"""Uploaded images: validation and storage.

ADR-0010 keeps the bytes on local disk and only the path in the database. 세션_보관_정책 2절
gives them the shortest retention of anything we hold — 24 hours — because an uploaded photo
is the most personal thing a user hands us and the one we have least reason to keep.

⚠️ Files are named after the session, not after what the user called them. An uploaded
filename is attacker-controlled text: `../../etc/…` walks out of the directory, and a name
that collides overwrites someone else's photo. The original name is not kept, because
nothing downstream reads it.

⚠️ FastAPI-free. The route hands the bytes over already read; this module never sees an
`UploadFile`.
"""

from __future__ import annotations

import struct
from pathlib import Path
from uuid import UUID

MAX_BYTES = 10 * 1024 * 1024
"""10MB, from the contract's `SessionCreateRequest.productImage` description."""

MIN_SHORT_EDGE = 512
"""Shortest side, in pixels. 확정 사항 (미결정_대장 N3, 도메인_모델 3.1절).

⚠️ Not a quality preference. The photo is the input to image generation, and a source
below this cannot produce an ad anyone would use — accepting it spends a GPU render
(one per session, INV-3) to produce something the user will throw away.
"""

# Contract: JPEG / PNG / WebP. GIF and HEIC are refused.
#
# ⚠️ Sniffed from the bytes, never taken from the `Content-Type` header or the filename —
# both are supplied by the caller, so trusting them means the format check checks nothing.
_MAGIC: dict[str, tuple[bytes, ...]] = {
    "jpeg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "webp": (b"RIFF",),
}

_SUFFIX = {"jpeg": ".jpg", "png": ".png", "webp": ".webp"}


class InvalidImageError(ValueError):
    """The upload is not an image we accept. The route answers 422 `INVALID_IMAGE`.

    ⚠️ Refused, never quietly fixed. Re-encoding a rejected file, or cropping an oversized
    one, would change what the user submitted without telling them — and the picture is the
    product (기획서 5.2).
    """


def detect_format(payload: bytes) -> str:
    """The image format, by magic bytes. Raises `InvalidImageError` for anything else.

    WebP is checked in two parts because `RIFF` alone is a container marker shared with WAV
    — the format name sits four bytes later.
    """
    for name, prefixes in _MAGIC.items():
        if not payload.startswith(prefixes):
            continue
        if name == "webp" and payload[8:12] != b"WEBP":
            continue
        return name
    raise InvalidImageError(
        "지원하지 않는 이미지 형식입니다. JPEG, PNG, WebP 만 받습니다 (GIF 와 HEIC 는 제외)."
    )


def dimensions(payload: bytes, image_format: str) -> tuple[int, int]:
    """`(width, height)`, read straight out of the file header.

    ⚠️ Parsed by hand rather than with Pillow, on purpose. Pillow would be a runtime
    dependency in both the CI install and the deployed image, and everything it buys here is
    four integers that each format writes at a fixed offset. We never decode pixels — the
    bytes go to disk untouched, because re-encoding what the user submitted is exactly what
    `InvalidImageError` exists to avoid.

    Raises `InvalidImageError` for a header that claims a format and then does not carry it,
    which is also what a truncated upload looks like.
    """
    try:
        if image_format == "png":
            # IHDR is always the first chunk: 8-byte signature, 4-byte length, 4-byte type.
            return _uint32(payload, 16), _uint32(payload, 20)
        if image_format == "webp":
            return _webp_dimensions(payload)
        return _jpeg_dimensions(payload)
    except (IndexError, struct.error, ValueError) as exc:
        raise InvalidImageError(
            "이미지 크기를 읽지 못했습니다. 파일이 잘렸거나 형식이 손상되었습니다."
        ) from exc


def _uint32(payload: bytes, offset: int) -> int:
    return int(struct.unpack_from(">I", payload, offset)[0])


def _webp_dimensions(payload: bytes) -> tuple[int, int]:
    """WebP keeps its size in a chunk whose layout depends on which of three it is."""
    chunk = payload[12:16]
    if chunk == b"VP8X":
        # 24-bit little-endian, stored as (value - 1).
        return (
            int.from_bytes(payload[24:27], "little") + 1,
            int.from_bytes(payload[27:30], "little") + 1,
        )
    if chunk == b"VP8L":
        bits = int.from_bytes(payload[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8 ":
        return (
            int(struct.unpack_from("<H", payload, 26)[0]) & 0x3FFF,
            int(struct.unpack_from("<H", payload, 28)[0]) & 0x3FFF,
        )
    raise ValueError(f"unknown WebP chunk {chunk!r}")


def _jpeg_dimensions(payload: bytes) -> tuple[int, int]:
    """JPEG has no fixed offset — the size lives in a frame header somewhere in the stream.

    Walk the markers until one of the SOF (start-of-frame) kinds appears. The excluded
    codes are not frames: `C4` is a Huffman table, `C8` is reserved and `CC` is arithmetic
    coding, and treating any of them as a frame reads two unrelated bytes as a dimension.
    """
    offset = 2
    while offset < len(payload):
        if payload[offset] != 0xFF:
            raise ValueError("lost marker alignment")
        marker = payload[offset + 1]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height = int(struct.unpack_from(">H", payload, offset + 5)[0])
            width = int(struct.unpack_from(">H", payload, offset + 7)[0])
            return width, height
        offset += 2 + int(struct.unpack_from(">H", payload, offset + 2)[0])
    raise ValueError("no start-of-frame marker")


def store(image_dir: str | Path, session_id: UUID, payload: bytes) -> str:
    """Validate and write the image. Returns the reference stored on the brief.

    ⚠️ The returned value is a **path**, and the contract calls the field `productImageUrl`.
    They do not match yet: the contract has no route that serves an image back, so there is
    no URL to build. Storing a path keeps the bytes and their reference together until that
    route exists, and turning it into a URL is then one function, here. Do not invent the
    serving route to close the gap — that is contract surface, and the contract comes first
    (AGENTS.md 교체 순서).
    """
    if not payload:
        raise InvalidImageError("이미지가 비어 있습니다.")
    if len(payload) > MAX_BYTES:
        raise InvalidImageError(
            f"이미지가 너무 큽니다. 최대 {MAX_BYTES // (1024 * 1024)}MB 입니다."
        )

    image_format = detect_format(payload)
    width, height = dimensions(payload, image_format)
    if min(width, height) < MIN_SHORT_EDGE:
        raise InvalidImageError(
            f"사진이 너무 작습니다. 짧은 변이 {MIN_SHORT_EDGE}px 이상이어야 합니다 "
            f"(받은 크기 {width}x{height})."
        )

    directory = Path(image_dir)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{session_id}{_SUFFIX[image_format]}"
    destination.write_bytes(payload)
    return str(destination)
