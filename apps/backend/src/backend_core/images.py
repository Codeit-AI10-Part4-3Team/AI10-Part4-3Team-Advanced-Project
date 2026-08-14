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

from pathlib import Path
from uuid import UUID

MAX_BYTES = 10 * 1024 * 1024
"""10MB, from the contract's `SessionCreateRequest.productImage` description."""

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

    directory = Path(image_dir)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{session_id}{_SUFFIX[detect_format(payload)]}"
    destination.write_bytes(payload)
    return str(destination)
