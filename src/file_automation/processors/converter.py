"""Format conversion for images and image-backed documents.

Supported, self-contained conversions (via Pillow):

* image -> image  (e.g. ``.png`` -> ``.webp``)
* image -> pdf    (e.g. ``.jpg`` -> ``.pdf``)

Conversions that require external toolchains (e.g. ``.docx`` -> ``.pdf``) are
intentionally *not* faked: an unsupported rule is logged and skipped rather
than producing a corrupt file. ``Pillow`` is imported lazily so the dependency
is only needed when conversion actually runs.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import ClassVar

from ..config import AppConfig, ConvertConfig
from ..exceptions import ProcessorError
from ..models import FileContext
from .base import Processor

# Extensions Pillow can reliably read as images.
_IMAGE_EXTS = frozenset(
    {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"}
)
# Pillow save format keyed by target extension.
_SAVE_FORMAT = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
    ".bmp": "BMP",
    ".gif": "GIF",
    ".tiff": "TIFF",
    ".tif": "TIFF",
    ".pdf": "PDF",
}
# Target formats that have no alpha channel and need an RGB image.
_NEEDS_RGB = frozenset({".jpg", ".jpeg", ".pdf", ".bmp"})


class ConvertProcessor(Processor):
    name: ClassVar[str] = "convert"

    def __init__(self, cfg: ConvertConfig) -> None:
        super().__init__()
        self._cfg = cfg

    @classmethod
    def from_config(cls, cfg: AppConfig) -> ConvertProcessor:
        return cls(cfg.convert)

    @property
    def enabled(self) -> bool:
        return self._cfg.enabled and bool(self._cfg.rules)

    def process(self, ctx: FileContext) -> FileContext:
        src_ext = ctx.working_path.suffix.lower()
        target_ext = self._cfg.rules.get(src_ext)
        if target_ext is None or target_ext == src_ext:
            return ctx  # nothing to do for this file

        if not self._is_supported(src_ext, target_ext):
            self.log.info(
                "skip unsupported conversion %s -> %s for %s",
                src_ext,
                target_ext,
                ctx.working_path.name,
            )
            return ctx

        new_path = self._convert_image(ctx.working_path, target_ext)
        ctx.record_step(self.name, from_ext=src_ext, to_ext=target_ext, output=new_path.name)
        ctx.working_path = new_path
        self.log.debug("converted %s -> %s", src_ext, target_ext)
        return ctx

    @staticmethod
    def _is_supported(src_ext: str, target_ext: str) -> bool:
        return src_ext in _IMAGE_EXTS and target_ext in _SAVE_FORMAT

    def _convert_image(self, path: Path, target_ext: str) -> Path:
        try:
            from PIL import Image, UnidentifiedImageError
            from PIL.Image import Image as PILImage
        except ImportError as exc:  # pragma: no cover - dependency guaranteed by install
            raise ProcessorError(self.name, "Pillow is required for conversion") from exc

        destination = path.with_suffix(target_ext)
        save_format = _SAVE_FORMAT[target_ext]
        # A few kilobytes of crafted header can claim billions of pixels, so cap
        # what Pillow is willing to decode at the configured ceiling. The limit
        # is process-global, hence the restore below.
        previous_limit = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = self._cfg.max_pixels
        try:
            with warnings.catch_warnings():
                # Pillow only raises past *twice* the limit and merely warns in
                # between; promote the warning so the ceiling is the ceiling.
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path) as img:
                    out: PILImage = img
                    if target_ext in _NEEDS_RGB and img.mode not in ("RGB", "L"):
                        out = img.convert("RGB")
                    save_kwargs: dict[str, object] = {}
                    if save_format in ("JPEG", "WEBP"):
                        save_kwargs["quality"] = self._cfg.image_quality
                    out.save(destination, format=save_format, **save_kwargs)
        except (
            OSError,
            UnidentifiedImageError,
            ValueError,
            # Neither of these is an OSError, so without them a single hostile
            # image escapes the pipeline's per-file handler and ends the run.
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as exc:
            destination.unlink(missing_ok=True)
            raise ProcessorError(self.name, f"cannot convert {path.name}: {exc}") from exc
        finally:
            Image.MAX_IMAGE_PIXELS = previous_limit

        # Remove the pre-conversion working file so staging stays clean.
        if destination != path:
            path.unlink(missing_ok=True)
        return destination
