"""Tests for the inbox watcher."""

from __future__ import annotations

from pathlib import Path

import pytest

from file_automation.config import AppConfig
from file_automation.state import StateStore
from file_automation.watcher import InboxWatcher


def _watcher(config: AppConfig) -> tuple[InboxWatcher, StateStore]:
    state = StateStore(config.paths.state_file, max_retries=config.max_retries)
    state.load()
    return InboxWatcher(config.paths.inbox, state, recursive=config.recursive), state


def test_scan_finds_new_files(config: AppConfig, sample_file: Path) -> None:
    watcher, _ = _watcher(config)
    found = watcher.scan()
    assert [d.path for d in found] == [sample_file]


def test_scan_skips_hidden_files(config: AppConfig) -> None:
    config.paths.inbox.mkdir(parents=True, exist_ok=True)
    (config.paths.inbox / ".hidden").write_text("x", encoding="utf-8")
    watcher, _ = _watcher(config)
    assert watcher.scan() == []


def test_symlink_is_skipped(config: AppConfig, sample_file: Path) -> None:
    """A symlink is never followed: its target lives outside the inbox."""
    outside = config.paths.inbox.parent / "outside.txt"
    outside.write_text("not the pipeline's to copy", encoding="utf-8")
    link = config.paths.inbox / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):  # pragma: no cover - platform dependent
        pytest.skip("symlinks not permitted on this platform")

    watcher, _ = _watcher(config)
    assert [d.path for d in watcher.scan()] == [sample_file]


def test_scan_missing_inbox_is_empty(config: AppConfig) -> None:
    watcher, _ = _watcher(config)
    assert watcher.scan() == []


def test_scan_is_stable_order(config: AppConfig) -> None:
    config.paths.inbox.mkdir(parents=True, exist_ok=True)
    for name in ("c.txt", "a.txt", "b.txt"):
        (config.paths.inbox / name).write_text("data" * 10, encoding="utf-8")
    watcher, _ = _watcher(config)
    names = [d.path.name for d in watcher.scan()]
    assert names == sorted(names)
