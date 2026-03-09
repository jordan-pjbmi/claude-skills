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

## Execution Strategy

For folder-scoped audits with multiple specs, parallelize the work using subagents:

1. **Scan phase** (main agent) — Read all specs to identify which specialist domains are relevant. Determine the specialist activation list.
2. **Dispatch phase** — Launch subagents in parallel:
   - One subagent runs the **6 core dimensions** across all specs
   - One subagent per **activated specialist** (e.g., database specialist, auth specialist) — each reads the same specs but through its domain lens
3. **Merge phase** (main agent) — Collect findings from all subagents, deduplicate by fingerprint (core findings win over specialist duplicates), assign sequential IDs (F001, F002…), and write the unified `audit.json`.

For single-file audits or when subagents aren't available, run everything sequentially in one pass — core dimensions first, then specialists.

Each subagent should receive: the list of spec file paths, the scope, and any prior `responses.json` for fingerprint matching. Subagents return their findings as JSON arrays; the main agent handles ID assignment, deduplication, summary aggregation, and writing the final output.

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

## Specialist Auditors

Domain-specific lenses that catch issues generic checks miss — they require understanding how a technology actually works, what its common pitfalls are, and how misconfiguration at the spec level cascades into implementation bugs. Each activated specialist runs as its own subagent in parallel (see Execution Strategy above).

**When to activate:** Determined during the scan phase. Look for domain signals in the specs (migration tasks, queue config, permission references, billing flows, etc.). Only activate specialists whose domain appears. Most audits activate 1–3 specialists.

**Output:** Specialist findings use dimension `specialist:{domain}` (e.g., `specialist:database`). They follow the same severity, fingerprint, and output rules as core findings. Add specialist dimensions to the `by_dimension` summary counts.

### Database / Schema / Migration

**Activates when:** specs mention migrations, database tables, columns, indexes, foreign keys, schema changes, seeders, or model relationships.

Checks:

- **Migration ordering** — Stories creating foreign keys must depend on stories that create the referenced tables. A migration adding a `user_id` FK must run after the users table migration. Look for implicit ordering not captured in Dependencies sections.
- **Rollback safety** — Are destructive migrations (dropping columns, changing types) acknowledged? If a migration transforms data, is the reverse path addressed or explicitly marked irreversible?
- **Column types** — Appropriate types for the data described: `decimal` for money (not `float`), `json` for flexible structures, `timestamp` for time data. Laravel 12's `HasUuids` trait defaults to UUIDv7 (ordered) — specs assuming v4 UUIDs should be flagged.
- **Index coverage** — If acceptance criteria mention filtering or querying by specific fields, is there a task to add the corresponding index? Flag missing composite indexes for multi-column lookups (especially `[tenant_id, ...]` patterns).
- **Multi-tenant isolation** — For tenant-scoped tables: is the tenant identifier column specified? Are unique constraints tenant-aware (e.g., unique email per org, not globally)? Are global scopes mentioned to prevent cross-tenant queries?
- **Soft delete awareness** — If specs say "deactivate" or "archive" rather than "delete", is `SoftDeletes` specified? Unique indexes on soft-deletable models need to account for deleted records (partial indexes or include `deleted_at`).
- **Seeder consistency** — Do seeders/fixtures reference tables and columns that match the schema defined in migration stories?
- **Test coverage** — Do specs include tasks for migration rollback tests, seeder verification, and schema assertion tests? Flag stories that create complex schemas (polymorphic relations, composite keys, JSON columns) without corresponding test tasks.

### Auth / Permissions

**Activates when:** specs mention authentication, authorization, roles, permissions, guards, policies, middleware, multi-tenant access control, or team-based permissions.

Checks:

