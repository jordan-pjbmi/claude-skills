---
name: spec-audit
description: >
  Audit spec.md files for consistency, completeness, and correctness. Use this skill whenever
  someone asks to audit, review, or validate specs, story specs, epic specs, or build plan
  documents. Also trigger when someone mentions checking dependencies between stories, finding
  gaps in specs, or reviewing spec quality. Works on a single spec file or an entire directory
  tree of specs.
---

# Spec Audit

Audit specification files for issues across multiple dimensions: structural consistency, dependency correctness, task completeness, cross-reference accuracy, and open decisions tracking.

## Input

The user provides either:
- **A file path** to a single `spec.md` — audit that one spec
- **A folder path** — recursively find all `spec.md` files and audit them together

If the user says something like "audit E01" or "audit all stories in epic X", resolve that to the appropriate folder path.

Optional flags:
- `--full` — force a full audit even if a prior audit exists for the same scope

## Partial vs Full Audit

By default, audits are **partial**: only files changed since the last audit are re-examined.

**Procedure:**

1. Find the most recent **completed** audit for the same `scope` in `index.json`
2. If found and it has a `git_commit` field, run: `git diff --name-only {prior_commit} HEAD -- {scope}/`
3. **Changed files only**: audit only the specs that appear in the diff output
4. **Carry forward unchanged findings**: for every finding from the prior audit whose `location.file` is NOT in the changed set, include it in the new audit with `"carried_forward": true` and `"carried_from_audit": "{prior-audit-id}"`. Carried findings preserve their fingerprints and any prior_response data.
5. **No prior audit** or no `git_commit` on the prior → fall back to a full audit
6. **No changed files** → report "No spec files changed since audit {id}" and skip. Suggest `--full` to re-audit everything.
7. `--full` flag → audit all specs regardless of changes

The `mode` field in audit.json and index.json records whether the audit was `"full"` or `"partial"`.

## Audit Dimensions

Run every spec through these checks. Not every check applies to every spec — use judgment.

### 1. Structural Consistency
- Does the spec follow the expected format? (Goal, Tasks, Acceptance Criteria, Dependencies sections)
- Are task items using checkbox syntax (`- [ ]`)?
- Is there a Dependencies section (even if "None")?

### 2. Cross-Reference Accuracy
- If an epic spec references story specs, do those story files actually exist?
- Do story titles in the epic table match the actual story spec titles?
- Are task lists in the epic summary consistent with the detailed story specs? Flag any tasks that appear in one but not the other, or that use different wording for the same thing.

