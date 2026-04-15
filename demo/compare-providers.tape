# Quick multi-provider comparison demo
# Run with: vhs demo/compare-providers.tape

Output demo/compare-providers.gif

Require team
Require tmux

Set Shell "bash"
Set FontSize 20
Set Width 1400
Set Height 800
Set Padding 20
Set WindowBar Colorful
Set BorderRadius 8
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms

# ── Hide shell startup and set a clean prompt ──────────────────

Hide
Type "export PS1='$ '"
Enter
Type "clear"
Enter
Sleep 0.5
Show

# ── Show the task file ─────────────────────────────────────────

Type "cat demo/compare-providers.md"
Enter
Sleep 3

# ── Initialize a team with Claude as lead ──────────────────────

Type "team init compare --provider claude"
Enter
Sleep 3

# ── Run the multi-provider tasks ──────────────────────────────

Type "team run demo/compare-providers.md"
Enter
Sleep 8

# ── Check status ──────────────────────────────────────────────

Type "team status"
Enter
Sleep 3

# ── Attach and browse workers ─────────────────────────────────

Type "team attach"
Enter
Sleep 3

Ctrl+B
Type n
Sleep 5

Ctrl+B
Type n
Sleep 5

# ── Detach ────────────────────────────────────────────────────

Ctrl+B
Type d
Sleep 2

# ── Check final status ────────────────────────────────────────

Type "team status"
Enter
Sleep 3

# ── Clean up ──────────────────────────────────────────────────

Type "team stop"
Enter
Sleep 2
