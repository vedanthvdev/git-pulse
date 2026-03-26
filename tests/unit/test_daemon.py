"""Unit tests for the daemon module.

Tests plist/systemd file generation, platform detection, and strategy pattern.
Does NOT call launchctl or systemctl — only tests string generation and backend selection.
"""

from __future__ import annotations

from unittest.mock import patch

from git_pulse.daemon import (
    PLIST_LABEL,
    DaemonBackend,
    LaunchdBackend,
    SystemdBackend,
    UnsupportedBackend,
    _find_git_pulse_bin,
    _get_backend,
)


class TestPlistGeneration:
    def test_contains_label(self):
        backend = LaunchdBackend()
        plist = backend._generate_plist(3600)
        assert PLIST_LABEL in plist

    def test_contains_interval(self):
        backend = LaunchdBackend()
        plist = backend._generate_plist(1800)
        assert "<integer>1800</integer>" in plist

    def test_contains_run_command(self):
        backend = LaunchdBackend()
        plist = backend._generate_plist(3600)
        assert "<string>run</string>" in plist
        assert "<string>--background</string>" in plist

    def test_contains_run_at_load(self):
        backend = LaunchdBackend()
        plist = backend._generate_plist(3600)
        assert "<key>RunAtLoad</key>" in plist
        assert "<true/>" in plist

    def test_contains_log_paths(self):
        backend = LaunchdBackend()
        plist = backend._generate_plist(3600)
        assert "launchd-stdout.log" in plist
        assert "launchd-stderr.log" in plist

    def test_valid_xml(self):
        backend = LaunchdBackend()
        plist = backend._generate_plist(3600)
        assert plist.startswith("<?xml version=")
        assert "</plist>" in plist


class TestSystemdGeneration:
    def test_service_contains_exec(self):
        backend = SystemdBackend()
        service = backend._generate_service()
        assert "ExecStart=" in service
        assert "run --background" in service

    def test_service_type_oneshot(self):
        backend = SystemdBackend()
        service = backend._generate_service()
        assert "Type=oneshot" in service

    def test_timer_contains_interval(self):
        backend = SystemdBackend()
        timer = backend._generate_timer(30)
        assert "OnUnitActiveSec=30min" in timer

    def test_timer_has_boot_delay(self):
        backend = SystemdBackend()
        timer = backend._generate_timer(60)
        assert "OnBootSec=5min" in timer

    def test_timer_persistent(self):
        backend = SystemdBackend()
        timer = backend._generate_timer(60)
        assert "Persistent=true" in timer


class TestBackendSelection:
    @patch("git_pulse.daemon.platform.system", return_value="Darwin")
    def test_selects_launchd_on_macos(self, _):
        backend = _get_backend()
        assert isinstance(backend, LaunchdBackend)

    @patch("git_pulse.daemon.platform.system", return_value="Linux")
    def test_selects_systemd_on_linux(self, _):
        backend = _get_backend()
        assert isinstance(backend, SystemdBackend)

    @patch("git_pulse.daemon.platform.system", return_value="Windows")
    def test_selects_unsupported_on_unknown(self, _):
        backend = _get_backend()
        assert isinstance(backend, UnsupportedBackend)

    def test_all_backends_implement_interface(self):
        for cls in [LaunchdBackend, SystemdBackend, UnsupportedBackend]:
            assert issubclass(cls, DaemonBackend)


class TestDaemonStatus:
    @patch("git_pulse.daemon.platform.system", return_value="Darwin")
    def test_status_no_plist(self, _, tmp_path, monkeypatch):
        backend = LaunchdBackend()
        backend.plist_path = tmp_path / "nonexistent.plist"
        info = backend.status()
        assert info["running"] == "no"
        assert "not installed" in info["reason"].lower()

    @patch("git_pulse.daemon.platform.system", return_value="Windows")
    def test_status_unsupported_platform(self, _):
        backend = UnsupportedBackend()
        info = backend.status()
        assert info["running"] == "unknown"


class TestFindBin:
    @patch("git_pulse.daemon.shutil.which", return_value="/usr/local/bin/git-pulse")
    def test_finds_on_path(self, _):
        result = _find_git_pulse_bin()
        assert "git-pulse" in result

    @patch("git_pulse.daemon.shutil.which", return_value=None)
    def test_fallback_to_sys_executable(self, _):
        result = _find_git_pulse_bin()
        assert "git_pulse.cli" in result
