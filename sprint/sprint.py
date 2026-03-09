#!/usr/bin/env python3
"""CLI entry point for sprint management."""

import argparse
import sqlite3
import sys
from pathlib import Path

# Add skill directory to path for module imports
SKILL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILL_DIR))

from db import find_project_root, get_connection, init_db, load_config, migrate_from_json, now_iso, recompute_epic_status, save_config


def ensure_db(project_root):
    """Ensure the database exists, initialize if not."""
    from db import db_path
    if not db_path(project_root).exists():
        init_db(project_root)


def cmd_init(args):
    """Initialize sprint database and config."""
    project_root = find_project_root()
    path = init_db(project_root)

    # Create default config if it doesn't exist
    conf_path = project_root / ".claude" / "sprint.conf"
    if not conf_path.exists():
        settings = {
            "name": project_root.name,
            "root": str(project_root),
            "build_plan": "build-plan",
            "main_branch": "main",
            "repos": "",
        }
        save_config(project_root, settings)
        print(f"Config created: {conf_path}")

    print(f"Database initialized: {path}")


def cmd_migrate(args):
    """Migrate from progress.json."""
    project_root = find_project_root()
    ensure_db(project_root)

    # Look for progress.json in common locations
    candidates = [
        project_root / ".claude" / "skills" / "progress" / "progress.json",
        project_root / "progress.json",
    ]
    json_path = None
    for c in candidates:
        if c.exists():
            json_path = c
            break

    if not json_path:
        print("No progress.json found.", file=sys.stderr)
        sys.exit(1)

    migrate_from_json(project_root, json_path)
    print(f"Migrated data from {json_path}")

    # Now sync to pick up any additional data from specs
    cmd_sync(args)


def cmd_sync(args):
    """Sync database from spec files."""
    from sync import sync_to_db

    project_root = find_project_root()
    ensure_db(project_root)
    config = load_config(project_root)
    build_plan_path = Path(config["root"]) / config["build_plan"]

    changes = sync_to_db(project_root, build_plan_path)

    has_changes = any(changes[k] for k in changes)
    if not has_changes:
        print("Already in sync. No changes needed.")
    else:
        if changes["added_epics"]:
            print(f"Added epics: {', '.join(changes['added_epics'])}")
        if changes["removed_epics"]:
            print(f"Removed epics: {', '.join(changes['removed_epics'])}")
        if changes["added_stories"]:
            print(f"Added stories: {', '.join(changes['added_stories'])}")
        if changes["removed_stories"]:
            print(f"Removed stories: {', '.join(changes['removed_stories'])}")
        if changes["updated"]:
            for u in changes["updated"]:
                print(f"Updated: {u}")
        print("\nDatabase updated.")


def cmd_get(args):
    """Show progress overview or epic detail."""
    from formatters import format_get_epic, format_get_overview

    project_root = find_project_root()
    ensure_db(project_root)

    if args.epic:
        result = format_get_epic(project_root, args.epic)
        if result is None:
            print(f"Epic {args.epic} not found.", file=sys.stderr)
            sys.exit(1)
        print(result)
    else:
        print(format_get_overview(project_root))


