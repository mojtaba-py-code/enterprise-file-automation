"""The pipeline: orchestrate processors over discovered files.

Design guarantees:

* The inbox file is never mutated — all work happens on a staging copy.
* A failure in one file never aborts the run; that file is recorded as failed
  and (optionally) copied to the ``failed/`` directory for inspection.
* Generated artifacts land in ``output/`` (separate from the inbox) so they are
  never re-scanned and reprocessed.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .config import AppConfig
from .exceptions import ProcessorError
from .logger import get_logger
from .models import FileContext, ProcessResult
from .processors import Processor, build_processors
from .state import StateStore
from .watcher import Discovered

_log = get_logger("pipeline")


@dataclass
class RunReport:
    """Aggregate outcome of a single batch run."""

    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[ProcessResult] = field(default_factory=list)

    @property
    def had_activity(self) -> bool:
        return self.processed > 0

    def add(self, result: ProcessResult) -> None:
        self.results.append(result)
        self.processed += 1
        if result.status == "success":
            self.succeeded += 1
        elif result.status == "failed":
            self.failed += 1
        else:
            self.skipped += 1


class Pipeline:
    def __init__(self, cfg: AppConfig, state: StateStore) -> None:
        self._cfg = cfg
        self._state = state
        self._processors: list[Processor] = build_processors(cfg)
        _log.debug("pipeline steps: %s", [p.name for p in self._processors])

    # -- public API --------------------------------------------------------- #
    def run(self, discovered: list[Discovered]) -> RunReport:
        """Process every discovered file and return an aggregate report."""
        report = RunReport()
        for item in discovered:
            result = self.process_one(item)
            self._state.record(result)
            report.add(result)
        if report.had_activity:
            self._state.save()
        return report

    def process_one(self, item: Discovered) -> ProcessResult:
        """Process a single file end to end, isolating any failure to it."""
        staging_dir = self._cfg.paths.staging / item.file_hash[:12]
        try:
            ctx = self._prepare(item, staging_dir)
            for processor in self._processors:
                ctx = processor.run(ctx)
            output_path = self._finalize(ctx)
            _log.info("processed %s -> %s", item.path.name, output_path.name)
            return ProcessResult(
                source_path=item.path,
                status="success",
                original_hash=item.file_hash,
                category=ctx.category,
                output_path=output_path,
                steps=ctx.steps,
            )
        except ProcessorError as exc:
            _log.error("failed %s: %s", item.path.name, exc)
            self._quarantine(item.path)
            return ProcessResult(
                source_path=item.path,
                status="failed",
                original_hash=item.file_hash,
                error=str(exc),
            )
        except OSError as exc:
            _log.error("I/O error on %s: %s", item.path.name, exc)
            self._quarantine(item.path)
            return ProcessResult(
                source_path=item.path,
                status="failed",
                original_hash=item.file_hash,
                error=f"I/O error: {exc}",
            )
        except Exception as exc:
            # Last line of defence. A processor — or a library it calls — can
            # raise something no one anticipated for one hostile input, and the
            # remaining files must still be processed. Logged with a traceback
            # so the surprise is recorded rather than swallowed.
            _log.exception("unexpected error on %s", item.path.name)
            self._quarantine(item.path)
            return ProcessResult(
                source_path=item.path,
                status="failed",
                original_hash=item.file_hash,
                error=f"unexpected error: {exc}",
            )
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

    # -- internals ---------------------------------------------------------- #
    def _prepare(self, item: Discovered, staging_dir: Path) -> FileContext:
        staging_dir.mkdir(parents=True, exist_ok=True)
        working = staging_dir / item.path.name
        shutil.copy2(item.path, working)
        return FileContext(
            source_path=item.path,
            working_path=working,
            original_hash=item.file_hash,
        )

    def _finalize(self, ctx: FileContext) -> Path:
        self._cfg.paths.output.mkdir(parents=True, exist_ok=True)
        destination = _unique(self._cfg.paths.output / ctx.working_path.name)
        shutil.move(str(ctx.working_path), str(destination))
        return destination

    def _quarantine(self, source: Path) -> None:
        """Copy a failed source file to ``failed/`` for manual inspection."""
        try:
            self._cfg.paths.failed.mkdir(parents=True, exist_ok=True)
            destination = _unique(self._cfg.paths.failed / source.name)
            shutil.copy2(source, destination)
        except OSError as exc:  # pragma: no cover - best-effort diagnostics
            _log.warning("could not quarantine %s: %s", source.name, exc)


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
