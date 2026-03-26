# git-pulse

Background Git repository updater that keeps your default branches fresh while you work.

You have 100+ repos on your machine. You rarely open most of them. **git-pulse** runs silently in the background, updating `master`, `main`, or whichever branches you tell it to — on an hourly cadence (configurable). When you finally open a repo, your default branches are already up to date.

## Key features

- **Silent background updates** via macOS launchd or Linux systemd — no window, no process bar, nothing
- **Branch-aware** — if you're on a feature branch, git-pulse updates master/main *behind the scenes* without touching your working directory
- **Multi-branch** — if a repo has both `master` and `main` and you track both, both get updated
- **Fail-fast** — if the network/VPN is down, the entire run aborts immediately instead of timing out on every repo
- **Auto-discovers new repos** — clone something new and it's picked up on the next run, no manual step needed
- **Cached** — repo metadata is cached so runs are fast (no filesystem walk every hour)
- **Safe** — never force-pushes, never touches dirty repos or repos mid-rebase, all pulls are `--ff-only`

## Install

### Via Homebrew (recommended)

```bash
brew tap vedanthvasudev/tap
brew install git-pulse
```

### From source

```bash
git clone https://github.com/vedanthvasudev/git-pulse.git
cd git-pulse
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Quick start

```bash
# Interactive setup — asks for scan paths, interval, branches
git-pulse init

# Start the background daemon
git-pulse start

# That's it. Your repos are now kept up to date automatically.
```

## Commands

| Command | Description |
|---|---|
| `git-pulse init` | Interactive setup wizard |
| `git-pulse run` | One-shot update of all cached repos |
| `git-pulse sync` | Alias for `run` — manual trigger |
| `git-pulse scan` | Force re-scan and rebuild the cache |
| `git-pulse start` | Install and start the background daemon |
| `git-pulse stop` | Stop and remove the daemon |
| `git-pulse status` | Show daemon status and cache info |
| `git-pulse logs` | Show recent log output (`-f` to follow) |
| `git-pulse config` | Print config; `config key value` to set |
| `git-pulse list` | List all cached repos and their branches |

## Configuration

Config lives at `~/.git-pulse/config.yml`. Created by `git-pulse init` or manually:

```yaml
scan_paths:
  - ~/Code/Modulo
  - ~/Code/personal

scan_depth: 3              # how deep to look for .git directories
interval_minutes: 60       # how often the daemon runs (default: 60)

branches_to_update:        # which branches to keep updated
  - master
  - main

fast_forward_rebase: false # opt-in: rebase feature branches onto updated default

exclude_paths:             # directories to skip
  - ~/Code/Modulo/archived

log_level: INFO
```

### How `branches_to_update` works

You provide a list of branch names. For each repo, git-pulse checks which of those branches actually exist locally:

- Repo has `master` → updates `master`
- Repo has `main` → updates `main`
- Repo has both → updates both
- Repo has neither → skips

### Update behavior per repo

| Your current branch | What happens |
|---|---|
| On `master` (tracked) | `git pull --ff-only` |
| On `feature/x` (not tracked) | `git fetch origin master:master` — master is updated silently, your feature branch and working directory are untouched |
| On `feature/x` with both `master` and `main` tracked | Both updated via `git fetch origin master:master` and `git fetch origin main:main` |

### Fast-forward rebase (opt-in)

When `fast_forward_rebase: true`, after updating the default branches, git-pulse will attempt to rebase your current feature branch onto the first tracked branch (usually master/main). If there are any conflicts, the rebase is immediately aborted — your branch is left exactly as it was.

## Cache

Repo metadata is cached at `~/.git-pulse/cache.json`. The cache:

- Is built on first run or via `git-pulse scan`
- Auto-detects new repos every run (lightweight directory listing, not a full git scan)
- Auto-prunes repos that no longer exist on disk
- Auto-rebuilds if you change `scan_paths` or `branches_to_update` in config

## Logs

```bash
git-pulse logs           # last 50 lines
git-pulse logs -n 100    # last 100 lines
git-pulse logs -f        # live tail
```

Logs are at `~/.git-pulse/logs/git-pulse.log` with automatic rotation (5 MB, 3 backups).

## How it works under the hood

1. **launchd** (macOS) or **systemd** (Linux) triggers `git-pulse run` at the configured interval
2. The runner loads the cached repo list and does a quick scan for new/removed repos
3. A **connectivity probe** (`git ls-remote`) is run against the first repo — if it fails, the entire run aborts
4. Each repo is processed: current branch detected, dirty/rebase state checked, then each tracked branch is updated
5. Results are logged to file

## Safety

- All pulls are `--ff-only` — no merge commits created
- Dirty repos (uncommitted changes) are always skipped
- Repos mid-rebase or mid-merge are always skipped
- Rebase is always wrapped in try/abort — conflicts are never left behind
- No force-push, no force-pull, no destructive operations

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v
```

## License

MIT
