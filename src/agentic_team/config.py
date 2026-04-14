"""Team configuration and state management via TOML files."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

import tomli_w

# ── Path constants ──────────────────────────────────────────────

BASE_DIR = Path.home() / ".agentic-team"
TEAMS_DIR = BASE_DIR / "teams"
STATE_DIR = BASE_DIR / "state"
LOGS_DIR = BASE_DIR / "logs"
ACTIVE_LINK = BASE_DIR / "active"


def ensure_dirs() -> None:
    """Create the base directory structure if it doesn't exist."""
    for d in (TEAMS_DIR, STATE_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ── Dataclasses ─────────────────────────────────────────────────


@dataclass
class TeamConfig:
    name: str
    provider: str  # "claude" | "codex" | "gemini"
    model: str | None = None
    worker_mode: str = "interactive"  # default mode for workers
    permissions: str = "auto"  # "auto" | "default" | "dangerously-skip-permissions"
    use_worktrees: bool = False
    working_dir: str = "."
    max_workers: int = 6
    recursion: int = 1
    created_at: str = ""

    @property
    def tmux_session(self) -> str:
        return f"team-{self.name}"

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


@dataclass
class WorkerState:
    name: str
    task: str
    provider: str = "claude"
    model: str | None = None
    mode: str = "interactive"
    status: str = "running"  # "running" | "done" | "error"
    tmux_window: str = ""
    session_id: str | None = None  # agent session ID for --resume
    started_at: str = ""
    pid: int | None = None

    def __post_init__(self) -> None:
        if not self.tmux_window:
            self.tmux_window = self.name
        if not self.started_at:
            self.started_at = datetime.now(timezone.utc).isoformat()


# ── Team config persistence ─────────────────────────────────────


def _strip_none(d: dict) -> dict:
    """Remove keys with None values (TOML can't serialize None)."""
    return {k: v for k, v in d.items() if v is not None}


def save_team(config: TeamConfig) -> Path:
    """Save team config to TOML. Returns the path."""
    ensure_dirs()
    path = TEAMS_DIR / f"{config.name}.toml"
    data = _strip_none(asdict(config))
    path.write_bytes(tomli_w.dumps(data).encode())
    return path


def load_team(name: str) -> TeamConfig:
    """Load team config from TOML by name."""
    path = TEAMS_DIR / f"{name}.toml"
    if not path.exists():
        raise FileNotFoundError(f"Team {name!r} not found at {path}")
    data = tomllib.loads(path.read_text())
    return TeamConfig(**data)


def list_teams() -> list[str]:
    """List all team names."""
    if not TEAMS_DIR.exists():
        return []
    return sorted(p.stem for p in TEAMS_DIR.glob("*.toml"))


# ── Active team ──────────────────────────────────────────────────


def set_active_team(name: str) -> None:
    """Set the active team via symlink."""
    ensure_dirs()
    target = STATE_DIR / name
    target.mkdir(parents=True, exist_ok=True)
    if ACTIVE_LINK.is_symlink() or ACTIVE_LINK.exists():
        ACTIVE_LINK.unlink()
    ACTIVE_LINK.symlink_to(target)


def get_active_team_name() -> str | None:
    """Get the active team name, or None if no team is active."""
    if not ACTIVE_LINK.is_symlink():
        return None
    target = ACTIVE_LINK.resolve()
    return target.name


def get_active_team() -> TeamConfig:
    """Load the active team config. Raises if no team is active."""
    name = get_active_team_name()
    if name is None:
        raise RuntimeError(
            "No active team. Run 'team init <name>' to create one."
        )
    return load_team(name)


def clear_active_team() -> None:
    """Remove the active team symlink."""
    if ACTIVE_LINK.is_symlink() or ACTIVE_LINK.exists():
        ACTIVE_LINK.unlink()


# ── Worker state persistence ────────────────────────────────────


def _workers_path(team_name: str) -> Path:
    return STATE_DIR / team_name / "workers.toml"


def save_workers(team_name: str, workers: list[WorkerState]) -> None:
    """Save worker state list to TOML."""
    path = _workers_path(team_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"workers": [_strip_none(asdict(w)) for w in workers]}
    path.write_bytes(tomli_w.dumps(data).encode())


def load_workers(team_name: str) -> list[WorkerState]:
    """Load worker states from TOML."""
    path = _workers_path(team_name)
    if not path.exists():
        return []
    data = tomllib.loads(path.read_text())
    return [WorkerState(**w) for w in data.get("workers", [])]


def get_worker(team_name: str, worker_name: str) -> WorkerState | None:
    """Get a specific worker by name."""
    for w in load_workers(team_name):
        if w.name == worker_name:
            return w
    return None


def log_dir_for_team(team_name: str) -> Path:
    """Return the log directory for a team, creating it if needed."""
    d = LOGS_DIR / team_name
    d.mkdir(parents=True, exist_ok=True)
    return d
