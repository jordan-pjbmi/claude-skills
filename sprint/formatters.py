"""Table output formatting and agent briefing generator."""

from db import get_connection, load_config


STATUS_DISPLAY = {
    "not-started": "Not Started",
    "in-progress": "In Progress",
    "done": "Done",
    "blocked": "Blocked",
    "complete": "Complete",
}


def compute_epic_status(stories):
    """Compute epic status from its stories (matches old progress.py behavior)."""
    if not stories:
        return "Not Started"
    statuses = [s["status"] for s in stories]
    if all(s == "done" for s in statuses):
        return "Complete"
    if any(s == "blocked" for s in statuses) and not any(s == "in-progress" for s in statuses):
        return "Blocked"
    if any(s in ("done", "in-progress") for s in statuses):
        return "In Progress"
    return "Not Started"


def pct(done, total):
    return round(done / total * 100) if total else 0


def format_table(headers, rows, indent=2):
    """Format a list of tuples into aligned columns."""
    if not rows:
        return ""
    widths = [max(len(headers[i]), *(len(str(r[i])) for r in rows)) for i in range(len(headers))]
    prefix = " " * indent
    fmt = prefix + "  ".join(f"{{:<{w}}}" for w in widths)
    lines = [fmt.format(*headers)]
    lines.append(fmt.format(*(("\u2014" * w) for w in widths)))
    for r in rows:
        lines.append(fmt.format(*r))
    return "\n".join(lines)


def format_get_overview(project_root):
    """Format the overall progress overview."""
    conn = get_connection(project_root)
    config = load_config(project_root)
    project_name = config.get("name", project_root.name)
    epics = conn.execute("SELECT * FROM epics ORDER BY id").fetchall()
    lines = []

    total_stories = 0
    total_done = 0
    rows = []
    for epic in epics:
        stories = conn.execute("SELECT status FROM stories WHERE epic_id=? ORDER BY sort_order", (epic["id"],)).fetchall()
        n = len(stories)
        d = sum(1 for s in stories if s["status"] == "done")
        total_stories += n
        total_done += d
        status = compute_epic_status(stories)
        progress = f"{d}/{n} ({pct(d, n)}%)" if n else "\u2014"
        rows.append((epic["id"], epic["title"], progress, status))

    lines.append(f"{project_name} \u2014 Progress ({total_done}/{total_stories}, {pct(total_done, total_stories)}%)")
    lines.append("")
    lines.append(format_table(("Epic", "Title", "Progress", "Status"), rows))
    conn.close()
    return "\n".join(lines)


def format_get_epic(project_root, epic_id):
    """Format detail for a single epic (matches old progress.py get E01 output)."""
    conn = get_connection(project_root)
    epic = conn.execute("SELECT * FROM epics WHERE id=?", (epic_id.upper(),)).fetchone()
    if not epic:
        return None

    stories = conn.execute(
        "SELECT * FROM stories WHERE epic_id=? ORDER BY sort_order", (epic["id"],)
    ).fetchall()

    n = len(stories)
    d = sum(1 for s in stories if s["status"] == "done")
    status = compute_epic_status(stories)
    header = f"{epic['id']}: {epic['title']} \u2014 {status}"
    if n:
        header += f" ({d}/{n}, {pct(d, n)}%)"

    lines = [header, ""]
    if not stories:
        lines.append("  No stories defined yet.")
    else:
        rows = []
        for s in stories:
            effort_str = str(s["effort"]) if s["effort"] else "\u2014"
            rows.append((s["id"], s["layer"] or "", s["title"], effort_str, STATUS_DISPLAY.get(s["status"], s["status"])))
        lines.append(format_table(("Story", "Layer", "Title", "Effort", "Status"), rows))

    conn.close()
    return "\n".join(lines)


def format_sprint_list(project_root):
    """List all sprints."""
    conn = get_connection(project_root)
    sprints = conn.execute("SELECT * FROM sprints ORDER BY id").fetchall()
    if not sprints:
        return "No sprints created yet."

    rows = []
    for s in sprints:
        story_count = conn.execute("SELECT COUNT(*) as c FROM sprint_stories WHERE sprint_id=?", (s["id"],)).fetchone()["c"]
        agent = s["agent_id"] or "\u2014"
        rows.append((str(s["id"]), s["name"], s["status"], str(story_count), agent, s["start_date"] or "\u2014", s["end_date"] or "\u2014"))

    conn.close()
    return format_table(("ID", "Name", "Status", "Stories", "Agent", "Start", "End"), rows)


def format_sprint_show(project_root, sprint_id):
    """Show detail for a single sprint."""
    conn = get_connection(project_root)
    sprint = conn.execute("SELECT * FROM sprints WHERE id=?", (sprint_id,)).fetchone()
    if not sprint:
        return None

    lines = [
        f"Sprint {sprint['id']}: {sprint['name']}",
        f"  Status: {sprint['status']}",
        f"  Goal: {sprint['goal'] or '\u2014'}",
        f"  Dates: {sprint['start_date'] or '?'} \u2192 {sprint['end_date'] or '?'}",
        f"  Agent: {sprint['agent_id'] or '\u2014'}",
        f"  Branch: {sprint['branch_name'] or '\u2014'}",
        f"  Worktree: {sprint['worktree_path'] or '\u2014'}",
        "",
    ]

    stories = conn.execute(
        """SELECT ss.sort_order, s.id, s.epic_id, s.title, s.layer, s.effort, s.status
           FROM sprint_stories ss
           JOIN stories s ON s.id = ss.story_id AND s.epic_id = ss.epic_id
           WHERE ss.sprint_id = ?
           ORDER BY ss.sort_order""",
        (sprint_id,),
    ).fetchall()

    if not stories:
        lines.append("  No stories assigned.")
    else:
        total_effort = sum(s["effort"] or 0 for s in stories)
        lines.append(f"  Stories ({len(stories)}, {total_effort} pts):")
        rows = []
        for s in stories:
            effort_str = str(s["effort"]) if s["effort"] else "\u2014"
            rows.append((f"{s['epic_id']}/{s['id']}", s["title"], effort_str, STATUS_DISPLAY.get(s["status"], s["status"])))
        lines.append(format_table(("Story", "Title", "Effort", "Status"), rows, indent=4))

    conn.close()
    return "\n".join(lines)


