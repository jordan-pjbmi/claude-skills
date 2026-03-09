"""Parse structure.md and epic spec files to populate the database."""

import re
from pathlib import Path

from db import get_connection, now_iso, recompute_epic_status


def parse_structure_md(structure_path):
    """Parse structure.md to extract epics, their titles, and dependency info."""
    if not structure_path.exists():
        return [], {}

    text = structure_path.read_text()
    epics = []
    dependencies = {}

    # Extract epics from ### E{N}: Title format
    for match in re.finditer(r"###\s+E(\d+):\s+(.+)", text):
        epic_id = f"E{match.group(1).zfill(2)}"
        title = match.group(2).strip()
        epics.append({"id": epic_id, "title": title})

    # Extract dependencies from **Dependencies:** lines following each epic heading
    # We parse section-by-section
    sections = re.split(r"###\s+E(\d+):", text)
    # sections[0] is before first epic, then pairs of (number, body)
    for i in range(1, len(sections), 2):
        epic_id = f"E{sections[i].zfill(2)}"
        body = sections[i + 1] if i + 1 < len(sections) else ""
        dep_match = re.search(r"\*\*Dependencies:\*\*\s*(.+)", body)
        if dep_match:
            dep_text = dep_match.group(1).strip()
            if dep_text.lower() not in ("none", "none (root)", "all epics"):
                # Parse "E1", "E2, E7", "E3, E4" etc.
                dep_ids = []
                for d in re.findall(r"E(\d+)", dep_text):
                    dep_ids.append(f"E{d.zfill(2)}")
                if dep_ids:
                    dependencies[epic_id] = dep_ids
            elif dep_text.lower() == "all epics":
                # E09 depends on all others — we'll resolve this after collecting all epics
                dependencies[epic_id] = "__ALL__"

    # Resolve "all epics"
    all_epic_ids = [e["id"] for e in epics]
    for eid, deps in dependencies.items():
        if deps == "__ALL__":
            dependencies[eid] = [x for x in all_epic_ids if x != eid]

    return epics, dependencies


def parse_epic_spec(spec_path):
    """Parse an epic spec.md to extract story info from the Story Overview table."""
    text = spec_path.read_text()
    stories = []
    in_table = False
    for line in text.splitlines():
        if "| Story |" in line and "Layer" in line:
            in_table = True
            continue
        if in_table and (line.startswith("|---") or line.startswith("| ---")):
            continue
        if in_table and line.startswith("|"):
            cols = [c.strip() for c in line.split("|")[1:-1]]
            if len(cols) >= 3:
                story_id = cols[0].strip()
                layer = cols[1].strip()
                title = cols[2].strip()
                # Extract spec path if present
                spec_ref = cols[3].strip() if len(cols) >= 4 else ""
                # Clean up backtick-wrapped paths
                spec_ref = spec_ref.strip("`")
                if re.match(r"S\d+", story_id):
                    stories.append({
                        "id": story_id,
                        "layer": layer,
                        "title": title,
                        "spec_ref": spec_ref,
                    })
        elif in_table and not line.startswith("|"):
            break
    return stories


def parse_story_effort(spec_path):
    """Parse a story spec.md to extract the Effort field."""
    if not spec_path.exists():
        return None
    text = spec_path.read_text()
    # Look for Effort: N or **Effort:** N patterns
    match = re.search(r"\*?\*?Effort\*?\*?:\s*(\d+)", text)
    if match:
        return int(match.group(1))
    return None


def resolve_story_spec_path(epic_dir, story):
    """Resolve the absolute path to a story's spec.md."""
    # Try the spec_ref from the table first
    if story.get("spec_ref"):
        candidate = epic_dir / story["spec_ref"]
        if candidate.exists():
            return candidate

    # Try common patterns
    story_id_lower = story["id"].lower()
    # Look for directories matching S{XX}-*
    for d in sorted(epic_dir.glob("stories/") if (epic_dir / "stories").exists() else []):
        pass

    # Try stories/S{XX}-*/spec.md pattern
    for spec in sorted(epic_dir.glob(f"stories/{story_id_lower}-*/spec.md")):
        return spec
    for spec in sorted(epic_dir.glob(f"stories/{story['id']}-*/spec.md")):
        return spec

    return None


