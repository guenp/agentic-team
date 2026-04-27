# GasTown Learnings for agentic-team

Research into [GasTown](https://github.com/gastownhall/gastown) (Steve Yegge's
"Kubernetes for AI coding agents") to identify patterns worth adopting and
anti-patterns to avoid in agentic-team.

---

## What is GasTown

GasTown is an open-source multi-agent orchestration framework written in Go
(~189k LOC). Released January 2026 by Steve Yegge, it coordinates 20-30 AI
coding agents (Claude Code, Gemini, Codex, Cursor, AMP, and others) working
simultaneously on a single codebase.

Its core thesis: at scale (10+ agents), manual coordination collapses.
GasTown replaces ad-hoc oversight with structured roles, persistent state,
and automated recovery.

**Key links:**

- GitHub: `gastownhall/gastown`
- Docs: gastown.dev
- Design philosophy: "Nondeterministic Idempotence" — sessions are ephemeral,
  but workflow definitions and acceptance criteria persist in git-backed state,
  so crashed agents resume rather than restart.

---

## Architecture

### Three-tier hierarchy: Town → Rigs → Workers

| Tier | Analogy | Purpose |
|------|---------|---------|
| **Town** | Kubernetes cluster | Workspace directory containing all projects and agents |
| **Rig** | Namespace/Pod group | Project container wrapping a single git repo |
| **Worker** | Pod | Individual AI agent operating within a rig |

### Seven specialized agent roles

| Role | Scope | Function |
|------|-------|----------|
| **Mayor** | Town | Primary coordinator; analyzes tasks, decomposes work, distributes to workers |
| **Polecats** | Rig | Ephemeral workers that execute tasks in parallel, produce merge requests |
| **Refinery** | Rig | Bors-style merge queue with CI gating and automatic bisection on failure |
| **Witness** | Rig | Per-rig lifecycle monitor; detects stuck agents, triggers recovery |
| **Deacon** | Town | Cross-rig supervisor daemon running continuous patrol loops |
| **Dogs** | Town | Infrastructure maintenance workers assisting the Deacon |
| **Crew** | Rig | Named, persistent per-rig agents for collaborative human-managed work |

### Communication model

All agents run in isolated **tmux sessions** — identical to agentic-team.
GasTown communicates with agents via `send-keys`. Any terminal-based CLI agent
works with zero modifications.

Structured inter-agent messaging goes through a `mail.Router`. Agents can also
discover predecessor sessions via `.events.jsonl` logs (the "Seance" feature),
which provides cross-session context continuity.

### State management

State persists in **Beads** — atomic work units stored in **Dolt** (a
Git-for-data SQL database). Bead IDs use a prefix + 5-char alphanumeric format
(e.g., `gt-abc12`). Workflow templates are defined in TOML as **Formulas**,
which compile into **Protomolecules**, then instantiate as executable
**Molecules** with tracked steps.

### Orchestration pattern (MEOW)

Mayor-Enhanced Orchestration Workflow:

1. Human describes goals to the Mayor
2. Mayor analyzes and decomposes into components
3. Creates a "convoy" (ticket bundle) with tracked issues
4. Spawns Polecat agents and distributes work via hooks
5. Monitors progress; Witness/Deacon handle failures
6. Refinery merges results with CI gating
7. Mayor summarizes completion

---

## Key features

### What GasTown does well

1. **Crash recovery via persistent hooks (GUPP):**
   "If there is work on your hook, YOU MUST RUN IT." Hooks are git worktrees
   with persistent state. Workers check hooks on startup and resume work across
   session restarts. This eliminates the "lost work" problem when agents crash.

2. **Three-tier health monitoring:**
   Witness (per-rig) → Deacon (cross-rig) → escalation to Mayor/human. Stuck
   agents are detected automatically with severity-routed escalation
   (CRITICAL/HIGH/MEDIUM).

3. **Automated merge queue (Refinery):**
   Bors-style merge processor with automatic rebasing and bisection when merges
   fail. Agents produce merge requests; the Refinery handles ordering,
   conflicts, and CI.

4. **Structured inter-agent messaging:**
   A `mail.Router` provides typed message delivery between agents, beyond raw
   tmux `send-keys`. Enables coordination without context window bloat.

5. **Session history discovery (Seance):**
   Agents can query `.events.jsonl` logs from predecessor sessions. When an
   agent crashes and a new session picks up the bead, it has context on what
   the previous session decided and accomplished.

6. **Capacity scheduling:**
   Config-driven governor that prevents API rate limit exhaustion when running
   20+ agents. Queues work rather than failing.

7. **Federated coordination (Wasteland Federation):**
   Cross-instance coordination via DoltHub for multi-team setups.

---

## Comparison with agentic-team

