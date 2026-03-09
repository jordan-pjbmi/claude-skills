-- Sprint management schema

CREATE TABLE IF NOT EXISTS epics (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    slug TEXT,
    status TEXT NOT NULL DEFAULT 'not-started',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS epic_dependencies (
    epic_id TEXT NOT NULL REFERENCES epics(id),
    depends_on TEXT NOT NULL REFERENCES epics(id),
    PRIMARY KEY (epic_id, depends_on)
);

CREATE TABLE IF NOT EXISTS stories (
    id TEXT NOT NULL,
    epic_id TEXT NOT NULL REFERENCES epics(id),
    title TEXT NOT NULL,
    layer TEXT,
    status TEXT NOT NULL DEFAULT 'not-started',
    effort INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 0,
    spec_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (id, epic_id)
);

CREATE TABLE IF NOT EXISTS story_dependencies (
    story_id TEXT NOT NULL,
    story_epic_id TEXT NOT NULL,
    depends_on_story TEXT NOT NULL,
    depends_on_epic TEXT NOT NULL,
    PRIMARY KEY (story_id, story_epic_id, depends_on_story, depends_on_epic),
    FOREIGN KEY (story_id, story_epic_id) REFERENCES stories(id, epic_id),
    FOREIGN KEY (depends_on_story, depends_on_epic) REFERENCES stories(id, epic_id)
);

CREATE TABLE IF NOT EXISTS sprints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    goal TEXT,
    start_date TEXT,
    end_date TEXT,
    status TEXT NOT NULL DEFAULT 'planning',
    agent_id TEXT REFERENCES agents(id),
    branch_name TEXT,
    worktree_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sprint_stories (
    sprint_id INTEGER NOT NULL REFERENCES sprints(id),
    story_id TEXT NOT NULL,
    epic_id TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (sprint_id, story_id, epic_id),
    FOREIGN KEY (story_id, epic_id) REFERENCES stories(id, epic_id)
);

CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS progress_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id TEXT NOT NULL,
    epic_id TEXT NOT NULL,
    sprint_id INTEGER REFERENCES sprints(id),
    agent_id TEXT REFERENCES agents(id),
    event_type TEXT NOT NULL,
    message TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (story_id, epic_id) REFERENCES stories(id, epic_id)
);
