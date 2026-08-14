"""Upload validation: what we accept, what we refuse, and what we never do quietly.

The refusals here are all from 미결정_대장 N3 and the contract's `SessionCreateRequest` —
JPEG/PNG/WebP, 10MB, short edge at least 512px. None of them is a preference: the photo is
the input to image generation, and a render costs a GPU pass we only get once per session
(INV-3).
"""

from __future__ import annotations

import struct
from pathlib import Path
from uuid import uuid4

import pytest
from conftest import png_of

from backend_core import images


def _webp(width: int, height: int) -> bytes:
    """A lossy WebP (`VP8 `) header claiming a size."""
    body = b"VP8 " + struct.pack("<I", 10) + b"\x00" * 6
    body += struct.pack("<HH", width, height)
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body


def _jpeg(width: int, height: int) -> bytes:
    """A JPEG with one SOF0 frame and nothing else."""
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x00\x00\x00"
    return b"\xff\xd8\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9 + sof


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (png_of(1024, 768), "png"),
        (_webp(1024, 768), "webp"),
        (_jpeg(1024, 768), "jpeg"),
    ],
)
def test_the_three_accepted_formats_are_detected(payload: bytes, expected: str) -> None:
    assert images.detect_format(payload) == expected


@pytest.mark.parametrize(
    "payload",
    [b"GIF89a" + b"\x00" * 32, b"\x00\x00\x00\x18ftypheic", b"not an image at all"],
    ids=["GIF", "HEIC", "text"],
)
def test_the_refused_formats_are_refused(payload: bytes) -> None:
    """GIF and HEIC by name in the contract; anything else falls through the same door."""
    with pytest.raises(images.InvalidImageError):
        images.detect_format(payload)


def test_a_wav_is_not_mistaken_for_a_webp() -> None:
    """`RIFF` is a container marker WebP shares with WAV — the format name is four bytes
    further in, and checking only the prefix would accept audio as a photo."""
    wav = b"RIFF" + struct.pack("<I", 36) + b"WAVEfmt "
    with pytest.raises(images.InvalidImageError):
        images.detect_format(wav)


@pytest.mark.parametrize(
    ("payload", "image_format"),
    [(png_of(1024, 768), "png"), (_webp(1024, 768), "webp"), (_jpeg(1024, 768), "jpeg")],
)
def test_dimensions_are_read_from_the_header(payload: bytes, image_format: str) -> None:
    assert images.dimensions(payload, image_format) == (1024, 768)


def test_a_truncated_file_is_an_invalid_image_not_a_crash() -> None:
    """A cut-off upload looks exactly like a corrupt header. Either way it is a 422, not a
    500 with a stack trace."""
    truncated = png_of(1024, 768)[:12]

    with pytest.raises(images.InvalidImageError):
        images.dimensions(truncated, "png")


@pytest.mark.parametrize(
    ("width", "height"),
    [(511, 1024), (1024, 511), (1, 1)],
    ids=["narrow", "short", "tiny"],
)
def test_a_photo_below_the_short_edge_is_refused(tmp_path: Path, width: int, height: int) -> None:
    """512px on the **short** edge — so a wide-but-short photo fails just as a narrow one
    does (미결정_대장 N3)."""
    too_small = png_of(width, height)
    session_id = uuid4()

    with pytest.raises(images.InvalidImageError) as caught:
        images.store(tmp_path, session_id, too_small)

    # The message has to say the size, because "too small" alone leaves the user guessing
    # what would be big enough.
    assert f"{width}x{height}" in str(caught.value)


def test_an_oversized_file_is_refused_before_anything_parses_it(tmp_path: Path) -> None:
    with pytest.raises(images.InvalidImageError):
        images.store(tmp_path, uuid4(), b"\x89PNG\r\n\x1a\n" + b"\x00" * images.MAX_BYTES)


def test_the_stored_file_is_byte_identical_to_what_arrived(tmp_path: Path) -> None:
    """⚠️ Never re-encoded, never resized. The picture is the product (기획서 5.2) — a server
    that silently rewrites it changes what the user submitted, and a refusal is the honest
    alternative."""
    payload = png_of(1024, 768)

    stored = Path(images.store(tmp_path, uuid4(), payload))

    assert stored.read_bytes() == payload


def test_the_file_is_named_after_the_session_not_the_upload(tmp_path: Path) -> None:
    """An uploaded filename is attacker-controlled text: `../../etc/…` walks out of the
    directory and a repeated name overwrites someone else's photo. Nothing downstream reads
    the original name, so it is not kept."""
    session_id = uuid4()

    stored = Path(images.store(tmp_path, session_id, png_of(1024, 768)))

    assert stored.name == f"{session_id}.png"
    assert stored.parent == tmp_path
