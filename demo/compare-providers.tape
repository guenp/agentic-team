# Multi-provider comparison demo
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
Sleep 12

# ── Check status — all three providers running ────────────────

Type "team status"
Enter
Sleep 3

# ── Attach to the tmux session ────────────────────────────────

Type "team attach"
Enter
Sleep 3

# ── Browse the Claude worker ──────────────────────────────────

Ctrl+B
Type n
Sleep 5

# ── Browse the Codex worker ───────────────────────────────────

Ctrl+B
Type n
Sleep 5

# ── Browse the Gemini worker ──────────────────────────────────

Ctrl+B
Type n
Sleep 5

# ── Back to lead ──────────────────────────────────────────────

Ctrl+B
Type p
Sleep 1
Ctrl+B
Type p
Sleep 1
Ctrl+B
Type p
Sleep 2

# ── Detach ────────────────────────────────────────────────────

Ctrl+B
Type d
Sleep 2

# ── Check final status ────────────────────────────────────────

Type "team status"
Enter
Sleep 3

# ── Compare logs from all three providers ─────────────────────

Type "team logs cmd-injection"
Enter
Sleep 4

Type "team logs path-traversal"
Enter
Sleep 4

Type "team logs input-validation"
Enter
Sleep 4

# ── Ask the lead to compare ───────────────────────────────────

Set TypingSpeed 20ms
Type "team \"Review the output from all three workers with 'team logs'. Compare the findings and write a consolidated report.\""
Enter
Sleep 3
Set TypingSpeed 40ms

# ── Clean up ──────────────────────────────────────────────────

Type "team stop"
Enter
Sleep 2
