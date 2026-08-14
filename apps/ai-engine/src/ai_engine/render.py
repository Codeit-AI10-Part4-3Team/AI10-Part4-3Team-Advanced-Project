"""S6 렌더 이음매 — the one image a finalized session produces.

⚠️ **The stub and the real implementation are two branches of the same function**
(구현_범위 1.1절). Filling in `_render_with_model` is the whole of the real work.

Two properties the stub keeps even though it draws nothing:

- **Lossless WebP.** 검증 1순위 scores the Korean glyphs drawn into the comic, and a lossy
  image would have the scorer measuring compression artefacts instead of the model's
  rendering accuracy. The format is part of the contract, not an implementation detail.
- **The requested size, exactly.** The caller sends `spec`, and the job reports
  `width`/`height` from what came back. A placeholder of a convenient size would make the
  job report a size nobody asked for.
"""

import io
import logging

from PIL import Image, ImageDraw

from ai_engine.config import Settings
from ai_engine.models import ImageRenderRequest

logger = logging.getLogger(__name__)

STUB_BACKGROUND = (238, 238, 244)
STUB_FOREGROUND = (120, 120, 140)


def render_image(request: ImageRenderRequest, settings: Settings) -> bytes:
    """Return the finished image as lossless WebP bytes.

    Bytes, not a path: if this service decided where the file lives, the two apps would
    share a filesystem and the coupling would have escaped the HTTP contract (AGENTS.md).
    """
    logger.info(
        "image:render mode=%s outputType=%s spec=%dx%d",
        settings.generation_mode,
        request.output_type,
        request.spec.width,
        request.spec.height,
    )
    if settings.generation_mode == "stub":
        return _render_stub(request, settings)
    return _render_with_model(request, settings)


def _render_stub(request: ImageRenderRequest, settings: Settings) -> bytes:
    """A placeholder that cannot be mistaken for output.

    It says so on its face. A blank or pretty placeholder ends up pasted into a report as a
    result, which is the accident 구현_범위 1.1절 warns about.
    """
    width, height = request.spec.width, request.spec.height
    canvas = Image.new("RGB", (width, height), STUB_BACKGROUND)
    draw = ImageDraw.Draw(canvas)

    # Diagonals plus a border: unmistakably a placeholder at any zoom level, and it needs no
    # font file — bundling one just for the stub would ship a licence question with it.
    draw.rectangle([(0, 0), (width - 1, height - 1)], outline=STUB_FOREGROUND, width=4)
    draw.line([(0, 0), (width, height)], fill=STUB_FOREGROUND, width=4)
    draw.line([(0, height), (width, 0)], fill=STUB_FOREGROUND, width=4)
    draw.text((16, 16), f"[{settings.stub_marker}] {request.output_type}", fill=STUB_FOREGROUND)

    buffer = io.BytesIO()
    canvas.save(buffer, format="WEBP", lossless=True)
    return buffer.getvalue()


def _render_with_model(request: ImageRenderRequest, settings: Settings) -> bytes:
    """The real render. Not written yet.

    ⚠️ Raise rather than return a placeholder. A placeholder returned from the model branch
    would be indistinguishable from a successful render in every log and metric.
    """
    raise NotImplementedError(
        f"generation_mode={settings.generation_mode!r} but the model path is not implemented; "
        "set ADGEN_GENERATION_MODE=stub or fill in ai_engine.render._render_with_model"
    )
