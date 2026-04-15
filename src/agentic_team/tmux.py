"""TmuxOrchestrator — all tmux interaction centralized here."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import warnings
from dataclasses import dataclass
from pathlib import Path


EXIT_SENTINEL = "__AGENTIC_TEAM_EXIT__="
CAPTURE_RETRY_BUDGET = 2


@dataclass
class TmuxError(RuntimeError):
    """Structured tmux execution failure."""

    command: tuple[str, ...]
    returncode: int | None
    stderr: str

    def __str__(self) -> str:
        cmd = shlex.join(self.command)
        if self.returncode is None:
            return f"tmux command failed before execution: {cmd}. {self.stderr}"
        detail = self.stderr.strip() or "no stderr output"
        return f"tmux command failed ({self.returncode}): {cmd}. {detail}"


@dataclass
class TmuxWindow:
    index: int
    name: str
    pane_pid: int
    pane_dead: bool


class TmuxOrchestrator:
    """Manages a tmux session for an agentic team."""

    def __init__(self, session_name: str) -> None:
        self.session_name = session_name

    @staticmethod
    def ensure_available() -> None:
        """Fail fast with a friendly error when tmux is missing."""
        if shutil.which("tmux") is None:
            raise TmuxError(
                command=("tmux",),
                returncode=None,
                stderr="tmux is not installed or not available on PATH.",
            )

    # ── Session lifecycle ────────────────────────────────────────

    def session_exists(self) -> bool:
        result = self._run(
            ["tmux", "has-session", "-t", self.session_name],
            check=False,
        )
        return result.returncode == 0

    def create_session(self, working_dir: str, lead_command: str) -> None:
        """Create a detached tmux session and start the team lead."""
        try:
            self._run([
                "tmux", "new-session",
                "-d",
                "-s", self.session_name,
                "-n", "lead",
                "-c", working_dir,
                "-x", "220",
                "-y", "50",
            ])
            # Prevent tmux from renaming windows to the foreground process —
            # we rely on stable window names for status tracking.
            self._run([
                "tmux", "set-option", "-t", self.session_name,
                "allow-rename", "off",
            ])
            # Resize all windows when a client attaches, not just the active
            # one.  Without this, worker windows keep the initial 220x50 size
            # and TUI content renders off-screen in smaller terminals.
            self._run([
                "tmux", "set-option", "-t", self.session_name,
                "window-size", "smallest",
            ])
            # Start the team lead agent in the first window
            self.send_shell_command("lead", lead_command)
        except TmuxError:
            self.kill_session()
            raise

    def kill_session(self) -> None:
        if self.session_exists():
            self._run(
                ["tmux", "kill-session", "-t", self.session_name],
                check=False,
            )

    # ── Window management ────────────────────────────────────────

    def create_window(self, window_name: str, working_dir: str) -> None:
        """Create a new named window in the session."""
        self._run([
            "tmux", "new-window",
            "-t", self.session_name,
            "-n", window_name,
            "-c", working_dir,
        ])
        self._run([
            "tmux", "set-window-option",
            "-t", f"{self.session_name}:{window_name}",
            "automatic-rename", "off",
        ])

    def spawn_worker(
        self,
        window_name: str,
        command: str,
        working_dir: str,
        state_dir: Path,
        initial_prompt: str | None = None,
    ) -> None:
        """Create a window, run the command, and optionally send an
        initial prompt after the agent starts.

        Logging is handled by the agent CLI's built-in flags (--verbose,
        RUST_LOG, --debug) with stderr/stdout redirected in the command
        string itself — no pipe-pane needed.
        """
        self.create_window(window_name, working_dir)
        try:
            self.send_shell_command(window_name, command)
            if initial_prompt:
                self._queue_prompt(window_name, initial_prompt, state_dir)
        except (OSError, TmuxError):
            self.kill_window(window_name)
            raise

    def _queue_prompt(self, target: str, prompt: str, state_dir: Path) -> None:
        """Write a pending prompt file for an interactive worker.

        The prompt is sent by `deliver_pending_prompts()` once the agent
        is detected as ready (showing its input prompt).
        """
        pending_dir = state_dir / "pending_prompts"
        pending_dir.mkdir(parents=True, exist_ok=True)
        (pending_dir / target).write_text(prompt)

    def deliver_pending_prompts(self, state_dir: Path) -> list[str]:
        """Check for pending prompts and deliver them if the agent is ready.

        Returns list of worker names that received their prompts.
        """
        pending_dir = state_dir / "pending_prompts"
        if not pending_dir.exists():
            return []

        delivered = []
        for prompt_file in pending_dir.iterdir():
            target = prompt_file.name
            try:
                prompt = prompt_file.read_text()
            except OSError as exc:
                warnings.warn(
                    f"Could not read pending prompt for {target}: {exc}",
                    stacklevel=2,
                )
                continue

            # Check if the agent is ready by scanning the pane for known
            # prompt indicators from each provider's startup output.
            output = self._capture_pane_with_retry(target, lines=30)
            if output is None:
                continue
            ready = any(
                indicator in output
                for indicator in (
                    "Claude Code",      # Claude Code welcome banner
                    "OpenAI Codex",     # Codex welcome banner
                    "Gemini CLI",       # Gemini CLI welcome banner
                    "Type your message",  # Gemini input prompt
                )
            )
            if ready:
                try:
                    # TUI agents (Codex, Gemini) need a brief delay
                    # between text input and Enter for the submit to register
                    self.send_keys(target, prompt, delay=0.5)
                except TmuxError as exc:
                    warnings.warn(
                        f"Could not deliver pending prompt to {target}: {exc}",
                        stacklevel=2,
                    )
                    continue
                try:
                    prompt_file.unlink()
                except OSError as exc:
                    warnings.warn(
                        f"Prompt for {target} was sent but its pending file could not be removed: {exc}",
                        stacklevel=2,
                    )
                delivered.append(target)

        # Clean up empty dir
        if pending_dir.exists() and not list(pending_dir.iterdir()):
            try:
                pending_dir.rmdir()
            except OSError as exc:
                warnings.warn(
                    f"Could not remove empty pending prompt directory {pending_dir}: {exc}",
                    stacklevel=2,
                )

        return delivered

    def kill_window(self, window_name: str) -> None:
        self._run(
            ["tmux", "kill-window", "-t", f"{self.session_name}:{window_name}"],
            check=False,
        )

    # ── Input / output ───────────────────────────────────────────

    def send_keys(
        self, target: str, text: str, delay: float = 0,
        state_dir: Path | None = None,
    ) -> None:
        """Send text to a tmux pane followed by Enter."""
        resolved = self._resolve_target(target, state_dir)
        # Use literal flag (-l) to avoid tmux key interpretation,
        # then send Enter separately
        self._run([
            "tmux", "send-keys",
            "-t", f"{self.session_name}:{resolved}",
            "-l", text,
        ])
        if delay > 0:
            import time
            time.sleep(delay)
        self._run([
            "tmux", "send-keys",
            "-t", f"{self.session_name}:{resolved}",
            "Enter",
        ])

    def send_shell_command(
        self,
        target: str,
        command: str,
        state_dir: Path | None = None,
    ) -> None:
        """Send a shell command instrumented with an exit-code sentinel."""
        wrapped = (
            f"{command}; "
            "__agentic_team_exit=$?; "
            f"printf '\\n{EXIT_SENTINEL}%s\\n' \"$__agentic_team_exit\""
        )
        self.send_keys(target, wrapped, state_dir=state_dir)

    def capture_pane(
        self, target: str, lines: int = 50, state_dir: Path | None = None,
    ) -> str:
        """Capture the last N lines of a pane."""
        resolved = self._resolve_target(target, state_dir)
        result = self._run([
            "tmux", "capture-pane",
            "-t", f"{self.session_name}:{resolved}",
            "-p",
            "-S", f"-{lines}",
        ])
        return result.stdout

    # ── Monitoring ───────────────────────────────────────────────

    def list_windows(self) -> list[TmuxWindow]:
        """List all windows in the session."""
        if not self.session_exists():
            return []
        result = self._run([
            "tmux", "list-windows",
            "-t", self.session_name,
            "-F", "#{window_index}\t#{window_name}\t#{pane_pid}\t#{pane_dead}",
        ])
        windows = []
        for line in result.stdout.strip().splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            windows.append(TmuxWindow(
                index=int(parts[0]),
                name=parts[1],
                pane_pid=int(parts[2]),
                pane_dead=parts[3] == "1",
            ))
        return windows

    def is_pane_dead(
        self, target: str, state_dir: Path | None = None,
    ) -> bool:
        """Check if a pane's process has exited."""
        resolved = self._resolve_target(target, state_dir)
        result = self._run([
            "tmux", "list-panes",
            "-t", f"{self.session_name}:{resolved}",
            "-F", "#{pane_dead}",
        ], check=False)
        if result.returncode != 0:
            return True  # Window doesn't exist
        return result.stdout.strip() == "1"

    # ── Attach ───────────────────────────────────────────────────

    def attach(self, window: str | None = None) -> None:
        """Attach to the session, replacing the current process.

        If window is specified, select that window first.
        Forces all windows to resize to the session size so TUI agents
        render at the correct terminal width.
        """
        if window:
            self._run([
                "tmux", "select-window",
                "-t", f"{self.session_name}:{window}",
            ], check=False)

        # Ensure all windows resize to match the client's terminal
        # when we attach.  This is set in create_session too, but
        # older sessions may not have it.
        self._run([
            "tmux", "set-option", "-t", self.session_name,
            "window-size", "smallest",
        ], check=False)

        # Replace current process with tmux attach
        self.ensure_available()
        try:
            os.execvp("tmux", [
                "tmux", "attach-session",
                "-t", self.session_name,
            ])
        except OSError as exc:
            raise TmuxError(
                command=("tmux", "attach-session", "-t", self.session_name),
                returncode=exc.errno,
                stderr=str(exc),
            ) from exc

    def multi_attach(self, targets: list[str], state_dir: Path) -> None:
        """Join worker panes into a single tiled window and attach.

        If already in multi mode, just re-attaches to the existing tiled
        window without re-joining.  Uses ``tmux join-pane`` to move real
        worker panes into the first worker's window, then applies a
        tiled layout.  The join order is persisted so ``break_multi``
        can undo it later.
        """
        if not targets:
            return
        if len(targets) == 1:
            self.attach(targets[0])
            return

        multi_file = state_dir / "multi_targets"

        # Already in multi mode — verify the host still has joined panes.
        if multi_file.exists():
            host = multi_file.read_text().strip().splitlines()[0]
            pane_count = self._count_panes(host)
            if pane_count > 1:
                # Panes are still joined — just re-attach.
                self.attach(host)
                return
            # Stale file (session was restarted, etc.) — clean up and rejoin.
            multi_file.unlink()

        host = targets[0]

        # Join each subsequent worker into the host window
        for target in targets[1:]:
            self._run([
                "tmux", "join-pane",
                "-h",
                "-s", f"{self.session_name}:{target}",
                "-t", f"{self.session_name}:{host}",
            ], check=False)

        # Apply tiled layout
        self._run([
            "tmux", "select-layout",
            "-t", f"{self.session_name}:{host}",
            "tiled",
        ])

        # Persist the join order so break_multi can undo it
        multi_file.parent.mkdir(parents=True, exist_ok=True)
        multi_file.write_text("\n".join(targets))

        self.attach(host)

    def break_multi(self, state_dir: Path) -> list[str]:
        """Undo a previous ``multi_attach`` — break panes back into
        their own windows.

        Returns the list of restored worker names, or an empty list if
        there was nothing to undo.
        """
        multi_file = state_dir / "multi_targets"
        if not multi_file.exists():
            return []

        targets = multi_file.read_text().strip().splitlines()
        if len(targets) < 2:
            multi_file.unlink(missing_ok=True)
            return []

        host = targets[0]

        # Break each non-host pane back into its own window.
        # Always break pane index 1 (the next non-host pane), since
        # indices shift down after each break.  Use -s (source pane)
        # and -n (new window name) to restore the original name.
        for target in targets[1:]:
            self._run([
                "tmux", "break-pane",
                "-d",
                "-s", f"{self.session_name}:{host}.1",
                "-n", target,
            ], check=False)

        # Force all windows to resize to the full session size.
        # After break-pane, windows may retain the smaller dimensions
        # from the tiled layout.
        for target in targets:
            self._run([
                "tmux", "resize-window",
                "-t", f"{self.session_name}:{target}",
                "-A",
            ], check=False)

        multi_file.unlink(missing_ok=True)
        return targets

    # ── Internals ────────────────────────────────────────────────

    def _resolve_target(self, target: str, state_dir: Path | None) -> str:
        """Resolve a worker name to its tmux target.

        In multi mode, workers are joined into a single host window as
        numbered panes.  This method translates the worker name to
        ``host.pane_index`` so that capture-pane and is_pane_dead still
        work.  Outside multi mode, returns the target unchanged.
        """
        if state_dir is None:
            return target
        multi_file = state_dir / "multi_targets"
        if not multi_file.exists():
            return target
        targets = multi_file.read_text().strip().splitlines()
        if target in targets:
            host = targets[0]
            pane_index = targets.index(target)
            return f"{host}.{pane_index}"
        return target

    def _count_panes(self, target: str) -> int:
        """Return the number of panes in a window (0 if it doesn't exist)."""
        result = self._run([
            "tmux", "list-panes",
            "-t", f"{self.session_name}:{target}",
        ], check=False)
        if result.returncode != 0:
            return 0
        return len(result.stdout.strip().splitlines())

    def _capture_pane_with_retry(
        self,
        target: str,
        lines: int,
        state_dir: Path | None = None,
        retries: int = CAPTURE_RETRY_BUDGET,
    ) -> str | None:
        """Retry transient capture-pane failures a bounded number of times."""
        last_error: TmuxError | None = None
        for _ in range(retries):
            try:
                return self.capture_pane(target, lines=lines, state_dir=state_dir)
            except TmuxError as exc:
                last_error = exc
        if last_error is not None:
            warnings.warn(
                f"Could not capture tmux pane for {target} after {retries} attempts: {last_error}",
                stacklevel=2,
            )
        return None

    def _run(
        self,
        args: list[str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        self.ensure_available()
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise TmuxError(
                command=tuple(args),
                returncode=exc.errno,
                stderr=str(exc),
            ) from exc

        if check and result.returncode != 0:
            raise TmuxError(
                command=tuple(args),
                returncode=result.returncode,
                stderr=result.stderr or result.stdout or "tmux returned a non-zero exit status.",
            )
        return result
