"""Dependency resolution and sprint planning suggestions."""

from db import get_connection


def get_available_stories(project_root):
    """Return stories available for sprint planning, respecting dependencies.

    Rules:
    1. Exclude stories from epics whose epic dependencies aren't complete
    2. Exclude stories whose story dependencies aren't done
    3. Exclude stories already in any sprint
    4. Exclude stories with status != not-started
    5. Order by epic priority (E01 < E02), then sort_order within epic
    """
    conn = get_connection(project_root)

    # Find epics whose dependencies are all complete
    all_epics = {row["id"]: row for row in conn.execute("SELECT * FROM epics ORDER BY id").fetchall()}
    available_epics = set()

    for epic_id, epic in all_epics.items():
        deps = conn.execute("SELECT depends_on FROM epic_dependencies WHERE epic_id=?", (epic_id,)).fetchall()
        if not deps:
            available_epics.add(epic_id)
        else:
            all_deps_met = all(
                d["depends_on"] in all_epics and all_epics[d["depends_on"]]["status"] == "complete"
                for d in deps
            )
            # Also allow if the epic itself is already in progress
            if all_deps_met or epic["status"] in ("in-progress", "complete"):
                available_epics.add(epic_id)

    # Get stories already assigned to any sprint
    assigned = set()
    for row in conn.execute("SELECT story_id, epic_id FROM sprint_stories").fetchall():
        assigned.add((row["story_id"], row["epic_id"]))

    # Collect available stories
    available = []
    for epic_id in sorted(available_epics):
        stories = conn.execute(
            "SELECT * FROM stories WHERE epic_id=? AND status='not-started' ORDER BY sort_order",
            (epic_id,),
        ).fetchall()

        for story in stories:
            if (story["id"], story["epic_id"]) in assigned:
                continue

            # Check story-level dependencies
            story_deps = conn.execute(
                "SELECT depends_on_story, depends_on_epic FROM story_dependencies WHERE story_id=? AND story_epic_id=?",
                (story["id"], story["epic_id"]),
            ).fetchall()

            deps_met = True
            for dep in story_deps:
                dep_status = conn.execute(
                    "SELECT status FROM stories WHERE id=? AND epic_id=?",
                    (dep["depends_on_story"], dep["depends_on_epic"]),
                ).fetchone()
                if not dep_status or dep_status["status"] != "done":
                    deps_met = False
                    break

            if deps_met:
                available.append(dict(story))

    conn.close()
    return available


def suggest_sprint(project_root, capacity=None):
    """Suggest stories for a sprint, optionally limited by capacity (story points)."""
    available = get_available_stories(project_root)

    if capacity is None:
        return available

    selected = []
    total = 0
    for story in available:
        effort = story.get("effort") or 0
        if effort == 0:
            # Include stories without effort estimates (they don't count against capacity)
            selected.append(story)
        elif total + effort <= capacity:
            selected.append(story)
            total += effort

    return selected