- **Permission completeness** — If a feature restricts access ("only admins can…"), is there a corresponding permission defined? Are permission names consistent across all specs (no `manage-users` in one place and `users.manage` in another)?
- **Spatie teams mode pitfalls** — If using Spatie laravel-permission with `teams: true`: is there a spec for where `setPermissionsTeamId()` gets called (middleware, service provider)? Is permission cache separation per tenant addressed? After switching team context, cached roles/permissions on user model relations must be unset — flag if not mentioned.
- **Role hierarchy** — Are roles defined with clear capabilities? If "manager" inherits from "editor", is that explicit? Are there global roles (super-admin) that bypass tenant scoping, and is that interaction defined?
- **Middleware configuration** — Laravel 11+ configures middleware in `bootstrap/app.php` (not `Kernel.php`). Specs referencing `Kernel.php` or `Auth::routes()` are outdated. Are protected routes explicitly listed or grouped?
- **Guard separation** — If admin and user auth are separate (e.g., Filament admin panel vs main app), are separate guards defined? Do specs clarify which guard each auth flow uses?
- **2FA and session lifecycle** — If specs mention 2FA, are recovery codes, single-use enforcement, and re-authentication flows specified? Is session expiry / token refresh addressed?
- **Test coverage** — Do specs include tasks for testing permission boundaries (user A can't access user B's resources), role assignment/revocation, guard isolation, and tenant-scoping enforcement? Flag multi-tenant auth specs without cross-tenant access tests.

### Queue / Background Jobs

**Activates when:** specs mention queues, jobs, workers, Horizon, Redis, scheduled tasks, event listeners, or async processing.

Checks:

- **Failure handling** — Do job specs define retry count, backoff strategy, and final-failure behavior (log, notify, dead letter)? Unspecified retry behavior defaults to 1 attempt with no recovery.
- **Queue separation** — Are different job types assigned to named queues? Heavy processing jobs on the same queue as real-time notifications will cause latency. Flag specs that put everything on `default` without justification.
- **Horizon topology** — If using Horizon: is the supervisor/queue mapping specified (which supervisors handle which queues)? Are auto-scaling parameters (`minProcesses`, `maxProcesses`, `balanceMaxShift`) mentioned for production? Is the balancing strategy (`auto` vs `simple`) chosen deliberately?
- **Idempotency** — Jobs that modify external state (send email, charge card, call API) must be safe to run twice. Flag job specs that don't address duplicate execution. Webhook handlers are especially prone — Stripe retries up to 19 times.
- **Infrastructure dependencies** — Do queue-related stories depend on Redis/Horizon setup stories? Flag orphaned job specs with no infrastructure dependency.
- **Timeout alignment** — If `retry_after` is shorter than actual job runtime, jobs get double-processed. Flag long-running job specs (report generation, data imports) that don't specify timeout and memory limits.
- **Unique jobs** — If specs describe jobs that shouldn't run concurrently (e.g., "sync tenant data"), is `ShouldBeUnique` or an equivalent locking strategy specified?
- **Test coverage** — Do specs include tasks for testing job failure/retry behavior, dead letter scenarios, and queue isolation? Flag jobs that handle payments or external API calls without specifying failure-path tests.

### Billing / Subscription

**Activates when:** specs mention payments, subscriptions, Stripe, Cashier, plans, pricing, invoices, webhooks, trials, or metered billing.

Checks:

- **Webhook idempotency** — Stripe retries failed webhooks. Are webhook handlers explicitly idempotent? Flag handlers that create records without checking for duplicates. Is `STRIPE_WEBHOOK_SECRET` verification specified?
- **Subscription lifecycle** — Are all states defined (trialing, active, past_due, canceled, incomplete, paused)? What changes in the UI and access control for each state? Flag specs that only define the happy path (subscribe → active) without addressing failures or cancellations.
- **Plan transitions** — Is upgrade/downgrade behavior explicit? Proration (immediate charge vs end-of-cycle), feature access during grace periods, and what happens to in-flight usage on plan change.
- **Trial handling** — Are trial periods, trial-to-paid conversion, and expired-trial behavior specified? Note: Cashier checkout sessions + `trial_end` + `billing_cycle_anchor` don't work together (known Cashier limitation) — flag if specs combine these.
- **Metered billing** — If applicable: Cashier 16 changed metered billing to use `Stripe\V2\Billing\MeterEvent` and requires `meter_event_name`/`meter_id` columns on `subscription_items`. Flag specs that don't account for this schema requirement.
- **Multi-tenant billing** — Do Stripe customers map to users or to organizations/tenants? Is this explicit? Can one org have multiple subscriptions, or one per tenant?
- **Stripe API version** — Cashier 16 uses Stripe API `2025-07-30.basil`. Flag specs referencing older Stripe patterns or not addressing API version pinning.
- **Test coverage** — Do specs include tasks for testing webhook signature verification, subscription state transitions, failed payment handling, and plan change proration? Flag billing specs that only test the happy path (successful charge) without failure scenarios.

### Security