def cmd_update(args):
    """Update story statuses."""
    project_root = find_project_root()
    ensure_db(project_root)

    conn = get_connection(project_root)
    epic_id = args.epic.upper()

    # Verify epic exists
    epic = conn.execute("SELECT id FROM epics WHERE id=?", (epic_id,)).fetchone()
    if not epic:
        conn.close()
        print(f"Epic {epic_id} not found.", file=sys.stderr)
        sys.exit(1)

    pairs = args.pairs
    if len(pairs) % 2 != 0:
        print("Updates must be story-status pairs (e.g. S01 done S02 in-progress).", file=sys.stderr)
        sys.exit(1)

    valid_statuses = {"not-started", "in-progress", "done", "blocked"}
    ts = now_iso()

    for i in range(0, len(pairs), 2):
        story_id = pairs[i].upper()
        status = pairs[i + 1]
        if status not in valid_statuses:
            conn.close()
            print(f"Invalid status '{status}'. Valid: {', '.join(sorted(valid_statuses))}", file=sys.stderr)
            sys.exit(1)
        story = conn.execute("SELECT id FROM stories WHERE id=? AND epic_id=?", (story_id, epic_id)).fetchone()
        if not story:
            conn.close()
            print(f"Story {story_id} not found in {epic_id}.", file=sys.stderr)
            sys.exit(1)
        conn.execute("UPDATE stories SET status=?, updated_at=? WHERE id=? AND epic_id=?", (status, ts, story_id, epic_id))

    recompute_epic_status(conn, epic_id)

    conn.commit()
    conn.close()

    # Show updated epic
    from formatters import format_get_epic
    print(format_get_epic(project_root, epic_id))


def cmd_revert(args):
    """Reset a story to not-started."""
    project_root = find_project_root()
    ensure_db(project_root)

    conn = get_connection(project_root)
    epic_id = args.epic.upper()
    story_id = args.story.upper()
    ts = now_iso()

    epic = conn.execute("SELECT id FROM epics WHERE id=?", (epic_id,)).fetchone()
    if not epic:
        conn.close()
        print(f"Epic {epic_id} not found.", file=sys.stderr)
        sys.exit(1)

    story = conn.execute("SELECT id FROM stories WHERE id=? AND epic_id=?", (story_id, epic_id)).fetchone()
    if not story:
        conn.close()
        print(f"Story {story_id} not found in {epic_id}.", file=sys.stderr)
        sys.exit(1)

    conn.execute("UPDATE stories SET status='not-started', updated_at=? WHERE id=? AND epic_id=?", (ts, story_id, epic_id))

    recompute_epic_status(conn, epic_id)

    conn.commit()
    conn.close()

    from formatters import format_get_epic
    print(format_get_epic(project_root, epic_id))


