"""Database connection management, schema initialization, and migrations."""

import configparser
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = SKILL_DIR / "schema.sql"


def now_iso():
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_project_root(start=None):
    """Walk up from start (or CWD) looking for project root.

    Priority:
    1. Directory containing .claude/sprint.conf
    2. Directory containing .claude/sprint.db
    3. Directory containing CLAUDE.md
    """
    current = Path(start or Path.cwd()).resolve()
    # First pass: look for sprint.conf or sprint.db
    check = current
    while check != check.parent:
        if (check / ".claude" / "sprint.conf").exists():
            return check
        if (check / ".claude" / "sprint.db").exists():
            return check
        check = check.parent
    # Second pass: look for CLAUDE.md
    check = current
    while check != check.parent:
        if (check / "CLAUDE.md").exists():
            return check
        check = check.parent
    return current


def load_config(project_root):
    """Load sprint.conf for a project, returning a dict of settings."""
    conf_path = project_root / ".claude" / "sprint.conf"
    config = configparser.ConfigParser()
    if conf_path.exists():
        config.read(conf_path)
    defaults = {
        "name": project_root.name,
        "root": str(project_root),
        "build_plan": "build-plan",
        "main_branch": "main",
        "repos": "",
    }
    if config.has_section("project"):
        for key in defaults:
            if config.has_option("project", key):
                defaults[key] = config.get("project", key)
    return defaults


def save_config(project_root, settings):
    """Save sprint.conf for a project."""
    conf_path = project_root / ".claude" / "sprint.conf"
    conf_path.parent.mkdir(parents=True, exist_ok=True)
    config = configparser.ConfigParser()
    config["project"] = settings
    with open(conf_path, "w") as f:
        config.write(f)


def db_path(project_root):
    """Return the path to the SQLite database for this project."""
    return project_root / ".claude" / "sprint.db"


def get_connection(project_root):
    """Get a SQLite connection for the given project root."""
    path = db_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(project_root):
    """Initialize the database schema."""
    conn = get_connection(project_root)
    schema = SCHEMA_PATH.read_text()
    conn.executescript(schema)
    conn.commit()
    conn.close()
    return db_path(project_root)


def recompute_epic_status(conn, epic_id):
    """Recompute and update an epic's status based on its stories."""
    stories = conn.execute("SELECT status FROM stories WHERE epic_id=?", (epic_id,)).fetchall()
    if not stories:
        status = "not-started"
    else:
        statuses = [s["status"] for s in stories]
        if all(s == "done" for s in statuses):
            status = "complete"
        elif any(s == "blocked" for s in statuses) and not any(s == "in-progress" for s in statuses):
            status = "blocked"
        elif any(s in ("done", "in-progress") for s in statuses):
            status = "in-progress"
        else:
            status = "not-started"
    conn.execute("UPDATE epics SET status=?, updated_at=? WHERE id=?", (status, now_iso(), epic_id))
    return status


def migrate_from_json(project_root, json_path):
    """Import data from a progress.json file into the database."""
    import json

    with open(json_path) as f:
        data = json.load(f)

    conn = get_connection(project_root)
    ts = now_iso()

    for epic in data.get("epics", []):
        conn.execute(
            "INSERT OR REPLACE INTO epics (id, title, slug, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (epic["id"], epic["title"], "", "not-started", ts, ts),
        )
        for idx, story in enumerate(epic.get("stories", [])):
            conn.execute(
                "INSERT OR REPLACE INTO stories (id, epic_id, title, layer, status, sort_order, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (story["id"], epic["id"], story["title"], story.get("layer", ""), story["status"], idx, ts, ts),
            )

    conn.commit()
    conn.close()
