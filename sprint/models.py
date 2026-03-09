"""Dataclasses for sprint management entities."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Epic:
    id: str
    title: str
    slug: str = ""
    status: str = "not-started"
    created_at: str = ""
    updated_at: str = ""
    stories: list = field(default_factory=list)
    dependencies: list = field(default_factory=list)


@dataclass
class Story:
    id: str
    epic_id: str
    title: str
    layer: str = ""
    status: str = "not-started"
    effort: Optional[int] = None
    sort_order: int = 0
    spec_path: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Sprint:
    id: Optional[int] = None
    name: str = ""
    goal: str = ""
    start_date: str = ""
    end_date: str = ""
    status: str = "planning"
    agent_id: Optional[str] = None
    branch_name: str = ""
    worktree_path: str = ""
    created_at: str = ""
    updated_at: str = ""
    stories: list = field(default_factory=list)


@dataclass
class Agent:
    id: str = ""
    created_at: str = ""


@dataclass
class LogEntry:
    id: Optional[int] = None
    story_id: str = ""
    epic_id: str = ""
    sprint_id: Optional[int] = None
    agent_id: Optional[str] = None
    event_type: str = ""
    message: str = ""
    created_at: str = ""
