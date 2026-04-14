"""Provider registry for supported AI coding agents."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderConfig:
    """Configuration for a coding agent CLI provider."""

    name: str
    cli_command: str
    models: list[str] = field(default_factory=list)
    interactive_args: list[str] = field(default_factory=list)
    oneshot_args: list[str] = field(default_factory=list)
    resume_flag: str | None = None
    system_prompt_flag: str | None = None
    system_prompt_file_flag: str | None = None
    output_format_json: bool = False


PROVIDERS: dict[str, ProviderConfig] = {
    "claude": ProviderConfig(
        name="claude",
        cli_command="claude",
        models=["opus", "sonnet", "haiku"],
        interactive_args=[],
        oneshot_args=["--print", "--output-format", "json"],
        resume_flag="--resume",
        system_prompt_flag="--append-system-prompt",
        system_prompt_file_flag="--append-system-prompt-file",
        output_format_json=True,
    ),
    "codex": ProviderConfig(
        name="codex",
        cli_command="codex",
        models=["o4-mini", "o3", "gpt-4.1"],
        interactive_args=["--full-auto"],
        oneshot_args=["--full-auto", "--quiet"],
        resume_flag=None,
        system_prompt_flag=None,
        system_prompt_file_flag=None,
        output_format_json=False,
    ),
    "gemini": ProviderConfig(
        name="gemini",
        cli_command="gemini",
        models=["gemini-2.5-pro", "gemini-2.5-flash"],
        interactive_args=["--sandbox", "permissive"],
        oneshot_args=["--sandbox", "permissive"],
        resume_flag=None,
        system_prompt_flag=None,
        system_prompt_file_flag=None,
        output_format_json=False,
    ),
}


def get_provider(name: str) -> ProviderConfig:
    """Look up a provider by name. Raises KeyError with a friendly message."""
    if name not in PROVIDERS:
        available = ", ".join(PROVIDERS)
        raise KeyError(f"Unknown provider {name!r}. Available: {available}")
    return PROVIDERS[name]