def sync_to_db(project_root, build_plan_path):
    """Sync spec files into the database. Returns a summary of changes."""
    conn = get_connection(project_root)
    ts = now_iso()
    changes = {"added_epics": [], "removed_epics": [], "added_stories": [], "removed_stories": [], "updated": []}

    structure_path = build_plan_path / "structure.md"
    spec_epics, epic_deps = parse_structure_md(structure_path)
    spec_epic_ids = {e["id"] for e in spec_epics}

    # Get existing epics
    existing = {row["id"]: dict(row) for row in conn.execute("SELECT * FROM epics").fetchall()}

    # Add/update epics
    for epic in spec_epics:
        if epic["id"] not in existing:
            # Derive slug from epic dir name
            slug = ""
            for d in sorted((build_plan_path / "epics").glob(f"{epic['id']}*")) if (build_plan_path / "epics").exists() else []:
                slug = d.name.split("-", 1)[1] if "-" in d.name else ""
                break
            conn.execute(
                "INSERT INTO epics (id, title, slug, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (epic["id"], epic["title"], slug, "not-started", ts, ts),
            )
            changes["added_epics"].append(epic["id"])
        else:
            if existing[epic["id"]]["title"] != epic["title"]:
                conn.execute("UPDATE epics SET title=?, updated_at=? WHERE id=?", (epic["title"], ts, epic["id"]))
                changes["updated"].append(f"{epic['id']} title: '{existing[epic['id']]['title']}' -> '{epic['title']}'")

    # Remove epics not in structure.md
    for eid in existing:
        if eid not in spec_epic_ids:
            conn.execute("DELETE FROM stories WHERE epic_id=?", (eid,))
            conn.execute("DELETE FROM epics WHERE id=?", (eid,))
            changes["removed_epics"].append(eid)

    # Sync epic dependencies
    conn.execute("DELETE FROM epic_dependencies")
    for epic_id, deps in epic_deps.items():
        for dep in deps:
            if dep in spec_epic_ids and epic_id in spec_epic_ids:
                conn.execute("INSERT OR IGNORE INTO epic_dependencies (epic_id, depends_on) VALUES (?, ?)", (epic_id, dep))

    # Sync stories from epic specs
    epics_dir = build_plan_path / "epics"
    if epics_dir.exists():
        for spec_path in sorted(epics_dir.glob("E*-*/spec.md")):
            dir_name = spec_path.parent.name
            match = re.match(r"E(\d+)", dir_name)
            if not match:
                continue
            epic_id = f"E{match.group(1).zfill(2)}"
            if epic_id not in spec_epic_ids:
                continue

            epic_dir = spec_path.parent
            spec_stories = parse_epic_spec(spec_path)
            spec_story_ids = {s["id"] for s in spec_stories}

            # Get existing stories for this epic
            existing_stories = {
                row["id"]: dict(row)
                for row in conn.execute("SELECT * FROM stories WHERE epic_id=?", (epic_id,)).fetchall()
            }

            # Add/update stories
            for idx, story in enumerate(spec_stories):
                # Try to parse effort from individual story spec
                story_spec = resolve_story_spec_path(epic_dir, story)
                effort = parse_story_effort(story_spec) if story_spec else None
                rel_spec_path = str(story_spec.relative_to(build_plan_path)) if story_spec else story.get("spec_ref", "")

                if story["id"] not in existing_stories:
                    conn.execute(
                        "INSERT INTO stories (id, epic_id, title, layer, status, effort, sort_order, spec_path, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (story["id"], epic_id, story["title"], story["layer"], "not-started", effort, idx, rel_spec_path, ts, ts),
                    )
                    changes["added_stories"].append(f"{epic_id}/{story['id']}")
                else:
                    es = existing_stories[story["id"]]
                    updates = []
                    params = []
                    if es["title"] != story["title"]:
                        updates.append("title=?")
                        params.append(story["title"])
                        changes["updated"].append(f"{epic_id}/{story['id']} title updated")
                    if es["layer"] != story["layer"]:
                        updates.append("layer=?")
                        params.append(story["layer"])
                        changes["updated"].append(f"{epic_id}/{story['id']} layer updated")
                    if effort is not None and es["effort"] != effort:
                        updates.append("effort=?")
                        params.append(effort)
                    if rel_spec_path and es["spec_path"] != rel_spec_path:
                        updates.append("spec_path=?")
                        params.append(rel_spec_path)
                    updates.append("sort_order=?")
                    params.append(idx)
                    if updates:
                        updates.append("updated_at=?")
                        params.append(ts)
                        params.extend([story["id"], epic_id])
                        conn.execute(f"UPDATE stories SET {', '.join(updates)} WHERE id=? AND epic_id=?", params)

            # Remove stories not in spec
            for sid in existing_stories:
                if sid not in spec_story_ids:
                    conn.execute("DELETE FROM stories WHERE id=? AND epic_id=?", (sid, epic_id))
                    changes["removed_stories"].append(f"{epic_id}/{sid}")

    # Recompute epic statuses
    for epic in spec_epics:
        recompute_epic_status(conn, epic["id"])

    conn.commit()
    conn.close()
    return changes