### 3. Dependency Correctness
- Are declared dependencies between stories logically correct?
- Are there missing dependencies? (e.g., a story that runs migrations but doesn't depend on the database config story)
- Are there circular dependencies?
- Do dependency references use correct story IDs?

### 4. Task Completeness
- Are tasks specific and actionable, or vague?
- Do acceptance criteria actually verify the tasks? (Every task should have a corresponding way to verify it succeeded)
- Are there acceptance criteria that no task addresses?

### 5. Open Decisions & Risks
- Are there unresolved decisions flagged in the specs?
- Do open decisions have enough context for someone to make the decision?
- Are there implicit decisions that should be made explicit? (e.g., choosing between two approaches without noting it)

### 6. Content Issues
- Redundant tasks across stories (same work specified in two places)
- Contradictions between specs
- Missing context (a spec references something not defined elsewhere)
- Outdated references (packages, versions, commands that may have changed)

## Output Format

Each audit run generates a unique ID based on the current timestamp: `YYYYMMDD-HHMMSS` (e.g., `20260307-143022`).

Store all findings in `./audit-history/{audit-id}/audit.json` (relative to the current working directory). Also maintain `./audit-history/index.json` as a manifest of all audits. Structure:

```
audit-history/
├── index.json              # [{id, date, scope, total_findings, by_severity, status}]
├── 20260307-143022/
│   ├── audit.json
│   └── responses.json
├── 20260305-091500/
│   ├── audit.json
│   └── responses.json
```

### audit.json

```json
{
  "id": "20260307-143022",
  "audit_date": "2026-03-07",
  "scope": "epics/E01-tech-stack",
  "git_commit": "abc1234",
  "mode": "partial",
  "specs_audited": ["spec.md", "stories/S01-prerequisites/spec.md", "..."],
  "summary": {
    "total_findings": 10,
    "by_severity": {"error": 1, "warning": 4, "info": 5},
    "by_dimension": {"dependencies": 3, "consistency": 2, "...": "..."}
  },
  "findings": [
    {
      "id": "F001",
      "fingerprint": "dependencies:s06-pulse:missing-redis-dependency",
      "severity": "error",
      "dimension": "dependencies",
      "title": "Short description of the finding",
      "detail": "Full explanation with specific references to files and line content",
      "location": {
        "file": "stories/S06-pulse/spec.md",
        "section": "Dependencies",
        "stories_affected": ["S06"]
      },
      "suggestion": "What to do about it — concrete fix recommendation",
      "prior_response": {
        "action": "dismiss",
        "audit_id": "20260305-091500",
        "notes": "Not applicable — Redis is installed separately"
      },
      "carried_forward": false,
      "carried_from_audit": null
    }
  ]
}
```

#### Fingerprint Format

Each finding must include a `fingerprint` field: `{dimension}:{story-slug}:{issue-slug}`

- `dimension`: the audit dimension (e.g., `dependencies`, `cross-reference`, `content`)
- `story-slug`: the primary story or file slug in kebab-case (e.g., `s06-pulse`, `spec`)
- `issue-slug`: a stable 2–5 word kebab-case description of the issue (e.g., `missing-redis-dependency`)

**Stability rules:**
- The same underlying issue MUST produce the same fingerprint across audit rounds
- If a finding spans multiple files, use the primary file from `location.file` for the slug
- Choose issue slugs that describe the root problem, not the symptom

#### Prior Response Tracking

Before generating findings, read the prior audit's `responses.json` for the same scope:

- **Fingerprint matches a prior dismissed finding** → include with `prior_response: {action, audit_id, notes}`. The finding will auto-populate as "dismiss" in the review UI (user can override).
- **Fingerprint matches a prior accepted finding and issue is now fixed** → omit it entirely
- **Fingerprint matches a prior accepted finding but issue persists** → include with `prior_response`
- **No match** → new finding, no `prior_response` field

#### Carried-Forward Fields

For partial audits, findings from unchanged files are carried forward:
- `"carried_forward": true` — this finding was not re-evaluated, just copied
- `"carried_from_audit": "20260305-091500"` — the audit it was carried from

For new/re-evaluated findings, omit these fields or set them to `false`/`null`.

### index.json

After writing `audit.json`, update (or create) `./audit-history/index.json`. Append an entry for the new audit:

```json
[
  {
    "id": "20260307-143022",
    "date": "2026-03-07",
    "scope": "epics/E01-tech-stack",
    "total_findings": 10,
    "by_severity": {"error": 1, "warning": 4, "info": 5},
    "mode": "partial",
    "status": "pending"
  }
]
```

The `status` field is `"pending"` initially and becomes `"complete"` when the user submits responses via the review UI.
The `mode` field is `"full"` or `"partial"` (see "Partial vs Full Audit" above).

### Severity Levels
- **error**: Will break things or cause implementation failures (e.g., duplicate queue workers, missing critical dependencies)
- **warning**: Should be fixed but won't immediately break things (e.g., missing dependency declarations, inconsistent wording)
- **info**: Nice to fix, stylistic, or architectural observations (e.g., open decisions not tracked, minor format inconsistencies)

### Dimension Values
Use exactly these dimension names: `structure`, `cross-reference`, `dependencies`, `completeness`, `decisions`, `content`

## Review Flow

After writing `audit.json` and updating `index.json`, generate an interactive HTML review page so the user can go through each finding and respond.

### Generate the Review Page

**Launch the review server exactly once per audit session.** The script detects if a server is already running on the port and will just reopen the browser if so — no need to launch it again. Only use `--relaunch` if you need to restart with updated audit data (e.g., after writing a new audit.json).

Run the bundled script:

```bash
python3 ~/.claude/skills/spec-audit/scripts/serve_review.py --history ./audit-history/
```

If you need to restart the server with fresh data after generating a new audit:

```bash
python3 ~/.claude/skills/spec-audit/scripts/serve_review.py --history ./audit-history/ --relaunch
```

To stop the server when the user is done reviewing:

```bash
python3 ~/.claude/skills/spec-audit/scripts/serve_review.py --kill
```

This starts a local server and opens a browser page where the user can:
- See a **History** tab listing all past audits with date, scope, finding counts, and review status
- Click an audit to load its findings into the **Findings** and **Summary** views
- Click through findings one at a time
- For each finding, choose: **Accept** (will fix), **Dismiss** (not an issue), or **Defer** (acknowledged, fix later)
- Add notes to any finding
- Submit all responses

You can also serve a single audit directly:

```bash
python3 ~/.claude/skills/spec-audit/scripts/serve_review.py \
  ./audit-history/20260307-143022/audit.json
```

Responses are saved to `./audit-history/{audit-id}/responses.json`.

### After Review

When the user says they're done reviewing, read `responses.json` and summarize:
- How many findings were accepted, dismissed, deferred
- List the accepted findings — these are the actionable items
- Offer to create a fix plan or apply fixes directly if the specs are in this repo

## Trend Analysis

A standalone script provides cross-audit trend analysis:

```bash
python3 ~/.claude/skills/spec-audit/scripts/trend.py <audit-history-dir> [--scope SCOPE]
```

This outputs:
1. **Findings Over Time** — table and ASCII bar chart: audit ID, date, mode, total/error/warn/info, response breakdown
2. **Recurring Findings** — grouped by fingerprint: first/last seen, appearances, status (resolved/open/dismissed). Degrades gracefully for legacy audits without fingerprints.
3. **Hotspot Files** — which spec files generate the most findings
4. **Dimension Breakdown** — aggregate finding counts by dimension across all audits

Use `--scope` to filter to a specific scope (e.g., `--scope epics/E01-tech-stack`).

## Tips for a Thorough Audit

- Read the epic-level spec first to understand the big picture, then read each story spec
- When checking dependencies, think about what each story actually DOES (runs migrations? needs Redis? modifies .env?) — not just what it says it depends on
- Look for the "hidden dependency" pattern: Story A modifies a file, Story B also modifies the same file — they need ordering even if not explicitly related
- For package installation stories, check whether the install command itself requires other packages/services to be running
- Compare passive language ("verify X is installed") vs active ("install X") — which is it?