def cmd_view(args):
    """Open HTML viewer in browser."""
    import json
    import subprocess
    import tempfile

    project_root = find_project_root()
    ensure_db(project_root)

    # Build JSON data structure matching old format for viewer compatibility
    conn = get_connection(project_root)
    epics = conn.execute("SELECT * FROM epics ORDER BY id").fetchall()
    config = load_config(project_root)
    data = {"initiative": config.get("name", project_root.name), "updated_at": now_iso(), "epics": []}
    for epic in epics:
        stories = conn.execute("SELECT * FROM stories WHERE epic_id=? ORDER BY sort_order", (epic["id"],)).fetchall()
        data["epics"].append({
            "id": epic["id"],
            "title": epic["title"],
            "stories": [{"id": s["id"], "layer": s["layer"] or "", "title": s["title"], "status": s["status"]} for s in stories],
        })
    conn.close()

    viewer_template = SKILL_DIR / "viewer.html"
    if not viewer_template.exists():
        print("viewer.html template not found.", file=sys.stderr)
        sys.exit(1)

    template = viewer_template.read_text()
    json_str = json.dumps(data, indent=2)
    inline_script = f"const data = {json_str};\n"
    fetch_start = template.index("fetch('./progress.json')")
    catch_end = template.index("});", template.index(".catch(")) + 3
    then_start = template.index("data => {", fetch_start) + len("data => {")
    then_end = template.index("  })\n  .catch", then_start)
    then_body = template[then_start:then_end]
    replacement = inline_script + then_body
    html = template[:fetch_start] + replacement + template[catch_end:]

    out_path = Path(tempfile.gettempdir()) / "revat-progress.html"
    out_path.write_text(html)
    print(f"Viewer written to {out_path}")
    try:
        subprocess.run(["xdg-open", str(out_path)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        try:
            subprocess.run(["open", str(out_path)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            print("Could not auto-open. Open the file manually in a browser.")


# --- Sprint management ---

def cmd_sprint_create(args):
    project_root = find_project_root()
    ensure_db(project_root)
    conn = get_connection(project_root)
    ts = now_iso()
    conn.execute(
        "INSERT INTO sprints (name, goal, start_date, end_date, status, created_at, updated_at) VALUES (?, ?, ?, ?, 'planning', ?, ?)",
        (args.name, args.goal or "", args.start or "", args.end or "", ts, ts),
    )
    sprint_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    print(f"Sprint {sprint_id} created: {args.name}")


def cmd_sprint_list(args):
    from formatters import format_sprint_list
    project_root = find_project_root()
    ensure_db(project_root)
    print(format_sprint_list(project_root))


def cmd_sprint_show(args):
    from formatters import format_sprint_show
    project_root = find_project_root()
    ensure_db(project_root)
    result = format_sprint_show(project_root, args.id)
    if result is None:
        print(f"Sprint {args.id} not found.", file=sys.stderr)
        sys.exit(1)
    print(result)


def cmd_sprint_plan(args):
    from planner import suggest_sprint
    from formatters import format_table
    project_root = find_project_root()
    ensure_db(project_root)

    capacity = args.capacity if hasattr(args, "capacity") and args.capacity else None
    stories = suggest_sprint(project_root, capacity)

    if not stories:
        print("No available stories for planning. Check epic dependencies.")
        return

    total_effort = sum(s.get("effort") or 0 for s in stories)
    print(f"Suggested stories ({len(stories)} stories, {total_effort} pts):")
    print()
    rows = []
    for s in stories:
        effort_str = str(s["effort"]) if s.get("effort") else "\u2014"
        rows.append((f"{s['epic_id']}/{s['id']}", s["title"], effort_str, s.get("layer", "")))
    print(format_table(("Story", "Title", "Effort", "Layer"), rows))
    print()
    print(f"To add these to a sprint: sprint.py sprint add <sprint_id> ...")


def cmd_sprint_add(args):
    project_root = find_project_root()
    ensure_db(project_root)
    conn = get_connection(project_root)

    sprint = conn.execute("SELECT id FROM sprints WHERE id=?", (args.sprint_id,)).fetchone()
    if not sprint:
        print(f"Sprint {args.sprint_id} not found.", file=sys.stderr)
        sys.exit(1)

    # Parse items: E01 S01 S02 E02 S03 S04 -> [(E01, S01), (E01, S02), (E02, S03), (E02, S04)]
    items = args.items
    current_epic = None
    pairs = []
    for item in items:
        item_upper = item.upper()
        if item_upper.startswith("E"):
            current_epic = item_upper
        elif item_upper.startswith("S"):
            if current_epic is None:
                print(f"Story {item_upper} specified without a preceding epic ID.", file=sys.stderr)
                sys.exit(1)
            pairs.append((current_epic, item_upper))
        else:
            print(f"Unrecognized item '{item}'. Expected epic (E01) or story (S01) ID.", file=sys.stderr)
            sys.exit(1)

    if not pairs:
        print("No stories specified.", file=sys.stderr)
        sys.exit(1)

    # Get current max sort_order
    max_order = conn.execute("SELECT COALESCE(MAX(sort_order), -1) as m FROM sprint_stories WHERE sprint_id=?", (args.sprint_id,)).fetchone()["m"]

    added = []
    for epic_id, story_id in pairs:
        story = conn.execute("SELECT id FROM stories WHERE id=? AND epic_id=?", (story_id, epic_id)).fetchone()
        if not story:
            print(f"Story {story_id} not found in {epic_id}.", file=sys.stderr)
            continue
        max_order += 1
        try:
            conn.execute(
                "INSERT INTO sprint_stories (sprint_id, story_id, epic_id, sort_order) VALUES (?, ?, ?, ?)",
                (args.sprint_id, story_id, epic_id, max_order),
            )
            added.append(f"{epic_id}/{story_id}")
        except sqlite3.IntegrityError:
            print(f"{epic_id}/{story_id} already in sprint.", file=sys.stderr)

    conn.commit()
    conn.close()
    if added:
        print(f"Added to sprint {args.sprint_id}: {', '.join(added)}")


def cmd_sprint_remove(args):
    project_root = find_project_root()
    ensure_db(project_root)
    conn = get_connection(project_root)
    epic_id = args.epic.upper()
    story_id = args.story.upper()

    result = conn.execute(
        "DELETE FROM sprint_stories WHERE sprint_id=? AND story_id=? AND epic_id=?",
        (args.sprint_id, story_id, epic_id),
    )
    conn.commit()
    conn.close()
    if result.rowcount:
        print(f"Removed {epic_id}/{story_id} from sprint {args.sprint_id}")
    else:
        print(f"{epic_id}/{story_id} not found in sprint {args.sprint_id}.", file=sys.stderr)


def cmd_sprint_activate(args):
    project_root = find_project_root()
    ensure_db(project_root)
    conn = get_connection(project_root)
    ts = now_iso()
    conn.execute("UPDATE sprints SET status='active', updated_at=? WHERE id=?", (ts, args.id))
    conn.commit()
    conn.close()
    print(f"Sprint {args.id} activated.")


def cmd_sprint_complete(args):
    project_root = find_project_root()
    ensure_db(project_root)
    conn = get_connection(project_root)

    # Check all stories are done
    not_done = conn.execute(
        """SELECT s.id, s.epic_id, s.status FROM sprint_stories ss
           JOIN stories s ON s.id = ss.story_id AND s.epic_id = ss.epic_id
           WHERE ss.sprint_id = ? AND s.status != 'done'""",
        (args.id,),
    ).fetchall()

    if not_done:
        print("Cannot complete sprint — these stories are not done:", file=sys.stderr)
        for s in not_done:
            print(f"  {s['epic_id']}/{s['id']}: {s['status']}", file=sys.stderr)
        sys.exit(1)

    ts = now_iso()
    conn.execute("UPDATE sprints SET status='completed', updated_at=? WHERE id=?", (ts, args.id))
    conn.commit()
    conn.close()
    print(f"Sprint {args.id} completed.")


def cmd_sprint_velocity(args):
    """Show velocity summary across sprints."""
    from formatters import format_table
    project_root = find_project_root()
    ensure_db(project_root)
    conn = get_connection(project_root)

    sprints = conn.execute("SELECT * FROM sprints ORDER BY id").fetchall()
    if not sprints:
        print("No sprints created yet.")
        return

    rows = []
    for sprint in sprints:
        stories = conn.execute(
            """SELECT s.effort, s.status FROM sprint_stories ss
               JOIN stories s ON s.id = ss.story_id AND s.epic_id = ss.epic_id
               WHERE ss.sprint_id = ?""",
            (sprint["id"],),
        ).fetchall()
        total = len(stories)
        done = sum(1 for s in stories if s["status"] == "done")
        total_pts = sum(s["effort"] or 0 for s in stories)
        done_pts = sum(s["effort"] or 0 for s in stories if s["status"] == "done")
        rows.append((
            str(sprint["id"]),
            sprint["name"],
            sprint["status"],
            f"{done}/{total}",
            f"{done_pts}/{total_pts}",
        ))

    print(format_table(("Sprint", "Name", "Status", "Stories", "Points"), rows))
    conn.close()


# --- Agent management ---

def cmd_agent_register(args):
    project_root = find_project_root()
    ensure_db(project_root)
    conn = get_connection(project_root)
    ts = now_iso()
    try:
        conn.execute("INSERT INTO agents (id, created_at) VALUES (?, ?)", (args.name, ts))
        conn.commit()
        print(f"Agent registered: {args.name}")
    except sqlite3.IntegrityError:
        print(f"Agent '{args.name}' already exists.", file=sys.stderr)
    conn.close()


def cmd_agent_list(args):
    project_root = find_project_root()
    ensure_db(project_root)
    conn = get_connection(project_root)
    agents = conn.execute("SELECT * FROM agents ORDER BY id").fetchall()
    conn.close()
    if not agents:
        print("No agents registered.")
        return
    for a in agents:
        print(f"  {a['id']} (registered {a['created_at']})")


def cmd_agent_assign(args):
    project_root = find_project_root()
    ensure_db(project_root)
    conn = get_connection(project_root)
    ts = now_iso()

    agent = conn.execute("SELECT id FROM agents WHERE id=?", (args.agent_id,)).fetchone()
    if not agent:
        print(f"Agent '{args.agent_id}' not found.", file=sys.stderr)
        sys.exit(1)

    sprint = conn.execute("SELECT id FROM sprints WHERE id=?", (args.sprint_id,)).fetchone()
    if not sprint:
        print(f"Sprint {args.sprint_id} not found.", file=sys.stderr)
        sys.exit(1)

    conn.execute("UPDATE sprints SET agent_id=?, updated_at=? WHERE id=?", (args.agent_id, ts, args.sprint_id))
    conn.commit()
    conn.close()
    print(f"Agent '{args.agent_id}' assigned to sprint {args.sprint_id}.")


# --- Briefing ---

def cmd_brief(args):
    from formatters import format_briefing
    project_root = find_project_root()
    ensure_db(project_root)
    config = load_config(project_root)

    # Try to interpret target as sprint ID first
    try:
        sprint_id = int(args.target)
    except ValueError:
        # It's an agent ID — find their active sprint
        conn = get_connection(project_root)
        sprint = conn.execute(
            "SELECT id FROM sprints WHERE agent_id=? AND status IN ('planning', 'active') ORDER BY id DESC LIMIT 1",
            (args.target,),
        ).fetchone()
        conn.close()
        if not sprint:
            print(f"No active sprint found for agent '{args.target}'.", file=sys.stderr)
            sys.exit(1)
        sprint_id = sprint["id"]

    result = format_briefing(project_root, sprint_id, config)
    if result is None:
        print(f"Sprint {sprint_id} not found.", file=sys.stderr)
        sys.exit(1)
    print(result)


# --- Logging ---

def cmd_log(args):
    project_root = find_project_root()
    ensure_db(project_root)
    conn = get_connection(project_root)
    ts = now_iso()

    epic_id = args.epic.upper()
    story_id = args.story.upper()

    valid_events = {"start", "progress", "blocker", "error", "resolution", "completion", "failure", "note"}
    if args.event_type not in valid_events:
        print(f"Invalid event type. Valid: {', '.join(sorted(valid_events))}", file=sys.stderr)
        sys.exit(1)

    # Find active sprint for this story (if any)
    sprint_row = conn.execute(
        """SELECT ss.sprint_id FROM sprint_stories ss
           JOIN sprints sp ON sp.id = ss.sprint_id
           WHERE ss.story_id=? AND ss.epic_id=? AND sp.status='active'
           LIMIT 1""",
        (story_id, epic_id),
    ).fetchone()
    sprint_id = sprint_row["sprint_id"] if sprint_row else None

    message = " ".join(args.message) if args.message else ""

    conn.execute(
        "INSERT INTO progress_log (story_id, epic_id, sprint_id, agent_id, event_type, message, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (story_id, epic_id, sprint_id, None, args.event_type, message, ts),
    )
    conn.commit()
    conn.close()
    print(f"Logged {args.event_type} for {epic_id}/{story_id}")


def cmd_log_history(args):
    from formatters import format_log_history
    project_root = find_project_root()
    ensure_db(project_root)

    sprint_id = args.sprint if hasattr(args, "sprint") and args.sprint else None
    epic_id = args.epic if hasattr(args, "epic") and args.epic else None
    story_id = args.story if hasattr(args, "story") and args.story else None

    print(format_log_history(project_root, epic_id, story_id, sprint_id))


# --- Worktree ---

def cmd_worktree_create(args):
    from git_ops import worktree_create
    project_root = find_project_root()
    ensure_db(project_root)
    ok, msg = worktree_create(project_root, args.sprint_id)
    print(msg)
    if not ok:
        sys.exit(1)


def cmd_worktree_destroy(args):
    from git_ops import worktree_destroy
    project_root = find_project_root()
    ensure_db(project_root)
    ok, msg = worktree_destroy(project_root, args.sprint_id)
    print(msg)
    if not ok:
        sys.exit(1)


def cmd_worktree_list(args):
    from git_ops import worktree_list
    project_root = find_project_root()
    ensure_db(project_root)
    print(worktree_list(project_root))


def main():
    parser = argparse.ArgumentParser(description="Sprint management CLI")
    sub = parser.add_subparsers(dest="command")

    # --- Backward-compatible commands ---
    get_p = sub.add_parser("get", help="Show progress overview or epic detail")
    get_p.add_argument("epic", nargs="?", help="Epic ID (e.g. E01)")

    update_p = sub.add_parser("update", help="Update story statuses")
    update_p.add_argument("epic", help="Epic ID")
    update_p.add_argument("pairs", nargs="+", help="Story-status pairs (e.g. S01 done)")

    revert_p = sub.add_parser("revert", help="Reset a story to not-started")
    revert_p.add_argument("epic", help="Epic ID")
    revert_p.add_argument("story", help="Story ID")

    sub.add_parser("sync", help="Sync DB from spec files")
    sub.add_parser("view", help="Open HTML viewer")

    # --- Sprint management ---
    sprint_p = sub.add_parser("sprint", help="Sprint management")
    sprint_sub = sprint_p.add_subparsers(dest="sprint_command")

    sc = sprint_sub.add_parser("create", help="Create a sprint")
    sc.add_argument("name", help="Sprint name")
    sc.add_argument("--goal", help="Sprint goal")
    sc.add_argument("--start", help="Start date")
    sc.add_argument("--end", help="End date")

    sprint_sub.add_parser("list", help="List sprints")

    ss = sprint_sub.add_parser("show", help="Show sprint detail")
    ss.add_argument("id", type=int, help="Sprint ID")

    sp = sprint_sub.add_parser("plan", help="Suggest stories for a sprint")
    sp.add_argument("id", type=int, nargs="?", help="Sprint ID")
    sp.add_argument("--capacity", type=int, help="Max story points")

    sa = sprint_sub.add_parser("add", help="Add stories to sprint")
    sa.add_argument("sprint_id", type=int, help="Sprint ID")
    sa.add_argument("items", nargs="+", help="Epic and story IDs (e.g. E01 S01 S02 E02 S03)")

    sr = sprint_sub.add_parser("remove", help="Remove story from sprint")
    sr.add_argument("sprint_id", type=int, help="Sprint ID")
    sr.add_argument("epic", help="Epic ID")
    sr.add_argument("story", help="Story ID")

    sact = sprint_sub.add_parser("activate", help="Activate a sprint")
    sact.add_argument("id", type=int, help="Sprint ID")

    scomp = sprint_sub.add_parser("complete", help="Complete a sprint")
    scomp.add_argument("id", type=int, help="Sprint ID")

    sprint_sub.add_parser("velocity", help="Show velocity across sprints")

    # --- Agent management ---
    agent_p = sub.add_parser("agent", help="Agent management")
    agent_sub = agent_p.add_subparsers(dest="agent_command")

    ar = agent_sub.add_parser("register", help="Register an agent")
    ar.add_argument("name", help="Agent name/ID")

    agent_sub.add_parser("list", help="List agents")

    aas = agent_sub.add_parser("assign", help="Assign agent to sprint")
    aas.add_argument("agent_id", help="Agent ID")
    aas.add_argument("sprint_id", type=int, help="Sprint ID")

    # --- Briefing ---
    brief_p = sub.add_parser("brief", help="Generate agent briefing")
    brief_p.add_argument("target", help="Sprint ID or agent ID")

    # --- Logging ---
    # log uses manual arg parsing to support both:
    #   log EPIC STORY event [message...]
    #   log history [EPIC] [STORY] [--sprint N]
    log_p = sub.add_parser("log", help="Progress logging")
    log_p.add_argument("log_args", nargs="*", help="EPIC STORY event [message...] OR history [EPIC] [STORY] [--sprint N]")

    # --- Worktree ---
    wt_p = sub.add_parser("worktree", help="Git worktree management")
    wt_sub = wt_p.add_subparsers(dest="worktree_command")

    wtc = wt_sub.add_parser("create", help="Create worktree for sprint")
    wtc.add_argument("sprint_id", type=int, help="Sprint ID")

    wtd = wt_sub.add_parser("destroy", help="Destroy sprint worktree")
    wtd.add_argument("sprint_id", type=int, help="Sprint ID")

    wt_sub.add_parser("list", help="List active worktrees")

    # --- Admin ---
    sub.add_parser("init", help="Initialize database")
    sub.add_parser("migrate", help="Import from progress.json")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # Route commands
    if args.command == "init":
        cmd_init(args)
    elif args.command == "migrate":
        cmd_migrate(args)
    elif args.command == "sync":
        cmd_sync(args)
    elif args.command == "get":
        cmd_get(args)
    elif args.command == "update":
        cmd_update(args)
    elif args.command == "revert":
        cmd_revert(args)
    elif args.command == "view":
        cmd_view(args)
    elif args.command == "sprint":
        if args.sprint_command == "create":
            cmd_sprint_create(args)
        elif args.sprint_command == "list":
            cmd_sprint_list(args)
        elif args.sprint_command == "show":
            cmd_sprint_show(args)
        elif args.sprint_command == "plan":
            cmd_sprint_plan(args)
        elif args.sprint_command == "add":
            cmd_sprint_add(args)
        elif args.sprint_command == "remove":
            cmd_sprint_remove(args)
        elif args.sprint_command == "activate":
            cmd_sprint_activate(args)
        elif args.sprint_command == "complete":
            cmd_sprint_complete(args)
        elif args.sprint_command == "velocity":
            cmd_sprint_velocity(args)
        else:
            sprint_p.print_help()
    elif args.command == "agent":
        if args.agent_command == "register":
            cmd_agent_register(args)
        elif args.agent_command == "list":
            cmd_agent_list(args)
        elif args.agent_command == "assign":
            cmd_agent_assign(args)
        else:
            agent_p.print_help()
    elif args.command == "brief":
        cmd_brief(args)
    elif args.command == "log":
        log_args = args.log_args
        if not log_args:
            log_p.print_help()
        elif log_args[0] == "history":
            # log history [EPIC] [STORY] [--sprint N]
            args.epic = log_args[1] if len(log_args) > 1 and not log_args[1].startswith("--") else None
            args.story = log_args[2] if len(log_args) > 2 and not log_args[2].startswith("--") else None
            args.sprint = None
            for i, a in enumerate(log_args):
                if a == "--sprint" and i + 1 < len(log_args):
                    args.sprint = int(log_args[i + 1])
            cmd_log_history(args)
        elif len(log_args) >= 3:
            # log EPIC STORY event [message...]
            args.epic = log_args[0]
            args.story = log_args[1]
            args.event_type = log_args[2]
            args.message = log_args[3:]
            cmd_log(args)
        else:
            log_p.print_help()
    elif args.command == "worktree":
        if args.worktree_command == "create":
            cmd_worktree_create(args)
        elif args.worktree_command == "destroy":
            cmd_worktree_destroy(args)
        elif args.worktree_command == "list":
            cmd_worktree_list(args)
        else:
            wt_p.print_help()


if __name__ == "__main__":
    main()
