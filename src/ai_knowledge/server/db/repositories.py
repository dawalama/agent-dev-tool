"""Repository classes for database operations."""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from typing import Optional

from .connection import get_db
from .models import (
    Project,
    Task,
    TaskStatus,
    TaskPriority,
    AgentRun,
    AgentRunStatus,
    Event,
    EventLevel,
)


class ProjectRepository:
    """Repository for project operations."""
    
    def __init__(self):
        self.db = get_db("main")
    
    def create(self, project: Project) -> Project:
        """Create a new project."""
        self.db.execute("""
            INSERT INTO projects (name, path, created_at, updated_at, config)
            VALUES (?, ?, ?, ?, ?)
        """, (
            project.name,
            project.path,
            project.created_at.isoformat(),
            project.updated_at.isoformat(),
            json.dumps(project.config) if project.config else None,
        ))
        self.db.commit()
        return project
    
    def get(self, name: str) -> Optional[Project]:
        """Get a project by name."""
        cursor = self.db.execute(
            "SELECT * FROM projects WHERE name = ?", (name,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_project(row)
    
    def list(self) -> list[Project]:
        """List all projects."""
        cursor = self.db.execute("SELECT * FROM projects ORDER BY name")
        return [self._row_to_project(row) for row in cursor.fetchall()]
    
    def update(self, project: Project) -> Project:
        """Update a project."""
        project.updated_at = datetime.now()
        self.db.execute("""
            UPDATE projects SET path = ?, updated_at = ?, config = ?
            WHERE name = ?
        """, (
            project.path,
            project.updated_at.isoformat(),
            json.dumps(project.config) if project.config else None,
            project.name,
        ))
        self.db.commit()
        return project
    
    def delete(self, name: str) -> bool:
        """Delete a project."""
        cursor = self.db.execute("DELETE FROM projects WHERE name = ?", (name,))
        self.db.commit()
        return cursor.rowcount > 0
    
    def _row_to_project(self, row) -> Project:
        return Project(
            name=row["name"],
            path=row["path"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            config=json.loads(row["config"]) if row["config"] else None,
        )


class TaskRepository:
    """Repository for task operations."""
    
    def __init__(self):
        self.db = get_db("tasks")
    
    def create(
        self,
        project: str,
        description: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        metadata: Optional[dict] = None,
    ) -> Task:
        """Create a new task."""
        task = Task(
            id=secrets.token_hex(4),
            project=project,
            description=description,
            priority=priority,
            metadata=metadata,
        )
        
        self.db.execute("""
            INSERT INTO tasks (id, project, description, priority, status, created_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            task.id,
            task.project,
            task.description,
            task.priority.value,
            task.status.value,
            task.created_at.isoformat(),
            json.dumps(task.metadata) if task.metadata else None,
        ))
        self.db.commit()
        return task
    
    def get(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        cursor = self.db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_task(row)
    
    def list(
        self,
        status: Optional[TaskStatus] = None,
        project: Optional[str] = None,
        limit: int = 100,
    ) -> list[Task]:
        """List tasks with optional filters."""
        conditions = []
        params = []
        
        if status:
            conditions.append("status = ?")
            params.append(status.value)
        if project:
            conditions.append("project = ?")
            params.append(project)
        
        where = " AND ".join(conditions) if conditions else "1=1"
        
        cursor = self.db.execute(f"""
            SELECT * FROM tasks
            WHERE {where}
            ORDER BY 
                CASE priority 
                    WHEN 'urgent' THEN 0 
                    WHEN 'high' THEN 1 
                    WHEN 'normal' THEN 2 
                    ELSE 3 
                END,
                created_at
            LIMIT ?
        """, params + [limit])
        
        return [self._row_to_task(row) for row in cursor.fetchall()]
    
    def list_pending(self, limit: int = 10) -> list[Task]:
        """List pending tasks ordered by priority."""
        return self.list(status=TaskStatus.PENDING, limit=limit)
    
    def claim_next(self, assigned_to: str) -> Optional[Task]:
        """Atomically claim the next pending task."""
        cursor = self.db.execute("""
            UPDATE tasks 
            SET status = 'in_progress', 
                assigned_to = ?, 
                started_at = ?
            WHERE id = (
                SELECT id FROM tasks 
                WHERE status = 'pending' 
                ORDER BY 
                    CASE priority 
                        WHEN 'urgent' THEN 0 
                        WHEN 'high' THEN 1 
                        WHEN 'normal' THEN 2 
                        ELSE 3 
                    END,
                    created_at
                LIMIT 1
            )
            RETURNING *
        """, (assigned_to, datetime.now().isoformat()))
        
        row = cursor.fetchone()
        self.db.commit()
        
        if not row:
            return None
        return self._row_to_task(row)
    
    def complete(self, task_id: str, result: Optional[str] = None) -> Optional[Task]:
        """Mark a task as completed."""
        now = datetime.now().isoformat()
        cursor = self.db.execute("""
            UPDATE tasks 
            SET status = 'completed', completed_at = ?, result = ?
            WHERE id = ?
            RETURNING *
        """, (now, result, task_id))
        
        row = cursor.fetchone()
        self.db.commit()
        
        if not row:
            return None
        return self._row_to_task(row)
    
    def fail(self, task_id: str, error: str) -> Optional[Task]:
        """Mark a task as failed."""
        now = datetime.now().isoformat()
        
        # Get current retry count
        task = self.get(task_id)
        if not task:
            return None
        
        new_retry = task.retry_count + 1
        new_status = TaskStatus.FAILED if new_retry >= task.max_retries else TaskStatus.PENDING
        
        cursor = self.db.execute("""
            UPDATE tasks 
            SET status = ?, 
                completed_at = CASE WHEN ? = 'failed' THEN ? ELSE completed_at END,
                error = ?,
                retry_count = ?,
                assigned_to = NULL,
                started_at = NULL
            WHERE id = ?
            RETURNING *
        """, (new_status.value, new_status.value, now, error, new_retry, task_id))
        
        row = cursor.fetchone()
        self.db.commit()
        
        if not row:
            return None
        return self._row_to_task(row)
    
    def cancel(self, task_id: str) -> Optional[Task]:
        """Cancel a task."""
        now = datetime.now().isoformat()
        cursor = self.db.execute("""
            UPDATE tasks 
            SET status = 'cancelled', completed_at = ?
            WHERE id = ? AND status IN ('pending', 'blocked')
            RETURNING *
        """, (now, task_id))
        
        row = cursor.fetchone()
        self.db.commit()
        
        if not row:
            return None
        return self._row_to_task(row)
    
    def stats(self) -> dict:
        """Get task statistics."""
        cursor = self.db.execute("""
            SELECT 
                status,
                COUNT(*) as count
            FROM tasks
            GROUP BY status
        """)
        
        stats = {s.value: 0 for s in TaskStatus}
        for row in cursor.fetchall():
            stats[row["status"]] = row["count"]
        
        stats["total"] = sum(stats.values())
        return stats
    
    def _row_to_task(self, row) -> Task:
        return Task(
            id=row["id"],
            project=row["project"],
            description=row["description"],
            priority=TaskPriority(row["priority"]),
            status=TaskStatus(row["status"]),
            assigned_to=row["assigned_to"],
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            result=row["result"],
            error=row["error"],
            retry_count=row["retry_count"],
            max_retries=row["max_retries"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else None,
        )


class AgentRunRepository:
    """Repository for agent run history."""
    
    def __init__(self):
        self.db = get_db("logs")
    
    def create(self, run: AgentRun) -> AgentRun:
        """Create a new agent run record."""
        cursor = self.db.execute("""
            INSERT INTO agent_runs (project, provider, task, task_id, pid, started_at, status, log_file)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run.project,
            run.provider,
            run.task,
            run.task_id,
            run.pid,
            run.started_at.isoformat(),
            run.status.value,
            run.log_file,
        ))
        run.id = cursor.lastrowid
        self.db.commit()
        return run
    
    def update(self, run: AgentRun) -> AgentRun:
        """Update an agent run."""
        self.db.execute("""
            UPDATE agent_runs 
            SET ended_at = ?, exit_code = ?, status = ?, error = ?
            WHERE id = ?
        """, (
            run.ended_at.isoformat() if run.ended_at else None,
            run.exit_code,
            run.status.value,
            run.error,
            run.id,
        ))
        self.db.commit()
        return run
    
    def get(self, run_id: int) -> Optional[AgentRun]:
        """Get a run by ID."""
        cursor = self.db.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_run(row)
    
    def get_active(self, project: str) -> Optional[AgentRun]:
        """Get the active run for a project."""
        cursor = self.db.execute("""
            SELECT * FROM agent_runs 
            WHERE project = ? AND status = 'running'
            ORDER BY started_at DESC
            LIMIT 1
        """, (project,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_run(row)
    
    def list(
        self,
        project: Optional[str] = None,
        status: Optional[AgentRunStatus] = None,
        limit: int = 50,
    ) -> list[AgentRun]:
        """List agent runs."""
        conditions = []
        params = []
        
        if project:
            conditions.append("project = ?")
            params.append(project)
        if status:
            conditions.append("status = ?")
            params.append(status.value)
        
        where = " AND ".join(conditions) if conditions else "1=1"
        
        cursor = self.db.execute(f"""
            SELECT * FROM agent_runs
            WHERE {where}
            ORDER BY started_at DESC
            LIMIT ?
        """, params + [limit])
        
        return [self._row_to_run(row) for row in cursor.fetchall()]
    
    def _row_to_run(self, row) -> AgentRun:
        return AgentRun(
            id=row["id"],
            project=row["project"],
            provider=row["provider"],
            task=row["task"],
            task_id=row["task_id"],
            pid=row["pid"],
            started_at=datetime.fromisoformat(row["started_at"]),
            ended_at=datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None,
            exit_code=row["exit_code"],
            status=AgentRunStatus(row["status"]),
            error=row["error"],
            log_file=row["log_file"],
        )


class EventRepository:
    """Repository for event logging."""
    
    def __init__(self):
        self.db = get_db("logs")
    
    def log(
        self,
        event_type: str,
        project: Optional[str] = None,
        agent: Optional[str] = None,
        task_id: Optional[str] = None,
        level: EventLevel = EventLevel.INFO,
        message: Optional[str] = None,
        data: Optional[dict] = None,
    ) -> Event:
        """Log an event."""
        event = Event(
            type=event_type,
            project=project,
            agent=agent,
            task_id=task_id,
            level=level,
            message=message,
            data=data,
        )
        
        cursor = self.db.execute("""
            INSERT INTO events (timestamp, type, project, agent, task_id, level, message, data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event.timestamp.isoformat(),
            event.type,
            event.project,
            event.agent,
            event.task_id,
            event.level.value,
            event.message,
            json.dumps(event.data) if event.data else None,
        ))
        event.id = cursor.lastrowid
        self.db.commit()
        return event
    
    def query(
        self,
        event_type: Optional[str] = None,
        project: Optional[str] = None,
        level: Optional[EventLevel] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[Event]:
        """Query events."""
        conditions = []
        params = []
        
        if event_type:
            conditions.append("type = ?")
            params.append(event_type)
        if project:
            conditions.append("project = ?")
            params.append(project)
        if level:
            conditions.append("level = ?")
            params.append(level.value)
        if since:
            conditions.append("timestamp >= ?")
            params.append(since.isoformat())
        
        where = " AND ".join(conditions) if conditions else "1=1"
        
        cursor = self.db.execute(f"""
            SELECT * FROM events
            WHERE {where}
            ORDER BY timestamp DESC
            LIMIT ?
        """, params + [limit])
        
        return [self._row_to_event(row) for row in cursor.fetchall()]
    
    def _row_to_event(self, row) -> Event:
        return Event(
            id=row["id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            type=row["type"],
            project=row["project"],
            agent=row["agent"],
            task_id=row["task_id"],
            level=EventLevel(row["level"]),
            message=row["message"],
            data=json.loads(row["data"]) if row["data"] else None,
        )
