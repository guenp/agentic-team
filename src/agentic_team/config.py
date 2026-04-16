"""Team configuration and state management via TOML files."""

from __future__ import annotations

import os
import tempfile
import tomllib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import tomli_w

# ── Path constants ──────────────────────────────────────────────

BASE_DIR = Path.home() / ".agentic-team"
TEAMS_DIR = BASE_DIR / "teams"
STATE_DIR = BASE_DIR / "state"
LOGS_DIR = BASE_DIR / "logs"
ACTIVE_LINK = BASE_DIR / "active"
DEFAULTS_PATH = BASE_DIR / "defaults.toml"


class StateFileError(RuntimeError):
    """Raised when persistent team state cannot be read or written safely."""


def ensure_dirs() -> None:
    """Create the base directory structure if it doesn't exist."""
    for d in (TEAMS_DIR, STATE_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ── User defaults ────────────────────────────────────────────────


@dataclass
class UserDefaults:
    provider: str | None = None
    model: str | None = None


def load_defaults() -> UserDefaults:
    """Load user defaults from ~/.agentic-team/defaults.toml."""
    if not DEFAULTS_PATH.exists():
        return UserDefaults()
    data = _load_toml_file(DEFAULTS_PATH, "user defaults")
    return UserDefaults(
        provider=data.get("provider"),
        model=data.get("model"),
    )


# ── Dataclasses ─────────────────────────────────────────────────


@dataclass
class TeamConfig:
    name: str
    provider: str  # "claude" | "codex" | "gemini"
    model: str | None = None
    worker_mode: str = "interactive"  # default mode for workers
    permissions: str = "auto"  # "auto" | "default" | "dangerously-skip-permissions"
    use_worktrees: bool = True
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
    source: str = "cli"  # "cli" | "file" | "lead"
    started_at: str = ""
    pid: int | None = None
    worktree_path: str | None = None
    branch_name: str | None = None
    last_error: str | None = None
    exit_code: int | None = None

    def __post_init__(self) -> None:
        if not self.tmux_window:
            self.tmux_window = self.name
        if not self.started_at:
            self.started_at = datetime.now(timezone.utc).isoformat()


# ── Team config persistence ─────────────────────────────────────


def _strip_none(d: dict) -> dict:
    """Remove keys with None values (TOML can't serialize None)."""
    return {k: v for k, v in d.items() if v is not None}


def _atomic_write_bytes(path: Path, data: bytes, description: str) -> None:
    """Write bytes atomically so readers never observe a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)
    except OSError as exc:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise StateFileError(
            f"Could not write {description} at {path}: {exc}. "
            f"Check permissions, free disk space, or remove the damaged file and retry."
        ) from exc


def _load_toml_file(path: Path, description: str) -> dict:
    """Load TOML with actionable recovery guidance on parse or I/O failures."""
    try:
        text = path.read_text()
    except OSError as exc:
        raise StateFileError(
            f"Could not read {description} at {path}: {exc}. "
            f"Check permissions or restore the file, then retry."
        ) from exc
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise StateFileError(
            f"Could not parse {description} at {path}: {exc}. "
            f"Fix the TOML or remove the file so it can be recreated."
        ) from exc


def save_team(config: TeamConfig) -> Path:
    """Save team config to TOML. Returns the path."""
    ensure_dirs()
    path = TEAMS_DIR / f"{config.name}.toml"
    data = _strip_none(asdict(config))
    _atomic_write_bytes(path, tomli_w.dumps(data).encode(), f"team config {config.name!r}")
    return path


def load_team(name: str) -> TeamConfig:
    """Load team config from TOML by name."""
    path = TEAMS_DIR / f"{name}.toml"
    if not path.exists():
        raise FileNotFoundError(f"Team {name!r} not found at {path}")
    data = _load_toml_file(path, f"team config {name!r}")
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
    data = {"workers": [_strip_none(asdict(w)) for w in workers]}
    _atomic_write_bytes(path, tomli_w.dumps(data).encode(), f"worker state for team {team_name!r}")


def load_workers(team_name: str) -> list[WorkerState]:
    """Load worker states from TOML."""
    path = _workers_path(team_name)
    if not path.exists():
        return []
    data = _load_toml_file(path, f"worker state for team {team_name!r}")
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


def create_session_log_dir(team_name: str) -> Path:
    """Create a timestamped session log directory.

    Returns a path like ``~/.agentic-team/logs/<team>/20260415-003621/``.
    Also writes a ``current`` symlink for easy access.
    """
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    session_dir = LOGS_DIR / team_name / ts
    session_dir.mkdir(parents=True, exist_ok=True)

    # Symlink "current" → this session for quick lookup
    current = LOGS_DIR / team_name / "current"
    if current.is_symlink() or current.exists():
        current.unlink()
    current.symlink_to(session_dir)

    return session_dir


def current_session_log_dir(team_name: str) -> Path | None:
    """Return the current session log directory, or None."""
    current = LOGS_DIR / team_name / "current"
    if current.is_symlink():
        return current.resolve()
    return None
