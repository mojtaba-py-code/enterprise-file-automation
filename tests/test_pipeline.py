"""Integration tests for the Application/Pipeline over a real temp filesystem."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from file_automation.app import Application
from file_automation.config import AppConfig
from file_automation.state import StateStore


def test_run_once_processes_file(config: AppConfig, sample_file: Path) -> None:
    app = Application(config)
    app.prepare_directories()
    report = app.run_once()

    assert report.processed == 1
    assert report.succeeded == 1
    # Output is a zip (classify -> rename -> compress -> backup).
    outputs = list(config.paths.output.iterdir())
    assert len(outputs) == 1 and outputs[0].suffix == ".zip"
    # The inbox file is untouched.
    assert sample_file.exists()
    # A backup exists under the category folder.
    backups = list((config.paths.backup / "documents").iterdir())
    assert len(backups) == 1


def test_processed_file_not_reprocessed(config: AppConfig, sample_file: Path) -> None:
    app = Application(config)
    app.prepare_directories()
    assert app.run_once().processed == 1
    # Second run: nothing new.
    second = app.run_once()
    assert second.processed == 0


def test_edited_file_is_reprocessed(config: AppConfig, sample_file: Path) -> None:
    app = Application(config)
    app.prepare_directories()
    app.run_once()
    sample_file.write_text("brand new content", encoding="utf-8")
    report = app.run_once()
    assert report.processed == 1


def test_state_persisted(config: AppConfig, sample_file: Path) -> None:
    app = Application(config)
    app.prepare_directories()
    app.run_once()
    assert config.paths.state_file.exists()
    store = StateStore(config.paths.state_file)
    store.load()
    assert len(store) == 1


def test_failure_quarantines_and_records(
    config_dict: dict[str, Any],
    make_config: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Enable encryption but provide no key -> every file fails deterministically.
    config_dict["pipeline"] = ["classify", "encrypt"]
    config_dict["encrypt"] = {"enabled": True, "key_env": "MISSING_KEY_VAR"}
    config_dict["max_retries"] = 1  # one attempt, so this failure is the last one
    monkeypatch.delenv("MISSING_KEY_VAR", raising=False)
    cfg: AppConfig = make_config(config_dict)

    cfg.paths.inbox.mkdir(parents=True, exist_ok=True)
    (cfg.paths.inbox / "x.txt").write_text("secret", encoding="utf-8")

    app = Application(cfg)
    app.prepare_directories()
    report = app.run_once()

    assert report.failed == 1
    assert list(cfg.paths.failed.iterdir())  # quarantined copy exists
    assert not list(cfg.paths.output.iterdir())  # no partial output


def test_failure_retries_capped(
    config_dict: dict[str, Any], make_config: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_dict["pipeline"] = ["encrypt"]
    config_dict["encrypt"] = {"enabled": True, "key_env": "MISSING_KEY_VAR"}
    config_dict["max_retries"] = 2
    monkeypatch.delenv("MISSING_KEY_VAR", raising=False)
    cfg: AppConfig = make_config(config_dict)
    cfg.paths.inbox.mkdir(parents=True, exist_ok=True)
    (cfg.paths.inbox / "x.txt").write_text("secret", encoding="utf-8")

    app = Application(cfg)
    app.prepare_directories()
    assert app.run_once().failed == 1  # attempt 1
    # Still retryable, so nothing is quarantined yet.
    assert list(cfg.paths.failed.iterdir()) == []
    assert app.run_once().failed == 1  # attempt 2
    # Third scan: attempts hit max_retries -> file skipped, nothing processed.
    assert app.run_once().processed == 0
    # Exactly one copy of the input, not one per attempt.
    quarantined = sorted(p.name for p in cfg.paths.failed.iterdir())
    assert quarantined == ["x.txt"]


def test_unexpected_error_is_contained(
    config: AppConfig, sample_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whatever a processor throws, the run finishes and the file is failed."""
    from file_automation.processors.classifier import ClassifyProcessor

    def _boom(self: Any, ctx: Any) -> Any:
        raise RuntimeError("library surprise")

    monkeypatch.setattr(ClassifyProcessor, "process", _boom)

    app = Application(config)
    app.prepare_directories()
    report = app.run_once()

    assert report.processed == 1
    assert report.failed == 1
    assert "library surprise" in (report.results[0].error or "")


def test_oversized_image_fails_only_that_file(
    config_dict: dict[str, Any], make_config: Any
) -> None:
    """A decompression bomb is one failed file, not an aborted run."""
    from PIL import Image

    config_dict["pipeline"] = ["classify", "convert"]
    config_dict["convert"] = {"enabled": True, "max_pixels": 16, "rules": {".png": ".jpg"}}
    cfg: AppConfig = make_config(config_dict)
    cfg.paths.inbox.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (1, 2, 3)).save(cfg.paths.inbox / "bomb.png")
    (cfg.paths.inbox / "note.txt").write_text("fine", encoding="utf-8")

    app = Application(cfg)
    app.prepare_directories()
    report = app.run_once()

    assert report.processed == 2
    assert report.failed == 1
    assert report.succeeded == 1  # the healthy file still went through


def test_staging_is_cleaned(config: AppConfig, sample_file: Path) -> None:
    app = Application(config)
    app.prepare_directories()
    app.run_once()
    leftovers = list(config.paths.staging.rglob("*"))
    assert leftovers == []


def test_recursive_scan(config: AppConfig) -> None:
    nested = config.paths.inbox / "sub" / "deep.txt"
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_text("x" * 50, encoding="utf-8")
    app = Application(config)
    app.prepare_directories()
    assert app.run_once().processed == 1
