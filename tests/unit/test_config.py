"""Unit tests for the config module.

Tests YAML serialization, defaults, hashing, type coercion, and edge cases.
No git repos or filesystem side-effects beyond the isolated config dir.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from git_pulse.config import (
    Config,
    ConfigError,
    MIN_INTERVAL_MINUTES,
    MAX_INTERVAL_MINUTES,
    MIN_SCAN_DEPTH,
    MAX_SCAN_DEPTH,
    _ensure_list,
    config_exists,
    load_config,
    save_config,
    set_config_value,
)


class TestConfigDefaults:
    def test_all_defaults(self):
        config = Config()
        assert config.scan_paths == []
        assert config.scan_depth == 3
        assert config.interval_minutes == 60
        assert config.branches_to_update == ["master", "main"]
        assert config.fast_forward_rebase is False
        assert config.exclude_paths == []
        assert config.log_level == "INFO"

    def test_to_dict_matches_fields(self):
        config = Config(scan_paths=["~/a"], interval_minutes=30)
        d = config.to_dict()
        assert d["scan_paths"] == ["~/a"]
        assert d["interval_minutes"] == 30
        assert set(d.keys()) == {
            "scan_paths", "scan_depth", "interval_minutes",
            "branches_to_update", "fast_forward_rebase",
            "exclude_paths", "log_level",
        }


class TestConfigPersistence:
    def test_round_trip_all_fields(self):
        original = Config(
            scan_paths=["~/Code", "~/Work"],
            scan_depth=5,
            interval_minutes=30,
            branches_to_update=["main", "develop"],
            fast_forward_rebase=True,
            exclude_paths=["~/Code/old"],
            log_level="DEBUG",
        )
        save_config(original)
        loaded = load_config()

        assert loaded.scan_paths == original.scan_paths
        assert loaded.scan_depth == 5
        assert loaded.interval_minutes == 30
        assert loaded.branches_to_update == ["main", "develop"]
        assert loaded.fast_forward_rebase is True
        assert loaded.exclude_paths == ["~/Code/old"]
        assert loaded.log_level == "DEBUG"

    def test_load_returns_defaults_when_no_file(self):
        config = load_config()
        assert config.scan_paths == []
        assert config.interval_minutes == 60

    def test_load_fills_missing_keys_with_defaults(self, tmp_path: Path):
        """A config file with only some keys should still load with defaults for the rest."""
        from git_pulse.config import CONFIG_DIR, CONFIG_FILE
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            yaml.dump({"scan_paths": ["~/partial"]}, f)

        config = load_config()
        assert config.scan_paths == ["~/partial"]
        assert config.interval_minutes == 60
        assert config.branches_to_update == ["master", "main"]

    def test_config_exists_false_initially(self):
        assert config_exists() is False

    def test_config_exists_true_after_save(self):
        save_config(Config())
        assert config_exists() is True


class TestConfigHash:
    def test_same_inputs_same_hash(self):
        c1 = Config(scan_paths=["~/a"], branches_to_update=["master", "main"])
        c2 = Config(scan_paths=["~/a"], branches_to_update=["master", "main"])
        assert c1.config_hash == c2.config_hash

    def test_different_branches_different_hash(self):
        c1 = Config(scan_paths=["~/a"], branches_to_update=["master"])
        c2 = Config(scan_paths=["~/a"], branches_to_update=["master", "main"])
        assert c1.config_hash != c2.config_hash

    def test_different_scan_paths_different_hash(self):
        c1 = Config(scan_paths=["~/a"])
        c2 = Config(scan_paths=["~/a", "~/b"])
        assert c1.config_hash != c2.config_hash

    def test_different_scan_depth_different_hash(self):
        c1 = Config(scan_paths=["~/a"], scan_depth=2)
        c2 = Config(scan_paths=["~/a"], scan_depth=5)
        assert c1.config_hash != c2.config_hash

    def test_order_insensitive(self):
        """scan_paths and branches_to_update are sorted before hashing."""
        c1 = Config(scan_paths=["~/b", "~/a"], branches_to_update=["main", "master"])
        c2 = Config(scan_paths=["~/a", "~/b"], branches_to_update=["master", "main"])
        assert c1.config_hash == c2.config_hash

    def test_non_cache_fields_dont_affect_hash(self):
        """interval_minutes, fast_forward_rebase, log_level don't invalidate cache."""
        c1 = Config(scan_paths=["~/a"], interval_minutes=60, fast_forward_rebase=False)
        c2 = Config(scan_paths=["~/a"], interval_minutes=5, fast_forward_rebase=True)
        assert c1.config_hash == c2.config_hash


