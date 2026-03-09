---
name: sprint
description: Sprint planning, progress tracking, and agent management. Use this skill whenever someone asks about project status, build progress, sprint planning, what's done or remaining, or when a story or task has been completed, started, or blocked. Also trigger when an agent finishes implementing something from the build plan — any mention of completing stories, finishing setup steps, wrapping up epic work, planning sprints, assigning agents, or checking progress should use this skill.
---

Manage sprints, track progress, and coordinate agents using the CLI at `~/.claude/skills/sprint/sprint.py`.

## Setup

```bash
SPRINT="python3 ~/.claude/skills/sprint/sprint.py"
```

## First-Time Init

```bash
$SPRINT init                    # Create DB + config
$SPRINT migrate                 # Import from progress.json (if exists)
$SPRINT sync                    # Sync with spec files
```

## Progress Tracking

```bash
$SPRINT get                     # Overview of all epics
$SPRINT get E01                 # Story detail for one epic
$SPRINT update E01 S01 done S02 in-progress   # Bulk status update
$SPRINT revert E01 S01          # Reset to not-started
$SPRINT sync                    # Sync DB from spec files
$SPRINT view                    # Open HTML viewer
```

Status values: `not-started`, `in-progress`, `done`, `blocked`

## Sprint Management

```bash
$SPRINT sprint create "Sprint 1" --goal "Tech stack setup" --start 2026-03-08 --end 2026-03-15
$SPRINT sprint list
$SPRINT sprint show 1
$SPRINT sprint plan --capacity 20       # Suggest stories via dependency resolution
$SPRINT sprint add 1 E01 S01 S02 S03    # Add from one epic
$SPRINT sprint add 1 E01 S01 S02 E02 S03 S04  # Add from multiple epics
$SPRINT sprint remove 1 E01 S01         # Remove story from sprint
$SPRINT sprint activate 1
$SPRINT sprint complete 1
$SPRINT sprint velocity                 # Compare points/stories across sprints
```

## Agent Management

```bash
$SPRINT agent register claude-main
$SPRINT agent list
$SPRINT agent assign claude-main 1
```

## Briefing

```bash
$SPRINT brief 1                 # Full sprint briefing by sprint ID
$SPRINT brief claude-main       # Briefing for agent's active sprint
```

## Progress Logging

```bash
$SPRINT log E01 S01 start
$SPRINT log E01 S01 completion "All tasks verified"
$SPRINT log E01 S01 blocker "MySQL not available"
$SPRINT log history E01 S01
$SPRINT log history --sprint 1
```

Event types: `start`, `progress`, `blocker`, `error`, `resolution`, `completion`, `failure`, `note`

## Git Worktrees

```bash
$SPRINT worktree create 1       # Create isolated worktree for sprint
$SPRINT worktree list            # Show active worktrees
$SPRINT worktree destroy 1       # Clean up after merge
```

## Auto-invocation

When context implies a progress update, status check, or sprint operation, run the appropriate command without the slash command. To map natural language to story IDs, read the relevant epic's spec.md.

**Status updates** — when a user says they finished, started, or got stuck on something:
- "just finished setting up Horizon" → identify the story (e.g. E01/S05), run `update E01 S05 done`
- "starting work on the auth system" → find the story, run `update E03 S01 in-progress`
- "MySQL isn't available, can't continue" → run `update E01 S03 blocked`, then `log E01 S03 blocker "MySQL not available"`

**Progress checks** — when a user asks about status or what's remaining:
- "how's the build going?" → run `get`
- "what's left on the tech stack?" → run `get E01`
- "how are we doing on velocity?" → run `sprint velocity`
- "show me sprint 2" → run `sprint show 2`

**Planning** — when a user wants to plan or organize work:
- "plan the next sprint" → run `sprint plan --capacity N`
- "start a new sprint for auth work" → run `sprint create "Auth Sprint" --goal "..."`
- "add the billing stories to sprint 2" → find billing epic, run `sprint add 2 E05 S01 S02 ...`

## Data

- **Database:** `{project_root}/.claude/sprint.db` (per-project)
- **Config:** `{project_root}/.claude/sprint.conf` (per-project)
- **Source of truth:** Spec files in `build-plan/` (synced to DB via `sync`)