| Dimension | agentic-team | GasTown |
|-----------|-------------|---------|
| **Language** | Python (~4.3k LOC) | Go (~189k LOC) |
| **Execution layer** | tmux sessions | tmux sessions (identical approach) |
| **Agent hierarchy** | 2-tier: Lead + Workers | 7 specialized roles across 3 tiers |
| **State persistence** | TOML files (atomic writes) | Dolt database (SQL + git semantics) |
| **Inter-agent comms** | `send-keys` only | `send-keys` + `mail.Router` + `.events.jsonl` |
| **Crash recovery** | Manual restart; oneshot resume via session ID | Automatic via GUPP hooks; beads persist across sessions |
| **Completion detection** | Pane capture heuristics (provider-specific) | Pane capture + event logs + Witness daemon |
| **Merge handling** | None (agents commit directly) | Automated merge queue with CI gating and bisection |
| **Health monitoring** | `team doctor` (manual, pre-flight) | Three-tier daemon (Witness → Deacon → Mayor) |
| **Task definition** | Markdown taskfiles or lead decomposition | TOML Formulas → Protomolecules → Molecules |
| **Scaling target** | 1-6 workers (practical) | 20-30 workers (design target) |
| **Provider support** | Claude, Codex, Gemini | Claude (primary) + 7 others |
| **Setup complexity** | `pip install`, needs tmux | Go binary + Dolt + Beads + tmux + Claude CLI |
| **Maturity model** | Lightweight tool for small teams | Enterprise-oriented framework for power users |
| **Cost profile** | Low (few agents) | High (reports of $100/hr peak burn) |

### Where the approaches converge

Both projects made the same foundational bet: **tmux as the universal agent
runtime**. Both use `send-keys` for communication and `capture-pane` for status
detection. Both support multiple AI providers. Both use a lead/coordinator
agent that decomposes tasks for workers.

### Where they diverge

GasTown invests heavily in **durability** (Dolt, Beads, GUPP hooks) and
**automated recovery** (Witness, Deacon, Refinery). agentic-team invests in
**simplicity** (TOML files, single CLI, minimal dependencies) and
**accessibility** (works with `pip install` and any tmux).

agentic-team treats workers as relatively independent; GasTown treats them as
nodes in a managed workflow graph with explicit handoffs and merge ordering.

---

## Recommendations

Specific, actionable ideas for improving agentic-team, ordered by
impact-to-effort ratio.

### 1. Add crash recovery for interactive workers

**Problem:** When an interactive worker's agent crashes (OOM, API timeout,
context overflow), work is lost. The worker state shows "running" but the pane
is dead or at a shell prompt.

**GasTown approach:** GUPP hooks persist the current task to disk. On restart,
the agent checks its hook and resumes.

**Recommendation:** On worker spawn, write the task + worker metadata to a
recovery file at `state/<team>/recovery/<worker>.toml`. When `team status`
detects a dead pane for an interactive worker, offer `team restart <worker>`
that re-spawns with the original task. The recovery file already has all needed
context.

**Files to modify:**
- `src/agentic_team/cli.py` — add `restart` command (near `spawn-worker`)
- `src/agentic_team/config.py` — add recovery file read/write
- `src/agentic_team/status.py` — detect crashed-but-recoverable workers

### 2. Add a stuck-worker detector

**Problem:** Interactive workers can get stuck (waiting for approval, looping
on an error, or idle after completing a sub-task). Currently only `team status`
shows this, and it requires manual inspection.

**GasTown approach:** The Witness daemon runs continuous patrol loops, detecting
stuck agents via timeout + pane inspection.

**Recommendation:** Add a `--watch` flag to `team wait` that, in addition to
polling for completion, warns when a worker has been in the same state for
longer than a configurable timeout (e.g., 5 minutes). This is much lighter
than a daemon but solves 80% of the problem.

**Files to modify:**
- `src/agentic_team/status.py` — track last-state-change timestamp per worker
- `src/agentic_team/cli.py` — add `--watch` to `team wait` with timeout alerts

### 3. Add structured worker output collection

**Problem:** When workers finish, the lead must read logs or pane captures to
understand what happened. There's no structured summary.

**GasTown approach:** Beads and event logs create a structured record of what
each agent did, enabling cross-session queries.

**Recommendation:** After a worker completes (detected by `status.py`), capture
its final output and write a structured summary to
`state/<team>/results/<worker>.md`. The `team standup` command could then
aggregate these instead of asking the lead to inspect each worker manually.

**Files to modify:**
- `src/agentic_team/status.py` — add result capture on completion detection
- `src/agentic_team/cli.py` — update `standup` to read result files

### 4. Add basic merge coordination

**Problem:** When multiple workers modify the same files, merge conflicts are
discovered only after both finish. This wastes time and requires manual
resolution.

**GasTown approach:** The Refinery provides a full merge queue with CI gating
and bisection.

