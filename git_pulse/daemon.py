"""Background daemon management for git-pulse.

Uses a strategy pattern: each platform backend (launchd, systemd) implements
install, uninstall, and status. The public API auto-selects the right backend.
"""

from __future__ import annotations

import abc
import platform
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from git_pulse.config import Config
from git_pulse.logger import get_logger

PLIST_LABEL = "com.git-pulse.updater"


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------

class DaemonBackend(abc.ABC):
    @abc.abstractmethod
    def install(self, config: Config) -> str: ...

    @abc.abstractmethod
    def uninstall(self) -> str: ...

    @abc.abstractmethod
    def status(self) -> dict[str, str]: ...


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _find_git_pulse_bin() -> str:
    """Resolve the absolute path to the git-pulse binary.

    Falls back to sys.executable-based invocation so launchd/systemd
    can find it even if PATH is minimal.
    """
    path = shutil.which("git-pulse")
    if path:
        return str(Path(path).resolve())
    return f"{sys.executable} -m git_pulse.cli"


# ---------------------------------------------------------------------------
# macOS launchd backend
# ---------------------------------------------------------------------------

class LaunchdBackend(DaemonBackend):
    def __init__(self) -> None:
        self.plist_dir = Path.home() / "Library" / "LaunchAgents"
        self.plist_path = self.plist_dir / f"{PLIST_LABEL}.plist"

    def install(self, config: Config) -> str:
        log = get_logger()
        interval_seconds = config.interval_minutes * 60

        self.plist_dir.mkdir(parents=True, exist_ok=True)
        (Path.home() / ".git-pulse" / "logs").mkdir(parents=True, exist_ok=True)

        self._unload(quiet=True)

        plist_content = self._generate_plist(interval_seconds)
        self.plist_path.write_text(plist_content)
        log.info("Wrote plist to %s", self.plist_path)

        result = subprocess.run(
            ["launchctl", "load", str(self.plist_path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            log.warning("launchctl load failed: %s", result.stderr.strip())
            return f"Plist written but launchctl load failed: {result.stderr.strip()}"

        log.info("Loaded launchd job %s", PLIST_LABEL)
        return f"Daemon started (launchd, every {interval_seconds // 60} min)"

    def uninstall(self) -> str:
        log = get_logger()
        self._unload()
        return "Daemon stopped and plist removed"

    def status(self) -> dict[str, str]:
        if not self.plist_path.exists():
            return {"running": "no", "reason": "Plist not installed"}
        result = subprocess.run(
            ["launchctl", "list", PLIST_LABEL],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return {"running": "yes", "backend": "launchd", "label": PLIST_LABEL}
        return {"running": "no", "reason": "Plist installed but not loaded"}

    def _unload(self, quiet: bool = False) -> None:
        log = get_logger()
        if self.plist_path.exists():
            subprocess.run(
                ["launchctl", "unload", str(self.plist_path)],
                capture_output=True,
            )
            if not quiet:
                log.info("Unloaded launchd job %s", PLIST_LABEL)
            self.plist_path.unlink(missing_ok=True)

    def _generate_plist(self, interval_seconds: int) -> str:
        bin_path = _find_git_pulse_bin()
        return textwrap.dedent(f"""\
            <?xml version="1.0" encoding="UTF-8"?>
            <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
              "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
            <plist version="1.0">
            <dict>
                <key>Label</key>
                <string>{PLIST_LABEL}</string>

                <key>ProgramArguments</key>
                <array>
                    <string>{bin_path}</string>
                    <string>run</string>
                    <string>--background</string>
                </array>

                <key>StartInterval</key>
                <integer>{interval_seconds}</integer>

                <key>RunAtLoad</key>
                <true/>

                <key>StandardOutPath</key>
                <string>{Path.home()}/.git-pulse/logs/launchd-stdout.log</string>

                <key>StandardErrorPath</key>
                <string>{Path.home()}/.git-pulse/logs/launchd-stderr.log</string>
            </dict>
            </plist>
        """)


# ---------------------------------------------------------------------------
# Linux systemd backend
# ---------------------------------------------------------------------------

class SystemdBackend(DaemonBackend):
    def __init__(self) -> None:
        self.systemd_dir = Path.home() / ".config" / "systemd" / "user"
        self.service_name = "git-pulse.service"
        self.timer_name = "git-pulse.timer"

    def install(self, config: Config) -> str:
        log = get_logger()
        self.systemd_dir.mkdir(parents=True, exist_ok=True)

        (self.systemd_dir / self.service_name).write_text(self._generate_service())
        (self.systemd_dir / self.timer_name).write_text(
            self._generate_timer(config.interval_minutes),
        )
        log.info("Wrote systemd files to %s", self.systemd_dir)

        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        result = subprocess.run(
            ["systemctl", "--user", "enable", "--now", self.timer_name],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            log.warning("systemctl enable failed: %s", result.stderr.strip())
            return f"Timer files written but enable failed: {result.stderr.strip()}"

        log.info("Enabled and started systemd timer %s", self.timer_name)
        return f"Daemon started (systemd, every {config.interval_minutes} min)"

    def uninstall(self) -> str:
        log = get_logger()
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", self.timer_name],
            capture_output=True,
        )
        (self.systemd_dir / self.service_name).unlink(missing_ok=True)
        (self.systemd_dir / self.timer_name).unlink(missing_ok=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        log.info("Stopped and removed systemd timer")
        return "Daemon stopped and systemd files removed"

    def status(self) -> dict[str, str]:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", self.timer_name],
            capture_output=True, text=True,
        )
        if result.stdout.strip() == "active":
            return {"running": "yes", "backend": "systemd", "timer": self.timer_name}
        return {"running": "no", "reason": f"Timer status: {result.stdout.strip()}"}

    def _generate_service(self) -> str:
        bin_path = _find_git_pulse_bin()
        return textwrap.dedent(f"""\
            [Unit]
            Description=git-pulse background repository updater

            [Service]
            Type=oneshot
            ExecStart={bin_path} run --background

            [Install]
            WantedBy=default.target
        """)

    def _generate_timer(self, interval_minutes: int) -> str:
        return textwrap.dedent(f"""\
            [Unit]
            Description=git-pulse periodic trigger

            [Timer]
            OnBootSec=5min
            OnUnitActiveSec={interval_minutes}min
            Persistent=true

            [Install]
            WantedBy=timers.target
        """)


# ---------------------------------------------------------------------------
# Unsupported platform fallback
# ---------------------------------------------------------------------------

class UnsupportedBackend(DaemonBackend):
    def install(self, config: Config) -> str:
        return f"Unsupported platform: {platform.system()}"

    def uninstall(self) -> str:
        return f"Unsupported platform: {platform.system()}"

    def status(self) -> dict[str, str]:
        return {"running": "unknown", "reason": f"Unsupported platform: {platform.system()}"}


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

def _get_backend() -> DaemonBackend:
    system = platform.system()
    if system == "Darwin":
        return LaunchdBackend()
    if system == "Linux":
        return SystemdBackend()
    return UnsupportedBackend()


# ---------------------------------------------------------------------------
# Public API (unchanged signatures for CLI compatibility)
# ---------------------------------------------------------------------------

def install_daemon(config: Config) -> str:
    return _get_backend().install(config)


def uninstall_daemon() -> str:
    return _get_backend().uninstall()


def daemon_status() -> dict[str, str]:
    return _get_backend().status()
