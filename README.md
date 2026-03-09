# Claude Skills

Custom skills for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) that extend the CLI with domain-specific capabilities.

## Skills

### spec-audit

Audits `spec.md` files for consistency, completeness, and correctness. Checks structural format, cross-references, dependency graphs, task completeness, open decisions, and content issues. Includes specialist auditors for database/auth/queue/billing domains that run in parallel via subagents.

Features:
- Partial audits (only changed files since last audit) or full sweeps
- Fingerprint-based finding deduplication across runs
- Interactive HTML review UI for triaging findings
- Trend analysis across audit history

### sprint

Sprint planning, progress tracking, and agent management backed by a local SQLite database. Coordinates multi-agent builds against a spec-based build plan.

Features:
- Sprint creation with goals and story assignment
- Story and task status tracking (pending/in-progress/completed/blocked)
- Agent assignment and workload management
- Git integration for linking commits to stories
- HTML viewer for sprint dashboards

## Installation

Clone into your Claude Code skills directory:

```bash
git clone https://github.com/jordan-pjbmi/claude-skills.git ~/.claude/skills
```

Skills are automatically discovered by Claude Code from `SKILL.md` files.

## License

MIT