**Recommendation:** A lightweight version: when `use_worktrees` is enabled, add
a `team merge` command that merges completed worker branches in sequence,
stopping on the first conflict and reporting which workers conflict. This
doesn't need CI gating or bisection — just sequential merge with clear error
reporting.

**Files to modify:**
- `src/agentic_team/cli.py` — add `merge` command
- `src/agentic_team/tmux.py` — (possibly) add git operations for worktree
  branches

### 5. Add inter-agent messaging beyond send-keys

**Problem:** `send-keys` is fire-and-forget with no delivery confirmation and
no structure. The lead can send messages to workers, but workers cannot
communicate with each other or send structured results back.

**GasTown approach:** `mail.Router` with typed messages.

**Recommendation:** A minimal version: add a `state/<team>/mailbox/<worker>/`
directory. Workers can write files there (via their system prompt instructions).
The lead's system prompt tells it to check mailboxes. No daemon needed — just
file-based message passing checked during status polls.

**Files to modify:**
- `src/agentic_team/agents.py` — update system prompts to mention mailbox paths
- `src/agentic_team/status.py` — report pending messages in status output
- `src/agentic_team/cli.py` — add `team messages` command to list/read

### 6. Add capacity scheduling for large teams

**Problem:** `max_workers` is a hard limit, but there's no queuing. If you have
10 tasks and `max_workers=4`, the CLI spawns 4 and drops/blocks on the rest.

**GasTown approach:** Config-driven capacity governor that queues excess work.

**Recommendation:** In `team run <taskfile>`, when tasks exceed `max_workers`,
queue the excess. After each `team status` poll that detects a completed
worker, spawn the next queued task. This already partially exists in the
taskfile processing logic (`cli.py:1406-1450`) but could be made more explicit
with a proper queue data structure.

**Files to modify:**
- `src/agentic_team/cli.py` — refactor taskfile batch processing into a queue
- `src/agentic_team/config.py` — persist queue state for crash recovery

---

## What NOT to adopt

### 1. Dolt as the state backend

GasTown uses Dolt (a Git-for-data SQL database) for all state. This adds a
significant dependency, setup complexity, and operational burden. agentic-team's
TOML files with atomic writes are sufficient for its scale (1-6 workers) and
dramatically simpler to debug, backup, and understand. The TOML approach is a
feature, not a limitation.

### 2. Seven specialized agent roles

GasTown's Mayor/Polecat/Refinery/Witness/Deacon/Dogs/Crew hierarchy is
designed for 20-30 agents. For agentic-team's target of 1-6 workers, this
would add complexity without benefit. The lead + workers model is the right
abstraction at this scale. If agentic-team grows to support larger teams,
individual features (like a merge queue or health monitor) can be added
incrementally without adopting the full role taxonomy.

### 3. Continuous daemon processes

GasTown's Witness and Deacon run as persistent daemons. agentic-team's
CLI-driven polling model (`team status`, `team wait`) is simpler, uses fewer
resources, and avoids the operational complexity of daemon lifecycle management.
The polling model can be enhanced (stuck detection, timeouts) without becoming
a daemon.

### 4. Workflow template DSL (Formulas → Protomolecules → Molecules)

GasTown's three-stage workflow compilation (TOML Formulas → Protomolecules →
Molecules) is enterprise-grade workflow management. agentic-team's markdown
taskfiles are more accessible and sufficient for the target use case. The
abstraction cost of a workflow DSL isn't justified until teams regularly run
repeatable multi-stage pipelines.

### 5. Federated multi-instance coordination

The Wasteland Federation feature (cross-GasTown coordination via DoltHub) is
designed for enterprise deployments with multiple teams across multiple
machines. This is well beyond agentic-team's scope and would add complexity
with no near-term benefit.

### 6. Event log replay (Seance)

While session history discovery is clever, it requires structured event logging
infrastructure (`.events.jsonl`) and agents that know how to query it.
agentic-team's log files + session resume (for oneshot workers) provide
sufficient continuity at current scale. The cost of instrumenting all agent
interactions into structured events is high relative to the benefit for small
teams.

---

## Summary

GasTown and agentic-team share the same foundational insight (tmux as universal
agent runtime) but target different scales. GasTown solves problems that emerge
at 20+ agents: crash recovery, merge ordering, stuck detection, capacity
scheduling. agentic-team should selectively adopt the **patterns** behind these
solutions (persistent recovery files, timeout-based stuck detection, structured
output collection, sequential merge coordination) without adopting the
**infrastructure** (Dolt, daemons, workflow DSLs, role taxonomies).

The highest-impact, lowest-effort wins are:

1. **Crash recovery files** — prevents lost work, builds on existing state model
2. **Stuck-worker detection** — small addition to status polling, high user value
3. **Structured result collection** — improves standup/reporting without new infra
