# agentic-team demo
# Run with: vhs demo/demo.tape

Output demo/demo.gif

Require team
Require tmux

Set Shell "zsh"
Set FontSize 20
Set Width 1400
Set Height 800
Set Padding 20
Set WindowBar Colorful
Set BorderRadius 8
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms

# ── Show the task file ──────────────────────────────────────────

Type "cat demo/tasks.md"
Enter
Sleep 2

# ── Initialize a team ──────────────────────────────────────────

Type "team init demo --provider claude"
Enter
Sleep 3

# ── Run the tasks ─────────────────────────────────────────────

Type "team run demo/tasks.md"
Enter
Sleep 12

# ── Check status ──────────────────────────────────────────────

Type "team status"
Enter
Sleep 3

# ── Attach to the tmux session ────────────────────────────────

Type "team attach"
Enter
Sleep 3

# ── Navigate to first worker (adder) ─────────────────────────

Ctrl+B
Type n
Sleep 4

# ── Navigate to next worker (bear) ───────────────────────────

Ctrl+B
Type n
Sleep 4

# ── Navigate to next worker (crane) ──────────────────────────

Ctrl+B
Type n
Sleep 4

# ── Go back to the lead ──────────────────────────────────────

Ctrl+B
Type p
Sleep 1
Ctrl+B
Type p
Sleep 1
Ctrl+B
Type p
Sleep 2

# ── Detach from tmux ─────────────────────────────────────────

Ctrl+B
Type d
Sleep 2

# ── Check status again ───────────────────────────────────────

Type "team status"
Enter
Sleep 3

# ── View logs for all workers ────────────────────────────────

Type "team logs"
Enter
Sleep 4

# ── Clean up ─────────────────────────────────────────────────

Type "team stop"
Enter
Sleep 2