def format_briefing(project_root, sprint_id, config):
    """Generate a full agent briefing for a sprint."""
    conn = get_connection(project_root)
    sprint = conn.execute("SELECT * FROM sprints WHERE id=?", (sprint_id,)).fetchone()
    if not sprint:
        return None

    stories = conn.execute(
        """SELECT ss.sort_order, s.id, s.epic_id, s.title, s.layer, s.effort, s.status, s.spec_path
           FROM sprint_stories ss
           JOIN stories s ON s.id = ss.story_id AND s.epic_id = ss.epic_id
           WHERE ss.sprint_id = ?
           ORDER BY ss.sort_order""",
        (sprint_id,),
    ).fetchall()

    build_plan = config.get("build_plan", "build-plan")
    work_dir = sprint["worktree_path"] or config.get("root", "")
    branch = sprint["branch_name"] or f"sprint/{sprint['id']}-{sprint['name'].lower().replace(' ', '-')}"

    lines = [
        f"# Sprint Briefing: {sprint['name']}",
        "",
        f"**Goal:** {sprint['goal'] or 'No goal set'}",
        f"**Dates:** {sprint['start_date'] or '?'} \u2192 {sprint['end_date'] or '?'}",
        f"**Agent:** {sprint['agent_id'] or 'unassigned'}",
        "",
        "## Working Directory",
        "",
        f"```",
        f"cd {work_dir}",
        f"```",
        "",
        "## Git Instructions",
        "",
        f"- **Branch:** `{branch}`",
        f"- **Commit format:** `E{{XX}}/S{{XX}}: {{title}}`",
        "- Commit after each completed story",
        "- Include sprint and agent in commit body:",
        "  ```",
        f"  Sprint: {sprint['name']}",
        f"  Agent: {sprint['agent_id'] or 'unassigned'}",
        "  ```",
        "",
        "## Stories",
        "",
    ]

    total_effort = sum(s["effort"] or 0 for s in stories)
    lines.append(f"Total: {len(stories)} stories, {total_effort} points")
    lines.append("")

    for s in stories:
        status_mark = "\u2705" if s["status"] == "done" else "\u2b1c" if s["status"] == "not-started" else "\U0001f534" if s["status"] == "blocked" else "\U0001f7e1"
        effort_str = f" ({s['effort']}pt)" if s["effort"] else ""
        spec = f"{build_plan}/{s['spec_path']}" if s["spec_path"] else "no spec"
        lines.append(f"{status_mark} **{s['epic_id']}/{s['id']}:** {s['title']}{effort_str}")
        lines.append(f"   Spec: `{spec}`")
        lines.append(f"   Status: {STATUS_DISPLAY.get(s['status'], s['status'])}")

        # Check story dependencies
        deps = conn.execute(
            "SELECT depends_on_epic, depends_on_story FROM story_dependencies WHERE story_id=? AND story_epic_id=?",
            (s["id"], s["epic_id"]),
        ).fetchall()
        if deps:
            dep_strs = [f"{d['depends_on_epic']}/{d['depends_on_story']}" for d in deps]
            lines.append(f"   Depends on: {', '.join(dep_strs)}")
        lines.append("")

    lines.extend([
        "## Workflow",
        "",
        "For each story:",
        "1. Read the story spec",
        "2. `sprint.py log EPIC STORY start`",
        "3. Execute all tasks",
        "4. Verify acceptance criteria",
        "5. `sprint.py log EPIC STORY completion`",
        "6. `sprint.py update EPIC STORY done`",
        "7. Commit: `git commit -m 'EPIC/STORY: Title'`",
        "",
        "If blocked:",
        "- `sprint.py log EPIC STORY blocker \"reason\"`",
        "- `sprint.py update EPIC STORY blocked`",
    ])

    conn.close()
    return "\n".join(lines)


def format_log_history(project_root, epic_id=None, story_id=None, sprint_id=None):
    """Format progress log history."""
    conn = get_connection(project_root)

    if sprint_id:
        rows = conn.execute(
            "SELECT * FROM progress_log WHERE sprint_id=? ORDER BY created_at", (sprint_id,)
        ).fetchall()
    elif epic_id and story_id:
        rows = conn.execute(
            "SELECT * FROM progress_log WHERE epic_id=? AND story_id=? ORDER BY created_at",
            (epic_id.upper(), story_id.upper()),
        ).fetchall()
    elif epic_id:
        rows = conn.execute(
            "SELECT * FROM progress_log WHERE epic_id=? ORDER BY created_at", (epic_id.upper(),)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM progress_log ORDER BY created_at DESC LIMIT 50").fetchall()

    if not rows:
        return "No log entries found."

    lines = []
    for r in rows:
        msg = f"  {r['message']}" if r["message"] else ""
        agent = f" [{r['agent_id']}]" if r["agent_id"] else ""
        lines.append(f"  {r['created_at']}  {r['epic_id']}/{r['story_id']}  {r['event_type']}{agent}{msg}")

    conn.close()
    return "\n".join(lines)
