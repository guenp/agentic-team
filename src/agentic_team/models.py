"""Provider registry for supported AI coding agents."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ProviderConfig:
    """Configuration for a coding agent CLI provider."""

    name: str
    cli_command: str
    install_hint: str
    login_hint: str
    models: list[str] = field(default_factory=list)
    interactive_args: list[str] = field(default_factory=list)
    oneshot_args: list[str] = field(default_factory=list)
    resume_flag: str | None = None
    system_prompt_flag: str | None = None
    system_prompt_file_flag: str | None = None
    output_format_json: bool = False
    ready_indicators: list[str] = field(default_factory=list)
    # Built-in logging: extra CLI args and env vars for capturing output
    log_args_interactive: list[str] = field(default_factory=list)
    log_args_oneshot: list[str] = field(default_factory=list)
    log_env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderHealth:
    """Best-effort local health snapshot for a provider CLI."""

    name: str
    cli_command: str
    installed: bool
    authenticated: bool
    cli_path: str | None = None
    detail: str = ""
    install_hint: str = ""
    login_hint: str = ""

    @property
    def viable(self) -> bool:
        return self.installed and self.authenticated


PROVIDERS: dict[str, ProviderConfig] = {
    "claude": ProviderConfig(
        name="claude",
        cli_command="claude",
        install_hint="Install Claude Code from https://docs.anthropic.com/en/docs/claude-code",
        login_hint="Run `claude auth login`.",
        models=["opus", "sonnet", "haiku"],
        interactive_args=[],
        oneshot_args=["--print", "--output-format", "stream-json"],
        resume_flag="--resume",
        system_prompt_flag="--append-system-prompt",
        system_prompt_file_flag="--append-system-prompt-file",
        output_format_json=True,
        ready_indicators=["Claude Code"],
        log_args_interactive=["--verbose"],
        log_args_oneshot=["--verbose"],
    ),
    "codex": ProviderConfig(
        name="codex",
        cli_command="codex",
        install_hint="Install Codex CLI from https://github.com/openai/codex",
        login_hint="Run `codex login`.",
        models=["o4-mini", "o3", "gpt-4.1"],
        interactive_args=["--full-auto"],
        oneshot_args=["--full-auto", "--quiet"],
        resume_flag=None,
        system_prompt_flag=None,
        system_prompt_file_flag=None,
        output_format_json=False,
        ready_indicators=["OpenAI Codex", "Use /skills"],
        log_env={"RUST_LOG": "info", "RUST_LOG_FORMAT": "json"},
    ),
    "gemini": ProviderConfig(
        name="gemini",
        cli_command="gemini",
        install_hint="Install Gemini CLI from https://github.com/google-gemini/gemini-cli",
        login_hint=(
            "Set `GEMINI_API_KEY` or `GOOGLE_API_KEY`, or configure auth in "
            "`~/.gemini/settings.json`."
        ),
        models=["gemini-2.5-pro", "gemini-2.5-flash"],
        interactive_args=["--yolo"],
        oneshot_args=["--yolo", "--prompt"],
        resume_flag="--resume",
        system_prompt_flag=None,
        system_prompt_file_flag=None,
        output_format_json=False,
        ready_indicators=["Gemini CLI", "Type your message"],
        log_args_interactive=["--debug"],
        log_args_oneshot=["--debug"],
    ),
}


def get_provider(name: str) -> ProviderConfig:
    """Look up a provider by name. Raises KeyError with a friendly message."""
    if name not in PROVIDERS:
        available = ", ".join(PROVIDERS)
        raise KeyError(f"Unknown provider {name!r}. Available: {available}")
    return PROVIDERS[name]


def get_provider_health(name: str) -> ProviderHealth:
    """Inspect whether a provider CLI is installed and authenticated."""
    provider = get_provider(name)
    cli_path = shutil.which(provider.cli_command)
    if not cli_path:
        return ProviderHealth(
            name=name,
            cli_command=provider.cli_command,
            installed=False,
            authenticated=False,
            detail=f"`{provider.cli_command}` is not installed.",
            install_hint=provider.install_hint,
            login_hint=provider.login_hint,
        )

    authenticated, detail = _check_provider_auth(provider)
    return ProviderHealth(
        name=name,
        cli_command=provider.cli_command,
        installed=True,
        authenticated=authenticated,
        cli_path=cli_path,
        detail=detail,
        install_hint=provider.install_hint,
        login_hint=provider.login_hint,
    )


def get_viable_providers() -> list[str]:
    """Return providers that are both installed and authenticated."""
    return [
        name for name in PROVIDERS
        if get_provider_health(name).viable
    ]


def describe_provider_flags(
    provider_name: str,
    *,
    model: str | None = None,
    permissions: str = "auto",
    mode: str = "interactive",
) -> list[str]:
    """Return the exact provider/runtime flags used for a launch."""
    provider = get_provider(provider_name)
    flags: list[str] = []

    if model:
        flags.extend(["--model", model])

    if mode == "oneshot":
        flags.extend(provider.oneshot_args)
    else:
        flags.extend(provider.interactive_args)

    if provider_name == "claude":
        flags.extend(["--permission-mode", permissions])

    return flags


def _check_provider_auth(provider: ProviderConfig) -> tuple[bool, str]:
    if provider.name == "claude":
        return _check_claude_auth(provider)
    if provider.name == "codex":
        return _check_codex_auth(provider)
    if provider.name == "gemini":
        return _check_gemini_auth(provider)
    return False, f"No auth check available for {provider.name!r}."


def _check_claude_auth(provider: ProviderConfig) -> tuple[bool, str]:
    result = _run_status_command([provider.cli_command, "auth", "status"])
    if result.returncode != 0:
        message = _clean_output(result.stderr or result.stdout) or "Authentication check failed."
        return False, message

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        message = _clean_output(result.stdout) or "Could not parse `claude auth status` output."
        return False, message

    if payload.get("loggedIn"):
        auth_method = payload.get("authMethod") or "authenticated"
        email = payload.get("email")
        detail = auth_method if not email else f"{auth_method} as {email}"
        return True, detail

    return False, "Claude Code is installed but not logged in."


def _check_codex_auth(provider: ProviderConfig) -> tuple[bool, str]:
    result = _run_status_command([provider.cli_command, "login", "status"])
    output = _clean_output("\n".join(
        part for part in (result.stdout, result.stderr) if part.strip()
    ))
    if result.returncode == 0 and "Logged in" in output:
        return True, output
    if "Not logged in" in output:
        return False, output
    if result.returncode != 0:
        return False, output or "Codex login status failed."
    return False, output or "Codex CLI is installed but login status is unclear."


def _check_gemini_auth(_provider: ProviderConfig) -> tuple[bool, str]:
    env_vars = {
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY"),
        "GOOGLE_API_KEY": os.environ.get("GOOGLE_API_KEY"),
        "GOOGLE_GENAI_USE_VERTEXAI": os.environ.get("GOOGLE_GENAI_USE_VERTEXAI"),
        "GOOGLE_GENAI_USE_GCA": os.environ.get("GOOGLE_GENAI_USE_GCA"),
    }
    configured_env = [name for name, value in env_vars.items() if value]
    if configured_env:
        joined = ", ".join(configured_env)
        return True, f"Environment configured via {joined}"

    gemini_dir = Path.home() / ".gemini"
    settings_path = gemini_dir / "settings.json"
    selected_type = ""
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
        except json.JSONDecodeError:
            return False, f"Could not parse {settings_path}."
        selected_type = str(
            settings.get("security", {})
            .get("auth", {})
            .get("selectedType", "")
        )

    credential_files = []
    for name in ("gemini-credentials.json", "google_accounts.json"):
        path = gemini_dir / name
        if path.exists():
            credential_files.append(path.name)

    if selected_type and credential_files:
        files = ", ".join(credential_files)
        return True, f"{selected_type} configured in {settings_path} ({files})"
    if selected_type:
        return False, (
            f"{settings_path} selects {selected_type!r}, but no local Gemini "
            "credential files were found."
        )
    return False, "No Gemini auth configuration found."


def _run_status_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
    )


def _clean_output(text: str) -> str:
    ignored_prefixes = (
        "WARNING: proceeding, even though we could not update PATH:",
    )
    return " ".join(
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.startswith(ignored_prefixes)
    )
