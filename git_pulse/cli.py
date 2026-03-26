"""CLI interface for git-pulse.

All user-facing commands are defined here using Typer.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from git_pulse import __version__
from git_pulse.cache import load_cache
from git_pulse.config import (
    CONFIG_FILE,
    Config,
    config_exists,
    load_config,
    save_config,
    set_config_value,
)
from git_pulse.daemon import daemon_status, install_daemon, uninstall_daemon
from git_pulse.logger import LOG_FILE, setup_logging
from git_pulse.scanner import full_scan, get_or_build_cache
from git_pulse.updater import RepoStatus, run_update

app = typer.Typer(
    name="git-pulse",
    help="Background Git repository updater — keeps your default branches fresh.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"git-pulse [bold]{__version__}[/bold]")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", "-v", help="Show version and exit.", callback=_version_callback, is_eager=True,
    ),
) -> None:
    """git-pulse: keep your local repos up to date while you work."""


@app.command()
def init() -> None:
    """Interactive setup — configure scan paths, interval, and branch names."""
    if config_exists():
        overwrite = typer.confirm("Config already exists. Overwrite?", default=False)
        if not overwrite:
            raise typer.Exit()

    console.print("\n[bold]git-pulse setup[/bold]\n")

    raw_paths = typer.prompt(
        "Directories to scan for git repos (comma-separated)",
        default="~/Code",
    )
    scan_paths = [p.strip() for p in raw_paths.split(",") if p.strip()]

    scan_depth = typer.prompt("Max directory depth to scan", default=3, type=int)

    interval = typer.prompt(
        "Update interval in minutes",
        default=60,
        type=int,
    )

    raw_branches = typer.prompt(
        "Branch names to keep updated (comma-separated)",
        default="master,main",
    )
    branches = [b.strip() for b in raw_branches.split(",") if b.strip()]

    ff_rebase = typer.confirm(
        "Enable fast-forward rebase on feature branches?",
        default=False,
    )

    raw_excludes = typer.prompt(
        "Paths to exclude (comma-separated, or empty)",
        default="",
    )
    excludes = [e.strip() for e in raw_excludes.split(",") if e.strip()]

    config = Config(
        scan_paths=scan_paths,
        scan_depth=scan_depth,
        interval_minutes=interval,
        branches_to_update=branches,
        fast_forward_rebase=ff_rebase,
        exclude_paths=excludes,
    )
    save_config(config)
    console.print(f"\n[green]Config saved to {CONFIG_FILE}[/green]")

    console.print("\nRunning initial scan ...")
    log = setup_logging(config.log_level, console=False)
    cache = full_scan(config)
    console.print(f"[green]Found {len(cache.repos)} repo(s)[/green]\n")

    start_daemon = typer.confirm("Start background daemon now?", default=True)
    if start_daemon:
        msg = install_daemon(config)
        console.print(f"[green]{msg}[/green]")


@app.command()
def run(
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview actions without executing"),
    background: bool = typer.Option(False, "--background", hidden=True),
) -> None:
    """Update all cached repos now (one-shot). Used by the daemon and for manual runs."""
    config = load_config()
    log = setup_logging(config.log_level, console=not background)

    cache = get_or_build_cache(config)
    result = run_update(cache, config, dry_run=dry_run)

    if result.aborted:
        console.print(f"[yellow]Aborted:[/yellow] {result.abort_reason}")
        raise typer.Exit(code=1)

    if not background:
        _print_run_summary(result)


@app.command()
def sync(
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview actions without executing"),
) -> None:
    """Manually trigger an update of all repos right now."""
    run(dry_run=dry_run, background=False)


@app.command()
def scan() -> None:
    """Force a full re-scan of all paths and rebuild the cache."""
    config = load_config()
    setup_logging(config.log_level)
    cache = full_scan(config)
    console.print(f"[green]Cache rebuilt: {len(cache.repos)} repo(s) found[/green]")


@app.command()
def start() -> None:
    """Install and start the background daemon."""
    config = load_config()
    setup_logging(config.log_level)
    msg = install_daemon(config)
    console.print(f"[green]{msg}[/green]")


@app.command()
def stop() -> None:
    """Stop and remove the background daemon."""
    setup_logging()
    msg = uninstall_daemon()
    console.print(f"[yellow]{msg}[/yellow]")


@app.command()
def status() -> None:
    """Show daemon status, cache info, and repo count."""
    config = load_config()
    setup_logging(config.log_level)

    info = daemon_status()
    cache = load_cache()

    table = Table(title="git-pulse status", show_header=False, border_style="dim")
    table.add_column("Key", style="bold")
    table.add_column("Value")

    table.add_row("Version", __version__)
    table.add_row("Daemon running", "[green]yes[/green]" if info.get("running") == "yes" else "[red]no[/red]")
    if info.get("backend"):
        table.add_row("Backend", info["backend"])
    if info.get("reason"):
        table.add_row("Reason", info["reason"])
    table.add_row("Interval", f"{config.interval_minutes} min")
    table.add_row("Branches", ", ".join(config.branches_to_update))
    table.add_row("FF rebase", "enabled" if config.fast_forward_rebase else "disabled")

    if cache:
        table.add_row("Cached repos", str(len(cache.repos)))
        table.add_row("Cache generated", cache.generated_at or "unknown")
    else:
        table.add_row("Cache", "[yellow]not built yet (run git-pulse scan)[/yellow]")

    console.print(table)


@app.command()
def logs(
    follow: bool = typer.Option(False, "--follow", "-f", help="Stream log output"),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
) -> None:
    """Show recent log output."""
    if not LOG_FILE.exists():
        console.print("[yellow]No log file found yet.[/yellow]")
        raise typer.Exit()

    if follow:
        try:
            subprocess.run(["tail", "-f", str(LOG_FILE)])
        except KeyboardInterrupt:
            pass
    else:
        subprocess.run(["tail", f"-{lines}", str(LOG_FILE)])


@app.command("config")
def config_cmd(
    key: str = typer.Argument(None, help="Config key to get or set"),
    value: str = typer.Argument(None, help="New value (omit to print current value)"),
) -> None:
    """Print or update configuration values."""
    config = load_config()

    if key is None:
        table = Table(title="git-pulse config", show_header=True, border_style="dim")
        table.add_column("Key", style="bold")
        table.add_column("Value")
        for k, v in config.to_dict().items():
            table.add_row(k, str(v))
        console.print(table)
        return

    if value is None:
        d = config.to_dict()
        if key in d:
            console.print(f"{key} = {d[key]}")
        else:
            console.print(f"[red]Unknown key: {key}[/red]")
            raise typer.Exit(code=1)
        return

    try:
        updated = set_config_value(key, value)
        console.print(f"[green]{key} = {getattr(updated, key)}[/green]")
    except (KeyError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)


@app.command("list")
def list_repos() -> None:
    """List all cached repos with their matching branches and current branch."""
    config = load_config()
    setup_logging(config.log_level, console=False)
    cache = get_or_build_cache(config)

    if not cache.repos:
        console.print("[yellow]No repos in cache. Run: git-pulse scan[/yellow]")
        raise typer.Exit()

    table = Table(title=f"Cached repos ({len(cache.repos)})", border_style="dim")
    table.add_column("#", style="dim", justify="right")
    table.add_column("Repository", style="bold")
    table.add_column("Tracked branches")
    table.add_column("Current branch")

    from git import InvalidGitRepositoryError, Repo

    for i, cached in enumerate(cache.repos, 1):
        try:
            repo = Repo(cached.path)
            current = repo.active_branch.name
        except (InvalidGitRepositoryError, TypeError):
            current = "[dim]unknown[/dim]"

        is_on_tracked = current in cached.matching_branches
        current_display = f"[green]{current}[/green]" if is_on_tracked else f"[cyan]{current}[/cyan]"

        table.add_row(
            str(i),
            Path(cached.path).name,
            ", ".join(cached.matching_branches),
            current_display,
        )

    console.print(table)


def _print_run_summary(result) -> None:
    table = Table(title="Update summary", border_style="dim")
    table.add_column("Repo", style="bold")
    table.add_column("Status")
    table.add_column("Branches updated")
    table.add_column("Note")

    for r in result.results:
        if r.status == RepoStatus.UPDATED:
            status_str = "[green]updated[/green]"
        elif r.status == RepoStatus.SKIPPED:
            status_str = "[yellow]skipped[/yellow]"
        else:
            status_str = "[red]error[/red]"

        table.add_row(
            Path(r.path).name,
            status_str,
            ", ".join(r.branches_updated) if r.branches_updated else "-",
            r.message or "",
        )

    console.print(table)
    console.print(
        f"\n[bold]Total:[/bold] {result.total}  "
        f"[green]Updated:[/green] {result.updated}  "
        f"[yellow]Skipped:[/yellow] {result.skipped}  "
        f"[red]Errors:[/red] {result.errors}"
    )
