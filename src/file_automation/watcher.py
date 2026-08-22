"""Inbox scanner: find files that still need processing.

Batch mode: on each run we walk the inbox, hash every regular file and ask the
:class:`~file_automation.state.StateStore` whether it still needs work. This is
simple and robust — no OS file-watching required — and the hash-based state
makes it idempotent.

Only real files are picked up: symlinks are reported and skipped, never
followed, so nothing outside the inbox can be pulled into a run.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .hashing import sha256_of
from .logger import get_logger
from .state import StateStore

_log = get_logger("watcher")


@dataclass(frozen=True)
class Discovered:
    """A file found in the inbox together with its content hash."""

    path: Path
    file_hash: str


class InboxWatcher:
    def __init__(self, inbox: Path, state: StateStore, *, recursive: bool = True) -> None:
        self._inbox = inbox
        self._state = state
        self._recursive = recursive

    def _iter_files(self) -> Iterator[Path]:
        if not self._inbox.exists():
            return
        globber = self._inbox.rglob("*") if self._recursive else self._inbox.glob("*")
        for path in sorted(globber):
            if path.name.startswith("."):
                continue
            if path.is_symlink():
                # is_file() follows the link, so a symlink dropped in the inbox
                # would have its target's contents read, copied to output/ and
                # backed up — data from outside the directory we were pointed at.
                _log.warning("skipping symlink in inbox: %s", path)
                continue
            # Skip directories and anything that isn't a real, readable file.
            if path.is_file():
                yield path

    def scan(self) -> list[Discovered]:
        """Return files that need processing, in a stable order."""
        pending: list[Discovered] = []
        for path in self._iter_files():
            try:
                file_hash = sha256_of(path)
            except OSError as exc:
                # File may have vanished or be locked; skip this round.
                _log.warning("cannot hash %s: %s", path, exc)
                continue
            if self._state.should_process(file_hash):
                pending.append(Discovered(path=path, file_hash=file_hash))
        _log.debug("scan found %d file(s) needing work", len(pending))
        return pending
