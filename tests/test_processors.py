"""Unit tests for individual pipeline processors."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from file_automation.config import (
    ClassifyConfig,
    CompressConfig,
    ConvertConfig,
    EncryptConfig,
    RenameConfig,
)
from file_automation.exceptions import ProcessorError
from file_automation.hashing import sha256_of
from file_automation.models import FileContext
from file_automation.processors.classifier import ClassifyProcessor
from file_automation.processors.compressor import CompressProcessor
from file_automation.processors.converter import ConvertProcessor
from file_automation.processors.encryptor import EncryptProcessor
from file_automation.processors.renamer import RenameProcessor


def _context(source: Path, staging: Path) -> FileContext:
    """Build a context with a staging copy, like the pipeline does."""
    staging.mkdir(parents=True, exist_ok=True)
    working = staging / source.name
    working.write_bytes(source.read_bytes())
    return FileContext(
        source_path=source,
        working_path=working,
        original_hash=sha256_of(source),
    )


@pytest.fixture
def text_source(tmp_path: Path) -> Path:
    src = tmp_path / "in" / "report.txt"
    src.parent.mkdir(parents=True)
    src.write_text("data " * 100, encoding="utf-8")
    return src


# --- classify --------------------------------------------------------------- #
def test_classify_known_extension(text_source: Path, tmp_path: Path) -> None:
    cfg = ClassifyConfig(default_category="misc", ext_to_category={".txt": "documents"})
    ctx = ClassifyProcessor(cfg).process(_context(text_source, tmp_path / "s"))
    assert ctx.category == "documents"


def test_classify_falls_back_to_default(text_source: Path, tmp_path: Path) -> None:
    cfg = ClassifyConfig(default_category="misc", ext_to_category={})
    ctx = ClassifyProcessor(cfg).process(_context(text_source, tmp_path / "s"))
    assert ctx.category == "misc"


# --- rename ----------------------------------------------------------------- #
def test_rename_applies_pattern(text_source: Path, tmp_path: Path) -> None:
    ctx = _context(text_source, tmp_path / "s")
    ctx.category = "documents"
    cfg = RenameConfig(enabled=True, pattern="{category}_{stem}_{hash8}{ext}")
    out = RenameProcessor(cfg).process(ctx)
    assert out.working_path.name == f"documents_report_{ctx.original_hash[:8]}.txt"
    assert out.working_path.exists()


def test_rename_bad_pattern_raises(text_source: Path, tmp_path: Path) -> None:
    ctx = _context(text_source, tmp_path / "s")
    cfg = RenameConfig(enabled=True, pattern="{does_not_exist}")
    with pytest.raises(ProcessorError):
        RenameProcessor(cfg).process(ctx)


# --- compress --------------------------------------------------------------- #
def test_compress_creates_zip(text_source: Path, tmp_path: Path) -> None:
    ctx = _context(text_source, tmp_path / "s")
    cfg = CompressConfig(enabled=True, format="zip", min_size_bytes=0)
    out = CompressProcessor(cfg).process(ctx)
    assert out.working_path.suffix == ".zip"
    with zipfile.ZipFile(out.working_path) as zf:
        assert zf.namelist() == ["report.txt"]


def test_compress_skips_small_file(text_source: Path, tmp_path: Path) -> None:
    ctx = _context(text_source, tmp_path / "s")
    cfg = CompressConfig(enabled=True, format="zip", min_size_bytes=10_000_000)
    out = CompressProcessor(cfg).process(ctx)
    assert out.working_path.suffix == ".txt"  # unchanged


# --- encrypt ---------------------------------------------------------------- #
def test_encrypt_roundtrip(
    text_source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("TEST_ENC_KEY", key)
    ctx = _context(text_source, tmp_path / "s")
    original = ctx.working_path.read_bytes()

    cfg = EncryptConfig(enabled=True, key_env="TEST_ENC_KEY")
    out = EncryptProcessor(cfg).process(ctx)

    assert out.working_path.suffix == ".enc"
    decrypted = Fernet(key.encode()).decrypt(out.working_path.read_bytes())
    assert decrypted == original


def test_encrypt_missing_key_raises(
    text_source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TEST_ENC_KEY", raising=False)
    ctx = _context(text_source, tmp_path / "s")
    cfg = EncryptConfig(enabled=True, key_env="TEST_ENC_KEY")
    with pytest.raises(ProcessorError, match="key not found"):
        EncryptProcessor(cfg).process(ctx)


def test_generate_key_is_valid() -> None:
    from cryptography.fernet import Fernet

    key = EncryptProcessor.generate_key()
    assert isinstance(Fernet(key.encode()), Fernet)


# --- convert ---------------------------------------------------------------- #
def test_convert_png_to_webp(tmp_path: Path) -> None:
    from PIL import Image

    src = tmp_path / "in" / "pic.png"
    src.parent.mkdir(parents=True)
    Image.new("RGBA", (8, 8), (255, 0, 0, 128)).save(src)

    ctx = _context(src, tmp_path / "s")
    cfg = ConvertConfig(enabled=True, image_quality=80, rules={".png": ".webp"})
    out = ConvertProcessor(cfg).process(ctx)

    assert out.working_path.suffix == ".webp"
    with Image.open(out.working_path) as img:
        assert img.size == (8, 8)


def test_convert_image_to_pdf(tmp_path: Path) -> None:
    from PIL import Image

    src = tmp_path / "in" / "pic.png"
    src.parent.mkdir(parents=True)
    Image.new("RGB", (8, 8), (0, 128, 0)).save(src)

    ctx = _context(src, tmp_path / "s")
    cfg = ConvertConfig(enabled=True, image_quality=80, rules={".png": ".pdf"})
    out = ConvertProcessor(cfg).process(ctx)
    assert out.working_path.suffix == ".pdf"
    assert out.working_path.read_bytes().startswith(b"%PDF")


def test_convert_unsupported_pair_is_skipped(text_source: Path, tmp_path: Path) -> None:
    ctx = _context(text_source, tmp_path / "s")
    cfg = ConvertConfig(enabled=True, image_quality=80, rules={".txt": ".pdf"})
    out = ConvertProcessor(cfg).process(ctx)
    assert out.working_path.suffix == ".txt"  # unchanged, no crash


def test_convert_disabled_without_rules(tmp_path: Path) -> None:
    cfg = ConvertConfig(enabled=True, image_quality=80, rules={})
    assert ConvertProcessor(cfg).enabled is False


def _png(tmp_path: Path, size: tuple[int, int]) -> Path:
    from PIL import Image

    src = tmp_path / "in" / "big.png"
    src.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (10, 20, 30)).save(src)
    return src


# 64 * 64 = 4096 pixels; Pillow raises past twice the limit and warns above it.
@pytest.mark.parametrize("max_pixels", [16, 3000])
def test_convert_rejects_an_oversized_image(tmp_path: Path, max_pixels: int) -> None:
    """A decompression bomb fails this one file, not the whole run.

    Pillow signals these with DecompressionBombError/Warning, neither of which
    is an OSError, so they must be translated into a ProcessorError.
    """
    from PIL import Image

    limit_before = Image.MAX_IMAGE_PIXELS
    ctx = _context(_png(tmp_path, (64, 64)), tmp_path / "s")
    cfg = ConvertConfig(
        enabled=True, image_quality=80, max_pixels=max_pixels, rules={".png": ".jpg"}
    )
    with pytest.raises(ProcessorError):
        ConvertProcessor(cfg).process(ctx)

    assert not (tmp_path / "s" / "big.jpg").exists()  # no half-written output
    assert limit_before == Image.MAX_IMAGE_PIXELS  # limit restored for other work