**Activates when:** specs describe user-facing features, API endpoints, form inputs, file uploads, authentication flows, external integrations, or any operation handling sensitive data. This specialist has a low activation threshold — most epics with user-facing stories should trigger it.

Checks:

- **Input validation** — Do specs describing user input (forms, API parameters, file uploads) include validation rules or reference a validation layer? Flag specs that accept user input without mentioning validation — especially freeform text fields, file uploads, and URL inputs.
- **Rate limiting** — Are throttle/rate-limit protections specified for abuse-prone endpoints? Login, password reset, registration, API endpoints, and webhook receivers should all have rate limiting. Flag unthrottled auth endpoints as warnings.
- **Data exposure** — Do API responses or view specs define which fields are returned? Flag specs that return model data without explicit field whitelisting (`$hidden`, API resources, `->only()`). Sensitive fields (emails, phone numbers, internal IDs, tokens) exposed without justification are errors.
- **Encryption at rest** — Are sensitive data columns (API keys, OAuth tokens, webhook secrets, PII) stored with encryption? Laravel's `encrypted` cast or equivalent should be specified for secrets. Flag plaintext storage of credentials.
- **Audit logging** — Do destructive or privilege-sensitive operations (delete records, change roles/permissions, impersonation, billing changes) include audit trail tasks? Flag admin actions without logging as warnings.
- **CSRF protection** — Are non-GET endpoints protected? Livewire handles CSRF automatically, but custom routes and API endpoints need explicit mention. Flag specs defining POST/PUT/DELETE routes without CSRF or token-based auth.
- **XSS surface** — Do specs mention rendering user-provided content (comments, names, rich text)? Flag if output encoding or sanitization isn't mentioned. Blade's `{{ }}` escapes by default, but `{!! !!}` does not — flag specs that imply raw HTML rendering.
- **File upload safety** — If specs describe file uploads: is file type validation specified? Size limits? Storage location (public vs private disk)? Flag uploads stored in public directories without access control.
- **Secret management** — Are API keys, third-party credentials, and signing secrets stored in `.env` / config? Flag specs that hardcode secrets or don't specify where credentials are stored.
- **CORS and security headers** — Do specs for API endpoints or embeddable content address CORS configuration? Are CSP headers mentioned for pages rendering external content or scripts?
- **Test coverage** — Do specs include tasks for testing rate limiting effectiveness, input validation rejection, permission boundary enforcement, and XSS/injection prevention? Flag security-sensitive features (auth, payments, admin actions) without explicit security test tasks.

## Output Format

Each audit run generates a unique ID based on the current timestamp: `YYYYMMDD-HHMMSS` (e.g., `20260307-143022`).

Store all findings in `./.spec-audit/{audit-id}/audit.json` (relative to the current working directory). Also maintain `./.spec-audit/index.json` as a manifest of all audits. Structure:

```
.spec-audit/
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

After writing `audit.json`, update (or create) `./.spec-audit/index.json`. Append an entry for the new audit:

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
Core dimensions: `structure`, `cross-reference`, `dependencies`, `completeness`, `decisions`, `content`
Specialist dimensions: `specialist:database`, `specialist:auth`, `specialist:queue`, `specialist:billing`, `specialist:security`

## Review Flow

After writing `audit.json` and updating `index.json`, generate an interactive HTML review page so the user can go through each finding and respond.

### Generate the Review Page

**Launch the review server exactly once per audit session.** The script detects if a server is already running on the port and will just reopen the browser if so — no need to launch it again. Only use `--relaunch` if you need to restart with updated audit data (e.g., after writing a new audit.json).

Run the bundled script:

```bash
python3 ~/.claude/skills/spec-audit/scripts/serve_review.py --history ./.spec-audit/
```

If you need to restart the server with fresh data after generating a new audit:

```bash
python3 ~/.claude/skills/spec-audit/scripts/serve_review.py --history ./.spec-audit/ --relaunch
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
  ./.spec-audit/20260307-143022/audit.json
```

Responses are saved to `./.spec-audit/{audit-id}/responses.json`.

### After Review

When the user says they're done reviewing, read `responses.json` and summarize:
- How many findings were accepted, dismissed, deferred
- List the accepted findings — these are the actionable items
- Offer to create a fix plan or apply fixes directly if the specs are in this repo

## Trend Analysis

A standalone script provides cross-audit trend analysis:

```bash
python3 ~/.claude/skills/spec-audit/scripts/trend.py <.spec-audit-dir> [--scope SCOPE]
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
