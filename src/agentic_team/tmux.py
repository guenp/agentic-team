"""TmuxOrchestrator — all tmux interaction centralized here."""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path


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

    # ── Session lifecycle ────────────────────────────────────────

    def session_exists(self) -> bool:
        result = self._run(
            ["tmux", "has-session", "-t", self.session_name],
            check=False,
        )
        return result.returncode == 0

    def create_session(self, working_dir: str, lead_command: str) -> None:
        """Create a detached tmux session and start the team lead."""
        self._run([
            "tmux", "new-session",
            "-d",
            "-s", self.session_name,
            "-n", "lead",
            "-c", working_dir,
            "-x", "220",
            "-y", "50",
        ])
        # Start the team lead agent in the first window
        self.send_keys("lead", lead_command)

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

    def spawn_worker(
        self,
        window_name: str,
        command: str,
        working_dir: str,
        log_path: Path,
        initial_prompt: str | None = None,
    ) -> None:
        """Create a window, start logging, run the command, and optionally
        send an initial prompt after the agent starts."""
        self.create_window(window_name, working_dir)
        self.start_logging(window_name, log_path)
        self.send_keys(window_name, command)
        if initial_prompt:
            # Store the prompt to be sent once the agent is ready.
            # We write it to a file and have a helper send it after a delay,
            # since the agent needs time to start up before accepting input.
            self._queue_prompt(window_name, initial_prompt, log_path.parent)

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
            prompt = prompt_file.read_text()

            # Check if the agent is ready by scanning the pane for known
            # prompt indicators from each provider's startup output.
            try:
                output = self.capture_pane(target, lines=30)
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
                    # TUI agents (Codex, Gemini) need a brief delay
                    # between text input and Enter for the submit to register
                    self.send_keys(target, prompt, delay=0.5)
                    prompt_file.unlink()
                    delivered.append(target)
            except Exception:
                pass

        # Clean up empty dir
        if pending_dir.exists() and not list(pending_dir.iterdir()):
            pending_dir.rmdir()

        return delivered

    def kill_window(self, window_name: str) -> None:
        self._run(
            ["tmux", "kill-window", "-t", f"{self.session_name}:{window_name}"],
            check=False,
        )

    # ── Input / output ───────────────────────────────────────────

    def send_keys(self, target: str, text: str, delay: float = 0) -> None:
        """Send text to a tmux pane followed by Enter."""
        # Use literal flag (-l) to avoid tmux key interpretation,
        # then send Enter separately
        self._run([
            "tmux", "send-keys",
            "-t", f"{self.session_name}:{target}",
            "-l", text,
        ])
        if delay > 0:
            import time
            time.sleep(delay)
        self._run([
            "tmux", "send-keys",
            "-t", f"{self.session_name}:{target}",
            "Enter",
        ])

    def capture_pane(self, target: str, lines: int = 50) -> str:
        """Capture the last N lines of a pane."""
        result = self._run([
            "tmux", "capture-pane",
            "-t", f"{self.session_name}:{target}",
            "-p",
            "-S", f"-{lines}",
        ])
        return result.stdout

    # ── Logging ──────────────────────────────────────────────────

    def start_logging(self, target: str, log_path: Path) -> None:
        """Pipe pane output to a log file."""
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._run([
            "tmux", "pipe-pane",
            "-t", f"{self.session_name}:{target}",
            "-o",
            f"cat >> {shlex.quote(str(log_path))}",
        ])

    def stop_logging(self, target: str) -> None:
        self._run([
            "tmux", "pipe-pane",
            "-t", f"{self.session_name}:{target}",
        ])

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

    def is_pane_dead(self, target: str) -> bool:
        """Check if a pane's process has exited."""
        result = self._run([
            "tmux", "list-panes",
            "-t", f"{self.session_name}:{target}",
            "-F", "#{pane_dead}",
        ], check=False)
        if result.returncode != 0:
            return True  # Window doesn't exist
        return result.stdout.strip() == "1"

    # ── Attach ───────────────────────────────────────────────────

    def attach(self, window: str | None = None) -> None:
        """Attach to the session, replacing the current process.

        If window is specified, select that window first.
        """
        if window:
            self._run([
                "tmux", "select-window",
                "-t", f"{self.session_name}:{window}",
            ], check=False)

        # Replace current process with tmux attach
        os.execvp("tmux", [
            "tmux", "attach-session",
            "-t", self.session_name,
        ])

    def multi_attach(self, targets: list[str]) -> None:
        """Create a tiled dashboard window showing multiple workers and attach.

        Each target gets a pane with a live-updating view of its output.
        """
        if not targets:
            return

        multi_window = "multi"

        # Kill any existing multi window
        self.kill_window(multi_window)

        # Create the multi window with the first target's live view
        cmd = self._watch_cmd(targets[0])
        self._run([
            "tmux", "new-window",
            "-t", self.session_name,
            "-n", multi_window,
            "bash", "-c", cmd,
        ])

        # Split for each additional target
        for target in targets[1:]:
            cmd = self._watch_cmd(target)
            self._run([
                "tmux", "split-window",
                "-t", f"{self.session_name}:{multi_window}",
                "bash", "-c", cmd,
            ])
            # Re-tile after each split to keep panes balanced
            self._run([
                "tmux", "select-layout",
                "-t", f"{self.session_name}:{multi_window}",
                "tiled",
            ])

        # Attach to the multi window
        self.attach(multi_window)

    def _watch_cmd(self, target: str) -> str:
        """Build a shell command that live-streams a pane's output.

        Flicker-free refresh: captures to a variable, moves cursor home,
        prints each line with erase-to-EOL, then clears below.
        """
        session_target = shlex.quote(f"{self.session_name}:{target}")
        return (
            f"EL=$(printf '\\033[K'); tput clear; "
            f"while true; do "
            f"out=$(tmux capture-pane -t {session_target} -p -S -50); "
            f"printf '\\033[H'; "
            f"printf '\\033[1;36m=== {target} ===%s\\033[0m\\n' \"$EL\"; "
            f"printf '%s\\n' \"$out\" "
            f"| while IFS= read -r ln; do printf '%s%s\\n' \"$ln\" \"$EL\"; done; "
            f"printf '\\033[J'; "
            f"sleep 1; done"
        )

    # ── Internals ────────────────────────────────────────────────

    def _run(
        self,
        args: list[str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=check,
        )
