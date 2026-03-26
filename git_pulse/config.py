"""Configuration management for git-pulse.

Reads/writes ~/.git-pulse/config.yml and provides typed access to settings.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path.home() / ".git-pulse"
CONFIG_FILE = CONFIG_DIR / "config.yml"

DEFAULTS: dict[str, Any] = {
    "scan_paths": [],
    "scan_depth": 3,
    "interval_minutes": 60,
    "branches_to_update": ["master", "main"],
    "fast_forward_rebase": False,
    "exclude_paths": [],
    "log_level": "INFO",
}

MIN_INTERVAL_MINUTES = 1
MAX_INTERVAL_MINUTES = 1440  # 24 hours
MIN_SCAN_DEPTH = 1
MAX_SCAN_DEPTH = 10


class ConfigError(Exception):
    """Raised when config loading or validation fails."""


@dataclass
class Config:
    scan_paths: list[str] = field(default_factory=list)
    scan_depth: int = 3
    interval_minutes: int = 60
    branches_to_update: list[str] = field(default_factory=lambda: ["master", "main"])
    fast_forward_rebase: bool = False
    exclude_paths: list[str] = field(default_factory=list)
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        self.interval_minutes = _clamp(
            self.interval_minutes,
            MIN_INTERVAL_MINUTES,
            MAX_INTERVAL_MINUTES,
        )
        self.scan_depth = _clamp(
            self.scan_depth,
            MIN_SCAN_DEPTH,
            MAX_SCAN_DEPTH,
        )

    @property
    def resolved_scan_paths(self) -> list[Path]:
        return [Path(p).expanduser().resolve() for p in self.scan_paths]

    @property
    def resolved_exclude_paths(self) -> list[Path]:
        return [Path(p).expanduser().resolve() for p in self.exclude_paths]

    @property
    def config_hash(self) -> str:
        """Hash of the settings that affect cache validity."""
        key = f"{sorted(self.scan_paths)}|{sorted(self.branches_to_update)}|{self.scan_depth}|{sorted(self.exclude_paths)}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scan_paths": self.scan_paths,
            "scan_depth": self.scan_depth,
            "interval_minutes": self.interval_minutes,
            "branches_to_update": self.branches_to_update,
            "fast_forward_rebase": self.fast_forward_rebase,
            "exclude_paths": self.exclude_paths,
            "log_level": self.log_level,
        }


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _atomic_write(path: Path, content: str) -> None:
    """Write to a temp file then rename — safe against crashes mid-write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        os.replace(tmp, path)
    except BaseException:
        os.close(fd) if not os.get_inheritable(fd) else None
        Path(tmp).unlink(missing_ok=True)
        raise


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    """Load config from disk, falling back to defaults for missing keys."""
    if not CONFIG_FILE.exists():
        return Config(**DEFAULTS)

    try:
        with open(CONFIG_FILE) as f:
            raw = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError) as exc:
        logging.getLogger("git_pulse").warning(
            "Failed to parse config (%s), using defaults: %s",
            CONFIG_FILE,
            exc,
        )
        return Config(**DEFAULTS)

    if not isinstance(raw, dict):
        logging.getLogger("git_pulse").warning(
            "Config file is not a YAML mapping, using defaults",
        )
        return Config(**DEFAULTS)

    merged = {**DEFAULTS, **raw}
    return Config(
        scan_paths=_ensure_list(merged["scan_paths"]),
        scan_depth=int(merged["scan_depth"]),
        interval_minutes=int(merged["interval_minutes"]),
        branches_to_update=_ensure_list(merged["branches_to_update"]),
        fast_forward_rebase=bool(merged["fast_forward_rebase"]),
        exclude_paths=_ensure_list(merged["exclude_paths"]),
        log_level=str(merged["log_level"]).upper(),
    )


def _ensure_list(val: Any) -> list:
    """Coerce a scalar or None to a single-element list."""
    if val is None:
        return []
    if isinstance(val, list):
        return val
    return [val]


def save_config(config: Config) -> None:
    ensure_config_dir()
    content = yaml.dump(
        config.to_dict(),
        default_flow_style=False,
        sort_keys=False,
    )
    _atomic_write(CONFIG_FILE, content)


def config_exists() -> bool:
    return CONFIG_FILE.exists()


def set_config_value(key: str, value: str) -> Config:
    """Set a single config key and persist. Returns the updated config."""
    config = load_config()

    if key not in DEFAULTS:
        raise KeyError(f"Unknown config key: {key}")

    expected_type = type(DEFAULTS[key])

    if expected_type is list:
        parsed: Any = [v.strip() for v in value.split(",")]
    elif expected_type is bool:
        parsed = value.lower() in ("true", "1", "yes")
    elif expected_type is int:
        parsed = int(value)
    else:
        parsed = value

    setattr(config, key, parsed)
    config.__post_init__()
    save_config(config)
    return config
