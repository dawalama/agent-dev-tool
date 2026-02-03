"""Task queue management."""

import json
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from ..config import get_adt_home


class TaskStatus(str, Enum):
    """Task status states."""
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"  # Waiting for human input
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    """Task priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    
    def __lt__(self, other: "TaskPriority") -> bool:
        order = [TaskPriority.LOW, TaskPriority.NORMAL, TaskPriority.HIGH, TaskPriority.URGENT]
        return order.index(self) < order.index(other)


class Task(BaseModel):
    """A task in the queue."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    project: str
    description: str
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    
    assigned_to: str | None = None  # Agent/worktree name
    result: str | None = None
    error: str | None = None
    
    retry_count: int = 0
    max_retries: int = 3
    
    metadata: dict = Field(default_factory=dict)
    
    def is_terminal(self) -> bool:
        """Check if task is in a terminal state."""
        return self.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
    
    def can_retry(self) -> bool:
        """Check if task can be retried."""
        return self.retry_count < self.max_retries


class TaskQueue:
    """Persistent task queue with priority ordering."""
    
    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._load()
    
    def _get_path(self) -> Path:
        """Get the queue file path."""
        return get_adt_home() / "queue" / "tasks.json"
    
    def _load(self) -> None:
        """Load tasks from file."""
        path = self._get_path()
        if not path.exists():
            return
        
        try:
            data = json.loads(path.read_text())
            for task_data in data:
                task = Task.model_validate(task_data)
                self._tasks[task.id] = task
        except Exception:
            pass
    
    def _save(self) -> None:
        """Save tasks to file."""
        path = self._get_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        
        data = [task.model_dump(mode="json") for task in self._tasks.values()]
        path.write_text(json.dumps(data, indent=2, default=str))
    
    def add(self, task: Task) -> Task:
        """Add a task to the queue."""
        self._tasks[task.id] = task
        self._save()
        return task
    
    def create(
        self,
        project: str,
        description: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        **metadata,
    ) -> Task:
        """Create and add a new task."""
        task = Task(
            project=project,
            description=description,
            priority=priority,
            metadata=metadata,
        )
        return self.add(task)
    
    def get(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        return self._tasks.get(task_id)
    
    def list(
        self,
        project: str | None = None,
        status: TaskStatus | None = None,
        include_completed: bool = False,
    ) -> list[Task]:
        """List tasks with optional filters."""
        tasks = list(self._tasks.values())
        
        if project:
            tasks = [t for t in tasks if t.project == project]
        
        if status:
            tasks = [t for t in tasks if t.status == status]
        elif not include_completed:
            tasks = [t for t in tasks if not t.is_terminal()]
        
        # Sort by priority (descending) then created_at (ascending)
        tasks.sort(key=lambda t: (t.priority, t.created_at), reverse=True)
        
        return tasks
    
    def next(self, project: str | None = None) -> Task | None:
        """Get the next task to work on."""
        pending = self.list(project=project, status=TaskStatus.PENDING)
        return pending[0] if pending else None
    
    def update(self, task_id: str, **updates) -> Task | None:
        """Update a task."""
        task = self._tasks.get(task_id)
        if not task:
            return None
        
        for key, value in updates.items():
            if hasattr(task, key):
                setattr(task, key, value)
        
        self._save()
        return task
    
    def assign(self, task_id: str, agent: str) -> Task | None:
        """Assign a task to an agent."""
        return self.update(
            task_id,
            assigned_to=agent,
            status=TaskStatus.ASSIGNED,
            started_at=datetime.now(),
        )
    
    def start(self, task_id: str) -> Task | None:
        """Mark a task as in progress."""
        return self.update(task_id, status=TaskStatus.IN_PROGRESS)
    
    def complete(self, task_id: str, result: str | None = None) -> Task | None:
        """Mark a task as completed."""
        return self.update(
            task_id,
            status=TaskStatus.COMPLETED,
            completed_at=datetime.now(),
            result=result,
        )
    
    def fail(self, task_id: str, error: str) -> Task | None:
        """Mark a task as failed."""
        task = self._tasks.get(task_id)
        if not task:
            return None
        
        task.retry_count += 1
        
        if task.can_retry():
            task.status = TaskStatus.PENDING
            task.error = f"Retry {task.retry_count}: {error}"
        else:
            task.status = TaskStatus.FAILED
            task.error = error
            task.completed_at = datetime.now()
        
        self._save()
        return task
    
    def block(self, task_id: str, reason: str) -> Task | None:
        """Mark a task as blocked (needs human input)."""
        return self.update(
            task_id,
            status=TaskStatus.BLOCKED,
            error=reason,
        )
    
    def cancel(self, task_id: str) -> Task | None:
        """Cancel a task."""
        return self.update(
            task_id,
            status=TaskStatus.CANCELLED,
            completed_at=datetime.now(),
        )
    
    def remove(self, task_id: str) -> bool:
        """Remove a task from the queue."""
        if task_id in self._tasks:
            del self._tasks[task_id]
            self._save()
            return True
        return False
    
    def clear_completed(self, older_than_days: int = 7) -> int:
        """Remove completed/failed/cancelled tasks older than N days."""
        cutoff = datetime.now().timestamp() - (older_than_days * 86400)
        count = 0
        
        for task_id, task in list(self._tasks.items()):
            if task.is_terminal() and task.completed_at:
                if task.completed_at.timestamp() < cutoff:
                    del self._tasks[task_id]
                    count += 1
        
        if count > 0:
            self._save()
        
        return count
    
    def stats(self) -> dict:
        """Get queue statistics."""
        tasks = list(self._tasks.values())
        return {
            "total": len(tasks),
            "pending": len([t for t in tasks if t.status == TaskStatus.PENDING]),
            "in_progress": len([t for t in tasks if t.status == TaskStatus.IN_PROGRESS]),
            "blocked": len([t for t in tasks if t.status == TaskStatus.BLOCKED]),
            "completed": len([t for t in tasks if t.status == TaskStatus.COMPLETED]),
            "failed": len([t for t in tasks if t.status == TaskStatus.FAILED]),
            "by_project": {
                project: len([t for t in tasks if t.project == project])
                for project in set(t.project for t in tasks)
            },
        }
