"""Typed configuration: load YAML, validate it, resolve paths.

Secrets (encryption key, SMTP password) are *never* stored here; only the
*names* of the environment variables that hold them are. This keeps real
secrets out of both the config file and version control.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .exceptions import ConfigError

# Names of the pipeline steps this package knows how to run.
KNOWN_STEPS: frozenset[str] = frozenset(
    {"classify", "convert", "rename", "compress", "encrypt", "backup"}
)

# Largest image the converter will decode, in pixels (Pillow's own default).
DEFAULT_MAX_PIXELS = 89_478_485


# --------------------------------------------------------------------------- #
# Small typed helpers for reading a mapping with clear error messages.
# --------------------------------------------------------------------------- #
def _require_mapping(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"'{where}' must be a mapping, got {type(value).__name__}")
    return value


def _get(mapping: dict[str, Any], key: str, default: Any) -> Any:
    return mapping.get(key, default)


def _as_bool(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"'{where}' must be true/false, got {value!r}")
    return value


def _as_int(value: Any, where: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"'{where}' must be an integer, got {value!r}")
    if minimum is not None and value < minimum:
        raise ConfigError(f"'{where}' must be >= {minimum}, got {value}")
    return value


def _as_str(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"'{where}' must be a non-empty string, got {value!r}")
    return value


def _norm_ext(ext: str, where: str) -> str:
    ext = _as_str(ext, where).lower()
    if not ext.startswith("."):
        ext = "." + ext
    return ext


# --------------------------------------------------------------------------- #
# Section dataclasses
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ScheduleConfig:
    interval_minutes: int = 10
    run_immediately: bool = True


@dataclass(frozen=True)
class PathsConfig:
    inbox: Path
    output: Path
    failed: Path
    staging: Path
    backup: Path
    state_file: Path

    def all_dirs(self) -> tuple[Path, ...]:
        """Directories that must exist before a run (state_file is a file)."""
        return (self.inbox, self.output, self.failed, self.staging, self.backup)


@dataclass(frozen=True)
class ClassifyConfig:
    default_category: str = "misc"
    # extension -> category, pre-flattened for O(1) lookup.
    ext_to_category: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ConvertConfig:
    enabled: bool = True
    image_quality: int = 85
    #: Refuse to decode an image larger than this; a few kilobytes of crafted
    #: header can otherwise claim billions of pixels and exhaust memory.
    max_pixels: int = DEFAULT_MAX_PIXELS
    rules: dict[str, str] = field(default_factory=dict)  # from_ext -> to_ext


@dataclass(frozen=True)
class RenameConfig:
    enabled: bool = True
    pattern: str = "{date}_{category}_{stem}_{hash8}{ext}"


@dataclass(frozen=True)
class CompressConfig:
    enabled: bool = True
    format: str = "zip"
    min_size_bytes: int = 0


@dataclass(frozen=True)
class EncryptConfig:
    enabled: bool = False
    key_env: str = "FILE_AUTOMATION_ENCRYPTION_KEY"


@dataclass(frozen=True)
class BackupConfig:
    enabled: bool = True


@dataclass(frozen=True)
class EmailConfig:
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    use_tls: bool = True
    sender: str = ""
    recipients: tuple[str, ...] = ()
    username_env: str = "FILE_AUTOMATION_SMTP_USERNAME"
    password_env: str = "FILE_AUTOMATION_SMTP_PASSWORD"
    subject_prefix: str = "[FileAutomation]"
    only_on_activity: bool = True


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    file: Path | None = None
    console: bool = True


@dataclass(frozen=True)
class AppConfig:
    schedule: ScheduleConfig
    paths: PathsConfig
    pipeline: tuple[str, ...]
    classify: ClassifyConfig
    convert: ConvertConfig
    rename: RenameConfig
    compress: CompressConfig
    encrypt: EncryptConfig
    backup: BackupConfig
    email: EmailConfig
    logging: LoggingConfig
    max_retries: int = 3
    recursive: bool = True


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
_VALID_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_VALID_COMPRESS = frozenset({"zip"})


def _parse_schedule(raw: dict[str, Any]) -> ScheduleConfig:
    return ScheduleConfig(
        interval_minutes=_as_int(
            _get(raw, "interval_minutes", 10), "schedule.interval_minutes", minimum=1
        ),
        run_immediately=_as_bool(_get(raw, "run_immediately", True), "schedule.run_immediately"),
    )


def _parse_paths(raw: dict[str, Any], base: Path) -> PathsConfig:
    def path(key: str, default: str) -> Path:
        value = _as_str(_get(raw, key, default), f"paths.{key}")
        p = Path(value).expanduser()
        return p if p.is_absolute() else (base / p)

    return PathsConfig(
        inbox=path("inbox", "./watched/inbox"),
        output=path("output", "./watched/output"),
        failed=path("failed", "./watched/failed"),
        staging=path("staging", "./watched/.staging"),
        backup=path("backup", "./backups"),
        state_file=path("state_file", "./state.json"),
    )


def _parse_classify(raw: dict[str, Any]) -> ClassifyConfig:
    rules = _require_mapping(_get(raw, "rules", {}), "classify.rules")
    ext_to_category: dict[str, str] = {}
    for category, exts in rules.items():
        if not isinstance(exts, list):
            raise ConfigError(f"classify.rules.{category} must be a list of extensions")
        for ext in exts:
            key = _norm_ext(ext, f"classify.rules.{category}")
            if key in ext_to_category and ext_to_category[key] != category:
                raise ConfigError(
                    f"extension '{key}' mapped to both "
                    f"'{ext_to_category[key]}' and '{category}'"
                )
            ext_to_category[key] = str(category)
    return ClassifyConfig(
        default_category=_as_str(
            _get(raw, "default_category", "misc"), "classify.default_category"
        ),
        ext_to_category=ext_to_category,
    )


def _parse_convert(raw: dict[str, Any]) -> ConvertConfig:
    rules_raw = _require_mapping(_get(raw, "rules", {}), "convert.rules")
    rules = {
        _norm_ext(src, "convert.rules key"): _norm_ext(dst, f"convert.rules.{src}")
        for src, dst in rules_raw.items()
    }
    return ConvertConfig(
        enabled=_as_bool(_get(raw, "enabled", True), "convert.enabled"),
        image_quality=_as_int(_get(raw, "image_quality", 85), "convert.image_quality", minimum=1),
        max_pixels=_as_int(
            _get(raw, "max_pixels", DEFAULT_MAX_PIXELS), "convert.max_pixels", minimum=1
        ),
        rules=rules,
    )


def _parse_rename(raw: dict[str, Any]) -> RenameConfig:
    return RenameConfig(
        enabled=_as_bool(_get(raw, "enabled", True), "rename.enabled"),
        pattern=_as_str(
            _get(raw, "pattern", "{date}_{category}_{stem}_{hash8}{ext}"), "rename.pattern"
        ),
    )


def _parse_compress(raw: dict[str, Any]) -> CompressConfig:
    fmt = _as_str(_get(raw, "format", "zip"), "compress.format").lower()
    if fmt not in _VALID_COMPRESS:
        raise ConfigError(f"compress.format must be one of {sorted(_VALID_COMPRESS)}, got '{fmt}'")
    return CompressConfig(
        enabled=_as_bool(_get(raw, "enabled", True), "compress.enabled"),
        format=fmt,
        min_size_bytes=_as_int(
            _get(raw, "min_size_bytes", 0), "compress.min_size_bytes", minimum=0
        ),
    )


def _parse_encrypt(raw: dict[str, Any]) -> EncryptConfig:
    return EncryptConfig(
        enabled=_as_bool(_get(raw, "enabled", False), "encrypt.enabled"),
        key_env=_as_str(
            _get(raw, "key_env", "FILE_AUTOMATION_ENCRYPTION_KEY"), "encrypt.key_env"
        ),
    )


def _parse_backup(raw: dict[str, Any]) -> BackupConfig:
    return BackupConfig(enabled=_as_bool(_get(raw, "enabled", True), "backup.enabled"))


def _parse_email(raw: dict[str, Any]) -> EmailConfig:
    enabled = _as_bool(_get(raw, "enabled", False), "email.enabled")
    recipients_raw = _get(raw, "recipients", [])
    if not isinstance(recipients_raw, list):
        raise ConfigError("email.recipients must be a list")
    recipients = tuple(_as_str(r, "email.recipients[]") for r in recipients_raw)
    cfg = EmailConfig(
        enabled=enabled,
        smtp_host=str(_get(raw, "smtp_host", "")),
        smtp_port=_as_int(_get(raw, "smtp_port", 587), "email.smtp_port", minimum=1),
        use_tls=_as_bool(_get(raw, "use_tls", True), "email.use_tls"),
        sender=str(_get(raw, "sender", "")),
        recipients=recipients,
        username_env=_as_str(
            _get(raw, "username_env", "FILE_AUTOMATION_SMTP_USERNAME"), "email.username_env"
        ),
        password_env=_as_str(
            _get(raw, "password_env", "FILE_AUTOMATION_SMTP_PASSWORD"), "email.password_env"
        ),
        subject_prefix=str(_get(raw, "subject_prefix", "[FileAutomation]")),
        only_on_activity=_as_bool(_get(raw, "only_on_activity", True), "email.only_on_activity"),
    )
    if enabled and (not cfg.smtp_host or not cfg.sender or not cfg.recipients):
        raise ConfigError(
            "email.enabled is true but smtp_host, sender or recipients is missing"
        )
    return cfg


def _parse_logging(raw: dict[str, Any], base: Path) -> LoggingConfig:
    level = _as_str(_get(raw, "level", "INFO"), "logging.level").upper()
    if level not in _VALID_LEVELS:
        raise ConfigError(f"logging.level must be one of {sorted(_VALID_LEVELS)}, got '{level}'")
    file_raw = _get(raw, "file", None)
    file_path: Path | None = None
    if file_raw is not None:
        p = Path(_as_str(file_raw, "logging.file")).expanduser()
        file_path = p if p.is_absolute() else (base / p)
    return LoggingConfig(
        level=level,
        file=file_path,
        console=_as_bool(_get(raw, "console", True), "logging.console"),
    )


def _parse_pipeline(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        raise ConfigError("'pipeline' must be a non-empty list of step names")
    steps: list[str] = []
    for item in raw:
        name = _as_str(item, "pipeline[]")
        if name not in KNOWN_STEPS:
            raise ConfigError(
                f"unknown pipeline step '{name}'; valid steps: {sorted(KNOWN_STEPS)}"
            )
        if name in steps:
            raise ConfigError(f"pipeline step '{name}' listed more than once")
        steps.append(name)
    return tuple(steps)


def from_mapping(data: dict[str, Any], *, base_dir: Path | None = None) -> AppConfig:
    """Build an :class:`AppConfig` from an already-parsed mapping."""
    base = (base_dir or Path.cwd()).resolve()
    data = _require_mapping(data, "<root>")

    cfg = AppConfig(
        schedule=_parse_schedule(_require_mapping(_get(data, "schedule", {}), "schedule")),
        paths=_parse_paths(_require_mapping(_get(data, "paths", {}), "paths"), base),
        pipeline=_parse_pipeline(_get(data, "pipeline", list(KNOWN_STEPS))),
        classify=_parse_classify(_require_mapping(_get(data, "classify", {}), "classify")),
        convert=_parse_convert(_require_mapping(_get(data, "convert", {}), "convert")),
        rename=_parse_rename(_require_mapping(_get(data, "rename", {}), "rename")),
        compress=_parse_compress(_require_mapping(_get(data, "compress", {}), "compress")),
        encrypt=_parse_encrypt(_require_mapping(_get(data, "encrypt", {}), "encrypt")),
        backup=_parse_backup(_require_mapping(_get(data, "backup", {}), "backup")),
        email=_parse_email(_require_mapping(_get(data, "email", {}), "email")),
        logging=_parse_logging(_require_mapping(_get(data, "logging", {}), "logging"), base),
        max_retries=_as_int(_get(data, "max_retries", 3), "max_retries", minimum=1),
        recursive=_as_bool(_get(data, "recursive", True), "recursive"),
    )
    return cfg


def load_config(path: str | Path, *, base_dir: Path | None = None) -> AppConfig:
    """Load and validate configuration from a YAML file.

    Relative paths inside the file are resolved against ``base_dir`` (the
    current working directory by default), matching how a CLI user expects
    ``./watched`` to point at their project, not at the config file's folder.
    """
    config_path = Path(path).expanduser()
    if not config_path.is_file():
        raise ConfigError(f"config file not found: {config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - passthrough of parser detail
        raise ConfigError(f"invalid YAML in {config_path}: {exc}") from exc
    if raw is None:
        raise ConfigError(f"config file is empty: {config_path}")
    return from_mapping(raw, base_dir=base_dir)
