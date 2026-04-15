"""Fit captured pane output to a dashboard pane's dimensions.

Used by TmuxOrchestrator.multi_attach — invoked as:
    tmux capture-pane ... | python3 -m agentic_team._pane_fit W H
"""

import sys


def main() -> None:
    w = int(sys.argv[1])
    h = int(sys.argv[2])

    lines = [line.rstrip("\n") for line in sys.stdin]

    # Strip trailing blank lines so content is compact
    while lines and not lines[-1].strip():
        lines.pop()

    for line in lines[:h]:
        # Truncate to pane width, pad with spaces to overwrite old content
        print(line[:w].ljust(w))


if __name__ == "__main__":
    main()
