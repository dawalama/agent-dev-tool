"""Database models for ADT."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"
    AWAITING_REVIEW = "awaiting_review"  # Needs human approval


class TaskPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    
    def sort_key(self) -> int:
        return {"urgent": 0, "high": 1, "normal": 2, "low": 3}[self.value]


class Project(BaseModel):
    """A registered project."""
    name: str
    path: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    config: Optional[dict[str, Any]] = None


class Task(BaseModel):
    """A task in the queue."""
    id: str
    project: str
    description: str
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    assigned_to: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    metadata: Optional[dict[str, Any]] = None
    
    # Task chaining
    depends_on: Optional[list[str]] = None  # Task IDs this depends on
    output: Optional[str] = None  # Captured output from agent
    output_artifacts: Optional[list[str]] = None  # File paths created
    next_tasks: Optional[list[str]] = None  # Tasks to trigger on completion
    
    # Review mode
    requires_review: bool = False  # If true, task pauses for approval before running
    review_prompt: Optional[str] = None  # What to show the reviewer
    reviewed_by: Optional[str] = None  # Who approved/rejected
    reviewed_at: Optional[datetime] = None


class AgentRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class AgentRun(BaseModel):
    """A single agent run (for history)."""
    id: Optional[int] = None
    project: str
    provider: Optional[str] = None
    task: Optional[str] = None
    task_id: Optional[str] = None
    pid: Optional[int] = None
    started_at: datetime = Field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None
    exit_code: Optional[int] = None
    status: AgentRunStatus = AgentRunStatus.RUNNING
    error: Optional[str] = None
    log_file: Optional[str] = None


class EventLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class Event(BaseModel):
    """A logged event."""
    id: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.now)
    type: str
    project: Optional[str] = None
    agent: Optional[str] = None
    task_id: Optional[str] = None
    level: EventLevel = EventLevel.INFO
    message: Optional[str] = None
    data: Optional[dict[str, Any]] = None