class TestSetConfigValue:
    def test_set_integer(self):
        save_config(Config())
        updated = set_config_value("interval_minutes", "30")
        assert updated.interval_minutes == 30

    def test_set_boolean_true(self):
        save_config(Config())
        updated = set_config_value("fast_forward_rebase", "true")
        assert updated.fast_forward_rebase is True

    def test_set_boolean_false(self):
        save_config(Config(fast_forward_rebase=True))
        updated = set_config_value("fast_forward_rebase", "no")
        assert updated.fast_forward_rebase is False

    def test_set_list(self):
        save_config(Config())
        updated = set_config_value("branches_to_update", "main, develop, release")
        assert updated.branches_to_update == ["main", "develop", "release"]

    def test_set_string(self):
        save_config(Config())
        updated = set_config_value("log_level", "debug")
        assert updated.log_level == "debug"

    def test_unknown_key_raises(self):
        save_config(Config())
        with pytest.raises(KeyError, match="Unknown config key"):
            set_config_value("nonexistent_key", "value")

    def test_persists_to_disk(self):
        save_config(Config(interval_minutes=60))
        set_config_value("interval_minutes", "15")
        reloaded = load_config()
        assert reloaded.interval_minutes == 15


class TestResolvedPaths:
    def test_resolved_scan_paths_expands_tilde(self):
        config = Config(scan_paths=["~/Code"])
        resolved = config.resolved_scan_paths
        assert len(resolved) == 1
        assert "~" not in str(resolved[0])
        assert resolved[0] == Path("~/Code").expanduser().resolve()

    def test_resolved_exclude_paths_expands_tilde(self):
        config = Config(exclude_paths=["~/old"])
        resolved = config.resolved_exclude_paths
        assert len(resolved) == 1
        assert "~" not in str(resolved[0])

    def test_empty_paths(self):
        config = Config()
        assert config.resolved_scan_paths == []
        assert config.resolved_exclude_paths == []


class TestValidation:
    def test_interval_clamped_to_min(self):
        config = Config(interval_minutes=0)
        assert config.interval_minutes == MIN_INTERVAL_MINUTES

    def test_interval_clamped_to_max(self):
        config = Config(interval_minutes=99999)
        assert config.interval_minutes == MAX_INTERVAL_MINUTES

    def test_interval_within_bounds_unchanged(self):
        config = Config(interval_minutes=30)
        assert config.interval_minutes == 30

    def test_scan_depth_clamped_to_min(self):
        config = Config(scan_depth=0)
        assert config.scan_depth == MIN_SCAN_DEPTH

    def test_scan_depth_clamped_to_max(self):
        config = Config(scan_depth=100)
        assert config.scan_depth == MAX_SCAN_DEPTH

    def test_scan_depth_within_bounds_unchanged(self):
        config = Config(scan_depth=5)
        assert config.scan_depth == 5

    def test_set_config_revalidates(self):
        save_config(Config())
        updated = set_config_value("interval_minutes", "-5")
        assert updated.interval_minutes == MIN_INTERVAL_MINUTES


class TestEnsureList:
    def test_none_becomes_empty_list(self):
        assert _ensure_list(None) == []

    def test_list_passthrough(self):
        assert _ensure_list(["a", "b"]) == ["a", "b"]

    def test_scalar_wrapped(self):
        assert _ensure_list("single") == ["single"]


class TestCorruptConfig:
    def test_load_invalid_yaml_returns_defaults(self):
        from git_pulse.config import CONFIG_DIR, CONFIG_FILE
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(": : :\ninvalid yaml {{[[")
        config = load_config()
        assert config.scan_paths == []
        assert config.interval_minutes == 60

    def test_load_non_dict_yaml_returns_defaults(self):
        from git_pulse.config import CONFIG_DIR, CONFIG_FILE
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text("- just\n- a\n- list\n")
        config = load_config()
        assert config.scan_paths == []


class TestAtomicWrite:
    def test_save_config_creates_file(self):
        save_config(Config(interval_minutes=42))
        loaded = load_config()
        assert loaded.interval_minutes == 42

    def test_save_config_overwrites_existing(self):
        save_config(Config(interval_minutes=10))
        save_config(Config(interval_minutes=20))
        loaded = load_config()
        assert loaded.interval_minutes == 20
