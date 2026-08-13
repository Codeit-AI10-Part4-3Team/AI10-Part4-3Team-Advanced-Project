"""Catalog — the output types and art styles a user picks from.

Contract: packages/contracts/openapi.yaml. Edit it first (AGENTS.md 교체 순서).

⚠️ The art-style list itself is still open (미결정_대장 A절 3번, 차단). Eight is a
placeholder taken from 기획서 12.2's 4x2 grid, not a decision — so these models describe the
shape only, and nothing here may hard-code candidate values.
"""

from backend_core.models.common import Base, OutputType


class Template(Base):
    """Contract: `components.schemas.Template`. One output type as the screen shows it."""

    output_type: OutputType
    name: str
    example_image_url: str


class ArtStyle(Base):
    """Contract: `components.schemas.ArtStyle`.

    The reference image is not decoration — 2026-08-11 회의 decided styles are always
    presented with one, because a style cannot be conveyed in words. It must be generated
    with the same prompt fragment the real run uses, or the picker lies about the result.
    """

    art_style_id: str
    name: str
    example_image_url: str
