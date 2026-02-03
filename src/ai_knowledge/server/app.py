"""FastAPI server for ADT Command Center."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel

from .dashboard import DASHBOARD_HTML

from .config import Config, ensure_adt_home
from .agents import AgentManager, AgentStatus
from .queue import TaskQueue, TaskPriority, TaskStatus
from .events import EventBus, Event, get_event_bus
from .events.bus import EventType
from .vault import get_secret
from .auth import get_auth_manager, TokenInfo, Role
from .audit import audit, AuditAction, get_audit_logger
from .middleware import AuthMiddleware
from .db import init_databases, close_databases, TaskRepository, EventRepository
from .orchestrator import Orchestrator, set_orchestrator


# Pydantic models for API
class SpawnRequest(BaseModel):
    project: str
    provider: str | None = None
    task: str | None = None
    worktree: str | None = None


class TaskRequest(BaseModel):
    project: str
    description: str
    priority: str = "normal"
    requires_review: bool = False  # If true, task goes to awaiting_review first
    review_prompt: str | None = None  # What to show reviewer


class AssignRequest(BaseModel):
    task: str


# Global state
config: Config | None = None
agent_manager: AgentManager | None = None
task_queue: TaskQueue | None = None
task_repo: TaskRepository | None = None
event_repo: EventRepository | None = None
event_bus: EventBus | None = None
orchestrator: Orchestrator | None = None
process_manager = None
telegram_bot = None
auth_manager = None
connected_clients: set[WebSocket] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    global config, agent_manager, task_queue, task_repo, event_repo, event_bus, orchestrator, process_manager, telegram_bot, auth_manager
    
    ensure_adt_home()
    
    # Initialize SQLite databases
    init_databases()
    task_repo = TaskRepository()
    event_repo = EventRepository()
    
    config = Config.load()
    agent_manager = AgentManager(config)
    task_queue = TaskQueue()  # Keep for backward compat, will migrate
    event_bus = get_event_bus()
    auth_manager = get_auth_manager()
    
    # Initialize process manager
    from .processes import get_process_manager
    process_manager = get_process_manager()
    
    # Register process event handlers for real-time updates
    def on_process_event(event_name: str):
        def handler(process_id: str, *args):
            # Broadcast to WebSocket clients
            import asyncio
            state = process_manager.get(process_id)
            if state:
                msg = {
                    "type": f"process.{event_name}",
                    "process_id": process_id,
                    "project": state.project,
                    "status": state.status.value,
                    "error": state.error,
                }
                for client in connected_clients:
                    try:
                        asyncio.create_task(client.send_json(msg))
                    except Exception:
                        pass
        return handler
    
    process_manager.on("started", on_process_event("started"))
    process_manager.on("stopped", on_process_event("stopped"))
    process_manager.on("exited", on_process_event("exited"))
    
    # Initialize orchestrator
    orchestrator = Orchestrator(
        config=config,
        agent_manager=agent_manager,
        task_repo=task_repo,
        event_repo=event_repo,
    )
    set_orchestrator(orchestrator)
    
    # Create initial admin token if none exist
    if not auth_manager.has_any_tokens():
        token, info = auth_manager.create_initial_admin_token()
        print("\n" + "=" * 60)
        print("INITIAL ADMIN TOKEN CREATED")
        print("=" * 60)
        print(f"Token: {token}")
        print("\nSave this token! It will not be shown again.")
        print("Use it to authenticate API requests:")
        print(f"  curl -H 'Authorization: Bearer {token}' http://...")
        print("=" * 60 + "\n")
        
        audit(
            AuditAction.AUTH_TOKEN_CREATED,
            actor_type="system",
            resource_type="token",
            resource_id=info.id,
            metadata={"name": info.name, "role": info.role.value},
        )
    
    # Subscribe to events to broadcast to WebSocket clients
    @event_bus.subscribe()
    async def broadcast_event(event: Event):
        if connected_clients:
            message = event.to_json()
            dead_clients = set()
            for client in connected_clients:
                try:
                    await client.send_text(message)
                except Exception:
                    dead_clients.add(client)
            connected_clients.difference_update(dead_clients)
    
    # Start Telegram bot if configured
    if config.channels.telegram.enabled:
        token = get_secret("TELEGRAM_BOT_TOKEN") or config.channels.telegram.token
        if token:
            from .channels.telegram import TelegramBot
            
            telegram_bot = TelegramBot(
                token=token,
                allowed_users=config.channels.telegram.allowed_users or None,
                on_command=handle_telegram_command,
            )
            await telegram_bot.start()
    
    # Start the orchestrator (auto-assigns tasks to agents)
    if config.agents.auto_spawn:
        await orchestrator.start()
    
    # Emit server started event
    event_bus.emit(EventType.SERVER_STARTED)
    
    yield
    
    # Cleanup
    if orchestrator:
        await orchestrator.stop()
    if telegram_bot:
        await telegram_bot.stop()
    if process_manager:
        process_manager.stop_all()
    event_bus.emit(EventType.SERVER_STOPPED)
    close_databases()


async def handle_telegram_command(command: str, args: str, user_id: int) -> str:
    """Handle commands from Telegram."""
    try:
        if command == "status":
            agents = agent_manager.list() if agent_manager else []
            running = len([a for a in agents if a.status not in (AgentStatus.STOPPED, AgentStatus.ERROR)])
            stats = task_queue.stats() if task_queue else {}
            
            return (
                f"📊 Status\n\n"
                f"Agents: {running} running / {len(agents)} total\n"
                f"Tasks: {stats.get('pending', 0)} pending, {stats.get('in_progress', 0)} in progress\n"
                f"Clients: {len(connected_clients)} connected"
            )
        
        elif command == "agents":
            agents = agent_manager.list() if agent_manager else []
            if not agents:
                return "No agents found."
            
            lines = ["🤖 Agents:\n"]
            for a in agents:
                status_icon = {"working": "🟢", "idle": "⚪", "error": "🔴", "stopped": "⬛"}.get(a.status.value, "⚪")
                lines.append(f"{status_icon} {a.project} ({a.status.value})")
                if a.current_task:
                    lines.append(f"   └ {a.current_task[:50]}")
            return "\n".join(lines)
        
        elif command == "tasks":
            tasks = task_queue.list() if task_queue else []
            if not tasks:
                return "No pending tasks."
            
            lines = ["📋 Tasks:\n"]
            for t in tasks[:10]:
                priority_icon = {"urgent": "🔴", "high": "🟠", "normal": "🔵", "low": "⚪"}.get(t.priority.value, "⚪")
                lines.append(f"{priority_icon} [{t.id}] {t.project}: {t.description[:40]}")
            return "\n".join(lines)
        
        elif command == "projects":
            from ..store import load_config as load_adt_config
            adt_config = load_adt_config()
            
            if not adt_config.projects:
                return "No projects registered."
            
            lines = ["📁 Projects:\n"]
            for p in adt_config.projects:
                lines.append(f"• {p.name}")
            return "\n".join(lines)
        
        elif command == "spawn":
            parts = args.split(maxsplit=1)
            project = parts[0] if parts else ""
            task = parts[1] if len(parts) > 1 else None
            
            if not project:
                return "Usage: /spawn <project> [task]"
            
            try:
                state = agent_manager.spawn(project, task=task)
                return f"✅ Spawned agent for {project}\nPID: {state.pid}"
            except Exception as e:
                return f"❌ Error: {e}"
        
        elif command == "stop":
            if not args:
                return "Usage: /stop <project>"
            
            if agent_manager.stop(args):
                return f"✅ Stopped agent for {args}"
            else:
                return f"❌ Agent not found: {args}"
        
        elif command == "add_task":
            parts = args.split(maxsplit=1)
            project = parts[0] if parts else ""
            description = parts[1] if len(parts) > 1 else ""
            
            if not project or not description:
                return "Usage: /add <project> <task description>"
            
            task = task_queue.create(project=project, description=description)
            return f"✅ Created task {task.id}"
        
        elif command == "message":
            # Natural language - try to interpret
            text = args.lower()
            
            if "status" in text:
                return await handle_telegram_command("status", "", user_id)
            elif "agents" in text or "agent" in text:
                return await handle_telegram_command("agents", "", user_id)
            elif "tasks" in text or "task" in text or "queue" in text:
                return await handle_telegram_command("tasks", "", user_id)
            else:
                return (
                    "I didn't understand that. Try:\n"
                    "/status - System status\n"
                    "/agents - List agents\n"
                    "/tasks - List tasks\n"
                    "/spawn <project> - Start agent\n"
                    "/add <project> <task> - Add task"
                )
        
        else:
            return f"Unknown command: {command}"
    
    except Exception as e:
        return f"❌ Error: {e}"


app = FastAPI(
    title="ADT Command Center",
    description="Agent orchestration and task management",
    version="0.1.0",
    lifespan=lifespan,
)

# Auth middleware (can be disabled via config)
# Set auth_enabled=False for development without tokens
app.add_middleware(AuthMiddleware, auth_enabled=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Health & Status
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the web dashboard."""
    return DASHBOARD_HTML


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/status")
async def status():
    """Get overall system status."""
    agents = agent_manager.list() if agent_manager else []
    queue_stats = task_queue.stats() if task_queue else {}
    
    return {
        "agents": {
            "total": len(agents),
            "running": len([a for a in agents if a.status not in (AgentStatus.STOPPED, AgentStatus.ERROR)]),
            "agents": [
                {
                    "project": a.project,
                    "status": a.status.value,
                    "provider": a.provider,
                    "task": a.current_task,
                }
                for a in agents
            ],
        },
        "queue": queue_stats,
        "connected_clients": len(connected_clients),
    }


# =============================================================================
# Agent Management
# =============================================================================

@app.get("/agents")
async def list_agents():
    """List all agents."""
    agents = agent_manager.list() if agent_manager else []
    return [
        {
            "project": a.project,
            "status": a.status.value,
            "provider": a.provider,
            "pid": a.pid,
            "task": a.current_task,
            "worktree": a.worktree,
            "started_at": a.started_at.isoformat() if a.started_at else None,
            "last_activity": a.last_activity.isoformat() if a.last_activity else None,
            "error": a.error,
        }
        for a in agents
    ]


@app.post("/agents/spawn")
async def spawn_agent(req: SpawnRequest, request: Request):
    """Spawn a new agent."""
    token_info = getattr(request.state, "token_info", None)
    
    try:
        state = agent_manager.spawn(
            project=req.project,
            provider=req.provider,
            task=req.task,
            worktree=req.worktree,
        )
        
        audit(
            AuditAction.AGENT_SPAWN,
            actor_type="user" if token_info else "system",
            actor_id=token_info.id if token_info else None,
            resource_type="agent",
            resource_id=req.project,
            channel="api",
            metadata={"provider": state.provider, "task": req.task[:100] if req.task else None},
        )
        
        event_bus.emit(
            EventType.AGENT_SPAWNED,
            project=req.project,
            provider=state.provider,
            pid=state.pid,
        )
        
        return {
            "success": True,
            "agent": {
                "project": state.project,
                "status": state.status.value,
                "provider": state.provider,
                "pid": state.pid,
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/agents/{project}/stop")
async def stop_agent(project: str, force: bool = False):
    """Stop an agent."""
    success = agent_manager.stop(project, force=force)
    
    if success:
        event_bus.emit(EventType.AGENT_STOPPED, project=project)
        return {"success": True}
    else:
        raise HTTPException(status_code=404, detail=f"Agent not found: {project}")


class RetryRequest(BaseModel):
    task: str | None = None  # Optional new task, otherwise retry with same


@app.post("/agents/{project}/retry")
async def retry_agent(project: str, request: Request, body: RetryRequest | None = None):
    """Retry a failed agent with optional new task."""
    agent = agent_manager.get(project)
    
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent not found: {project}")
    
    # Allow retry from error or stopped state
    if agent.status not in (AgentStatus.ERROR, AgentStatus.STOPPED):
        raise HTTPException(status_code=400, detail=f"Agent cannot be retried from state: {agent.status}")
    
    # Get task - use new one if provided, otherwise use the previous task
    task = None
    if body and body.task:
        task = body.task
    elif agent.current_task:
        task = agent.current_task
    
    try:
        # Stop first to clean up
        agent_manager.stop(project, force=True)
        
        # Respawn with task
        state = agent_manager.spawn(project, task=task)
        
        # Log to SQLite
        event_repo.log(
            "agent.retry",
            project=project,
            message=f"Agent retried with task: {task[:50] if task else 'none'}",
        )
        
        event_bus.emit(EventType.AGENT_STARTED, project=project, task=task)
        
        token_info = getattr(request.state, "token_info", None)
        audit(
            AuditAction.AGENT_RETRY,
            actor_type="user" if token_info else "system",
            actor_id=token_info.id if token_info else None,
            resource_type="agent",
            resource_id=project,
            channel="api",
        )
        
        return {
            "success": True,
            "agent": {
                "project": state.project,
                "status": state.status.value,
                "pid": state.pid,
                "task": state.current_task,
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/agents/{project}")
async def get_agent(project: str):
    """Get agent status."""
    agent = agent_manager.get(project)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent not found: {project}")
    
    return {
        "project": agent.project,
        "status": agent.status.value,
        "provider": agent.provider,
        "pid": agent.pid,
        "task": agent.current_task,
        "worktree": agent.worktree,
        "started_at": agent.started_at.isoformat() if agent.started_at else None,
        "last_activity": agent.last_activity.isoformat() if agent.last_activity else None,
        "error": agent.error,
        "retry_count": agent.retry_count,
    }


@app.get("/agents/{project}/logs")
async def get_agent_logs(project: str, lines: int = 100):
    """Get agent logs."""
    logs = agent_manager.get_logs(project, lines=lines)
    return {"project": project, "logs": logs}


@app.post("/agents/{project}/assign")
async def assign_to_agent(project: str, req: AssignRequest):
    """Assign a task to an agent."""
    try:
        state = agent_manager.assign_task(project, req.task)
        
        event_bus.emit(
            EventType.TASK_ASSIGNED,
            project=project,
            task=req.task,
        )
        
        return {
            "success": True,
            "agent": {
                "project": state.project,
                "status": state.status.value,
                "task": state.current_task,
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =============================================================================
# Task Queue
# =============================================================================

@app.get("/tasks")
async def list_tasks(
    project: str | None = None,
    status: str | None = None,
    include_completed: bool = True,
):
    """List tasks in the queue."""
    from .db.models import TaskStatus as DBTaskStatus
    
    status_filter = None
    if status:
        try:
            status_filter = DBTaskStatus(status)
        except ValueError:
            pass
    
    # Use SQLite repository
    tasks = task_repo.list(status=status_filter, project=project, limit=100)
    
    # Filter out cancelled unless requested
    tasks = [t for t in tasks if t.status != DBTaskStatus.CANCELLED]
    
    return [
        {
            "id": t.id,
            "project": t.project,
            "description": t.description,
            "priority": t.priority.value,
            "status": t.status.value,
            "assigned_to": t.assigned_to,
            "created_at": t.created_at.isoformat(),
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            "result": t.result,
            "error": t.error,
        }
        for t in tasks
    ]


@app.post("/tasks")
async def create_task(req: TaskRequest, request: Request):
    """Create a new task."""
    from .db.models import TaskPriority as DBTaskPriority, TaskStatus as DBTaskStatus
    
    try:
        priority = DBTaskPriority(req.priority)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid priority: {req.priority}")
    
    # Use SQLite repository
    task = task_repo.create(
        project=req.project,
        description=req.description,
        priority=priority,
    )
    
    # If requires review, update status
    if req.requires_review:
        task_repo.db.execute("""
            UPDATE tasks SET status = 'awaiting_review', review_prompt = ? WHERE id = ?
        """, (req.review_prompt or req.description, task.id))
        task_repo.db.commit()
        task.status = DBTaskStatus.AWAITING_REVIEW
    
    # Log event to SQLite
    event_repo.log(
        "task.created",
        project=req.project,
        task_id=task.id,
        message=f"Task created{' (requires review)' if req.requires_review else ''}: {req.description[:50]}",
    )
    
    event_bus.emit(
        EventType.TASK_CREATED,
        project=req.project,
        task_id=task.id,
        description=req.description,
    )
    
    token_info = getattr(request.state, "token_info", None)
    audit(
        AuditAction.TASK_CREATED,
        actor_type="user" if token_info else "system",
        actor_id=token_info.id if token_info else None,
        resource_type="task",
        resource_id=task.id,
        channel="api",
        metadata={"project": req.project, "priority": req.priority},
    )
    
    return {
        "success": True,
        "task": {
            "id": task.id,
            "project": task.project,
            "description": task.description,
            "priority": task.priority.value,
            "status": task.status.value,
        },
    }


@app.get("/tasks/pending-review")
async def get_pending_review():
    """Get all tasks awaiting human review."""
    from .db.models import TaskStatus as DBTaskStatus
    
    tasks = task_repo.list(status=DBTaskStatus.AWAITING_REVIEW, limit=50)
    
    return [
        {
            "id": t.id,
            "project": t.project,
            "description": t.description,
            "priority": t.priority.value,
            "review_prompt": getattr(t, 'review_prompt', None),
            "created_at": t.created_at.isoformat(),
        }
        for t in tasks
    ]


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Get a task by ID."""
    task = task_repo.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    
    return {
        "id": task.id,
        "project": task.project,
        "description": task.description,
        "priority": task.priority.value,
        "status": task.status.value,
        "assigned_to": task.assigned_to,
        "created_at": task.created_at.isoformat(),
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "result": task.result,
        "error": task.error,
        "retry_count": task.retry_count,
    }


@app.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, request: Request):
    """Cancel a task."""
    task = task_repo.cancel(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found or cannot be cancelled: {task_id}")
    
    event_repo.log(
        "task.cancelled",
        project=task.project,
        task_id=task.id,
        message="Task cancelled",
    )
    
    token_info = getattr(request.state, "token_info", None)
    audit(
        AuditAction.TASK_CANCELLED,
        actor_type="user" if token_info else "system",
        actor_id=token_info.id if token_info else None,
        resource_type="task",
        resource_id=task_id,
        channel="api",
    )
    
    return {"success": True, "task_id": task_id}


class TaskRetryRequest(BaseModel):
    description: str | None = None  # Optional new description
    priority: str | None = None  # Optional new priority


class ChainedTaskRequest(BaseModel):
    project: str
    description: str
    priority: str = "normal"
    depends_on: list[str] | None = None  # Task IDs to wait for
    use_output_from: str | None = None  # Task ID whose output to inject as {{output}}


@app.post("/tasks/chain")
async def create_chained_task(req: ChainedTaskRequest, request: Request):
    """Create a task that depends on other tasks.
    
    The description can include {{output}} which will be replaced with
    the output from the use_output_from task when it runs.
    """
    from .db.models import TaskPriority as DBTaskPriority
    
    try:
        priority = DBTaskPriority(req.priority)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid priority: {req.priority}")
    
    # Build dependencies list
    depends_on = req.depends_on or []
    if req.use_output_from and req.use_output_from not in depends_on:
        depends_on.append(req.use_output_from)
    
    # If using output from another task, check if it's complete and substitute
    description = req.description
    if req.use_output_from:
        source_task = task_repo.get(req.use_output_from)
        if source_task and source_task.status.value == "completed" and source_task.output:
            # Substitute output into description
            description = description.replace("{{output}}", source_task.output)
    
    task = task_repo.create(
        project=req.project,
        description=description,
        priority=priority,
        depends_on=depends_on if depends_on else None,
        metadata={"use_output_from": req.use_output_from} if req.use_output_from else None,
    )
    
    event_bus.emit(
        EventType.TASK_CREATED,
        project=req.project,
        task_id=task.id,
    )
    
    return {
        "success": True,
        "task": {
            "id": task.id,
            "project": task.project,
            "description": task.description,
            "priority": task.priority.value,
            "status": task.status.value,
            "depends_on": task.depends_on,
        },
    }


@app.get("/tasks/{task_id}/output")
async def get_task_output(task_id: str):
    """Get the captured output from a completed task."""
    task = task_repo.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    
    return {
        "task_id": task_id,
        "status": task.status.value,
        "output": task.output,
        "output_artifacts": task.output_artifacts,
    }


class ReviewDecision(BaseModel):
    approved: bool
    comment: str | None = None
    modified_description: str | None = None  # Allow reviewer to edit task


@app.post("/tasks/{task_id}/review")
async def review_task(task_id: str, decision: ReviewDecision, request: Request):
    """Approve or reject a task awaiting review."""
    from .db.models import TaskStatus as DBTaskStatus
    
    task = task_repo.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    
    if task.status != DBTaskStatus.AWAITING_REVIEW:
        raise HTTPException(status_code=400, detail=f"Task is not awaiting review: {task.status}")
    
    token_info = getattr(request.state, "token_info", None)
    reviewer_id = token_info.id if token_info else "anonymous"
    
    if decision.approved:
        # Update description if modified
        description = decision.modified_description or task.description
        
        # Mark as pending so orchestrator picks it up
        task_repo.db.execute("""
            UPDATE tasks 
            SET status = 'pending', 
                description = ?,
                reviewed_by = ?,
                reviewed_at = ?
            WHERE id = ?
        """, (description, reviewer_id, datetime.now().isoformat(), task_id))
        task_repo.db.commit()
        
        event_repo.log(
            "task.approved",
            project=task.project,
            task_id=task_id,
            message=f"Approved by {reviewer_id}",
        )
        
        return {"success": True, "action": "approved", "task_id": task_id}
    else:
        # Rejected - cancel the task
        task_repo.cancel(task_id)
        
        event_repo.log(
            "task.rejected",
            project=task.project,
            task_id=task_id,
            message=f"Rejected by {reviewer_id}: {decision.comment or 'no reason'}",
        )
        
        return {"success": True, "action": "rejected", "task_id": task_id}


@app.post("/tasks/{task_id}/retry")
async def retry_task(task_id: str, request: Request, body: TaskRetryRequest | None = None):
    """Retry a failed task (creates a new task with same or updated params)."""
    from .db.models import TaskPriority as DBTaskPriority
    
    original = task_repo.get(task_id)
    if not original:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    
    # Use provided values or fall back to original
    description = body.description if body and body.description else original.description
    priority = original.priority
    if body and body.priority:
        try:
            priority = DBTaskPriority(body.priority)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid priority: {body.priority}")
    
    # Create new task
    new_task = task_repo.create(
        project=original.project,
        description=description,
        priority=priority,
        metadata={"retried_from": task_id},
    )
    
    event_repo.log(
        "task.retried",
        project=original.project,
        task_id=new_task.id,
        message=f"Retried from {task_id}",
    )
    
    event_bus.emit(
        EventType.TASK_CREATED,
        project=original.project,
        task_id=new_task.id,
        description=description,
    )
    
    return {
        "success": True,
        "original_task_id": task_id,
        "new_task": {
            "id": new_task.id,
            "project": new_task.project,
            "description": new_task.description,
            "priority": new_task.priority.value,
            "status": new_task.status.value,
        },
    }


@app.post("/tasks/{task_id}/run")
async def run_task_now(task_id: str, request: Request):
    """Immediately run a pending task by spawning an agent."""
    task = task_repo.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    
    if task.status != TaskStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Task is not pending: {task.status}")
    
    # Claim the task
    claimed = task_repo.claim_next(task.project)
    if not claimed or claimed.id != task_id:
        raise HTTPException(status_code=409, detail="Task was claimed by another process")
    
    try:
        # Spawn agent
        state = agent_manager.spawn(
            project=task.project,
            task=task.description,
        )
        
        event_repo.log(
            "task.started",
            project=task.project,
            task_id=task_id,
            message=f"Agent spawned: {task.description[:50]}",
        )
        
        return {
            "success": True,
            "task_id": task_id,
            "agent": {
                "project": state.project,
                "status": state.status.value,
                "pid": state.pid,
            },
        }
    except Exception as e:
        # Mark task as failed
        task_repo.fail(task_id, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tasks/stats")
async def task_stats():
    """Get queue statistics."""
    return task_repo.stats()


# =============================================================================
# Process Management (Dev Servers, etc.)
# =============================================================================

class ProcessRegisterRequest(BaseModel):
    project: str
    name: str
    command: str
    cwd: str
    port: int | None = None


@app.get("/processes")
async def list_processes(project: str | None = None):
    """List all managed processes."""
    processes = process_manager.list(project=project)
    return [
        {
            "id": p.id,
            "project": p.project,
            "name": p.name,
            "type": p.process_type.value,
            "command": p.command,
            "status": p.status.value,
            "pid": p.pid,
            "port": p.port,
            "started_at": p.started_at.isoformat() if p.started_at else None,
            "error": p.error,
        }
        for p in processes
    ]


@app.post("/processes/register")
async def register_process(req: ProcessRegisterRequest):
    """Register a new process configuration."""
    state = process_manager.register(
        project=req.project,
        name=req.name,
        command=req.command,
        cwd=req.cwd,
        port=req.port,
    )
    return {"success": True, "process": {"id": state.id, "status": state.status.value}}


@app.post("/processes/{process_id}/start")
async def start_process(process_id: str):
    """Start a registered process."""
    try:
        state = process_manager.start(process_id)
        event_repo.log(
            "process.started",
            project=state.project,
            message=f"Started {state.name}: {state.command}",
        )
        return {
            "success": True,
            "process": {
                "id": state.id,
                "status": state.status.value,
                "pid": state.pid,
                "port": state.port,
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/processes/{process_id}/stop")
async def stop_process(process_id: str, force: bool = False):
    """Stop a running process."""
    try:
        state = process_manager.stop(process_id, force=force)
        event_repo.log(
            "process.stopped",
            project=state.project,
            message=f"Stopped {state.name}",
        )
        return {"success": True, "process": {"id": state.id, "status": state.status.value}}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/processes/{process_id}/restart")
async def restart_process(process_id: str):
    """Restart a process."""
    try:
        state = process_manager.restart(process_id)
        event_repo.log(
            "process.restarted",
            project=state.project,
            message=f"Restarted {state.name}",
        )
        return {
            "success": True,
            "process": {
                "id": state.id,
                "status": state.status.value,
                "pid": state.pid,
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/processes/{process_id}/logs")
async def get_process_logs(process_id: str, lines: int = 100):
    """Get logs for a process."""
    state = process_manager.get(process_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Process not found: {process_id}")
    
    logs = process_manager.get_logs(process_id, lines=lines)
    return {"process_id": process_id, "logs": logs}


@app.post("/processes/{process_id}/create-fix-task")
async def create_fix_task_from_process(process_id: str):
    """Create a task to fix a failed process error."""
    from .db.models import TaskPriority as DBTaskPriority
    
    state = process_manager.get(process_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Process not found: {process_id}")
    
    if state.status.value != "failed":
        raise HTTPException(status_code=400, detail="Process is not in failed state")
    
    # Get error details
    error_msg = state.error or "Unknown error"
    logs = process_manager.get_logs(process_id, lines=50)
    
    # Create task description
    description = f"""Fix the {state.name} process error for {state.project}.

Command that failed: {state.command}

Error:
{error_msg}

Recent logs:
{logs[-2000:] if len(logs) > 2000 else logs}
"""
    
    task = task_repo.create(
        project=state.project,
        description=description,
        priority=DBTaskPriority.HIGH,
        metadata={"source": "process_error", "process_id": process_id},
    )
    
    event_repo.log(
        "task.created_from_error",
        project=state.project,
        task_id=task.id,
        message=f"Created fix task from failed process: {state.name}",
    )
    
    return {
        "success": True,
        "task": {
            "id": task.id,
            "project": task.project,
            "description": task.description[:100] + "...",
            "priority": task.priority.value,
        },
    }


@app.post("/projects/{project}/detect-processes")
async def detect_project_processes(project: str, use_llm: bool = True):
    """Auto-detect and register dev processes for a project.
    
    Uses LLM (Ollama) to intelligently discover all runnable processes
    from package.json, pyproject.toml, etc.
    """
    from ..store import load_config as load_adt_config
    from .process_discovery import discover_processes
    from .ports import get_port_manager
    
    adt_config = load_adt_config()
    proj = next((p for p in adt_config.projects if p.name == project), None)
    if not proj:
        raise HTTPException(status_code=404, detail=f"Project not found: {project}")
    
    project_path = str(proj.path)
    port_manager = get_port_manager()
    
    # Discover processes using LLM or heuristics
    discovered = discover_processes(project, project_path, use_llm=use_llm)
    
    registered = []
    for proc in discovered:
        # Determine the working directory
        if proc.cwd:
            cwd = str(Path(project_path) / proc.cwd)
        else:
            cwd = project_path
        
        # Assign port if this is a server
        port = None
        if proc.default_port:
            port = port_manager.assign_port(project, proc.name, preferred=proc.default_port)
            # Adjust command with assigned port
            cmd = process_manager._adjust_command_port(proc.command, port)
        else:
            cmd = proc.command
        
        # Register the process
        state = process_manager.register(
            project=project,
            name=proc.name,
            command=cmd,
            cwd=cwd,
            port=port,
            force_update=True,
        )
        registered.append({
            "id": state.id,
            "name": proc.name,
            "command": cmd,
            "port": port,
            "description": proc.description,
        })
    
    return {
        "success": True,
        "detected": registered,
        "method": "llm" if use_llm and registered else "heuristics",
    }


# =============================================================================
# Port Management
# =============================================================================

@app.get("/ports")
async def list_ports(project: str | None = None):
    """List all port assignments."""
    from .ports import get_port_manager
    
    pm = get_port_manager()
    assignments = pm.list_assignments(project=project)
    
    return [
        {
            "project": a.project,
            "service": a.service,
            "port": a.port,
            "in_use": a.in_use,
        }
        for a in assignments
    ]


class PortAssignRequest(BaseModel):
    project: str
    service: str
    port: int | None = None  # If None, auto-assign
    force_new: bool = False  # Force finding a new port (for conflict resolution)


@app.post("/ports/assign")
async def assign_port(req: PortAssignRequest):
    """Assign a port to a project service."""
    from .ports import get_port_manager
    
    pm = get_port_manager()
    
    try:
        port = pm.assign_port(req.project, req.service, preferred=req.port, force_new=req.force_new)
        
        # Also update the process command if exists
        process_id = f"{req.project}-{req.service}"
        if process_id in state.process_manager._processes:
            proc_state = state.process_manager._processes[process_id]
            old_port = proc_state.port
            if old_port != port:
                proc_state.port = port
                # Update command with new port
                from .processes import ProcessManager
                proc_state.command = state.process_manager._update_command_port(proc_state.command, port)
                state.process_manager._save_state()
        
        return {"success": True, "project": req.project, "service": req.service, "port": port}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/ports/set")
async def set_port(req: PortAssignRequest):
    """Explicitly set a port for a service."""
    from .ports import get_port_manager
    
    if not req.port:
        raise HTTPException(status_code=400, detail="Port is required")
    
    pm = get_port_manager()
    success = pm.set_port(req.project, req.service, req.port)
    
    if not success:
        raise HTTPException(status_code=400, detail=f"Port {req.port} is not available")
    
    return {"success": True, "project": req.project, "service": req.service, "port": req.port}


@app.delete("/ports/{project}/{service}")
async def release_port(project: str, service: str):
    """Release a port assignment."""
    from .ports import get_port_manager
    
    pm = get_port_manager()
    pm.release_port(project, service)
    
    return {"success": True, "released": f"{project}:{service}"}


# =============================================================================
# WebSocket for Real-time Updates
# =============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    from .streaming import get_stream_manager
    
    await websocket.accept()
    connected_clients.add(websocket)
    
    # Track subscriptions for cleanup
    stream_subscriptions: list[tuple[str, callable]] = []
    
    async def on_agent_output(project: str, content: str):
        """Send agent output to this client."""
        try:
            await websocket.send_json({
                "type": "agent.output",
                "project": project,
                "content": content,
            })
        except Exception:
            pass
    
    try:
        # Send current state on connect
        await websocket.send_json({
            "type": "connected",
            "data": {
                "agents": len(agent_manager.list()) if agent_manager else 0,
                "tasks": task_queue.stats() if task_queue else {},
            },
        })
        
        stream_manager = get_stream_manager()
        
        # Keep connection alive and handle incoming messages
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                message = json.loads(data)
                
                # Handle client commands via WebSocket
                cmd = message.get("command")
                
                if cmd == "ping":
                    await websocket.send_json({"type": "pong"})
                
                elif cmd == "status":
                    await websocket.send_json({
                        "type": "status",
                        "data": await status(),
                    })
                
                elif cmd == "spawn":
                    project = message.get("project")
                    task = message.get("task")
                    if project:
                        try:
                            state = agent_manager.spawn(project, task=task)
                            await websocket.send_json({
                                "type": "agent.spawned",
                                "data": {"project": project, "pid": state.pid},
                            })
                        except Exception as e:
                            await websocket.send_json({
                                "type": "error",
                                "data": {"message": str(e)},
                            })
                
                elif cmd == "subscribe":
                    # Subscribe to agent output stream
                    project = message.get("project")
                    if project:
                        await stream_manager.subscribe(project, on_agent_output)
                        stream_subscriptions.append((project, on_agent_output))
                        await websocket.send_json({
                            "type": "subscribed",
                            "project": project,
                        })
                
                elif cmd == "unsubscribe":
                    # Unsubscribe from agent output stream
                    project = message.get("project")
                    if project:
                        await stream_manager.unsubscribe(project, on_agent_output)
                        stream_subscriptions = [(p, c) for p, c in stream_subscriptions if p != project]
                        await websocket.send_json({
                            "type": "unsubscribed",
                            "project": project,
                        })
                
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                await websocket.send_json({"type": "ping"})
                
    except WebSocketDisconnect:
        pass
    finally:
        # Cleanup subscriptions
        stream_manager = get_stream_manager()
        for project, callback in stream_subscriptions:
            await stream_manager.unsubscribe(project, callback)
        connected_clients.discard(websocket)


# =============================================================================
# Projects (from adt registry)
# =============================================================================

@app.get("/projects")
async def list_projects():
    """List registered projects."""
    from ..store import load_config as load_adt_config
    
    adt_config = load_adt_config()
    return [
        {
            "name": p.name,
            "path": str(p.path),
            "description": p.description,
            "tags": p.tags,
        }
        for p in adt_config.projects
    ]


# =============================================================================
# Events History
# =============================================================================

@app.get("/events")
async def list_events(limit: int = 50, event_type: str | None = None):
    """Get recent events."""
    type_filter = EventType(event_type) if event_type else None
    events = event_bus.get_history(limit=limit, event_type=type_filter)
    
    return [
        {
            "type": e.type.value,
            "timestamp": e.timestamp.isoformat(),
            "project": e.project,
            "data": e.data,
        }
        for e in events
    ]


# Token management endpoints

class CreateTokenRequest(BaseModel):
    name: str
    role: str = "operator"
    expires_in_days: int | None = None


@app.get("/tokens")
async def list_tokens(request: Request):
    """List all API tokens (admin only)."""
    tokens = auth_manager.list_tokens()
    return [
        {
            "id": t.id,
            "name": t.name,
            "role": t.role.value,
            "created_at": t.created_at.isoformat(),
            "expires_at": t.expires_at.isoformat() if t.expires_at else None,
            "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
            "revoked": t.revoked,
        }
        for t in tokens
    ]


@app.post("/tokens")
async def create_token(req: CreateTokenRequest, request: Request):
    """Create a new API token (admin only)."""
    token_info = getattr(request.state, "token_info", None)
    
    try:
        role = Role(req.role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid role: {req.role}")
    
    plain_token, info = auth_manager.create_token(
        name=req.name,
        role=role,
        expires_in_days=req.expires_in_days,
        created_by=token_info.id if token_info else None,
    )
    
    audit(
        AuditAction.AUTH_TOKEN_CREATED,
        actor_type="user" if token_info else "system",
        actor_id=token_info.id if token_info else None,
        resource_type="token",
        resource_id=info.id,
        channel="api",
        metadata={"name": info.name, "role": info.role.value},
    )
    
    return {
        "token": plain_token,
        "id": info.id,
        "name": info.name,
        "role": info.role.value,
        "expires_at": info.expires_at.isoformat() if info.expires_at else None,
    }


@app.delete("/tokens/{token_id}")
async def revoke_token(token_id: str, request: Request):
    """Revoke an API token (admin only)."""
    token_info = getattr(request.state, "token_info", None)
    
    success = auth_manager.revoke_token(token_id)
    if not success:
        raise HTTPException(status_code=404, detail="Token not found")
    
    audit(
        AuditAction.AUTH_TOKEN_REVOKED,
        actor_type="user" if token_info else "system",
        actor_id=token_info.id if token_info else None,
        resource_type="token",
        resource_id=token_id,
        channel="api",
    )
    
    return {"success": True}


# Orchestrator endpoints

@app.get("/orchestrator/status")
async def orchestrator_status():
    """Get orchestrator status and stats."""
    if not orchestrator:
        return {"running": False, "error": "Orchestrator not initialized"}
    return orchestrator.get_stats()


@app.post("/orchestrator/start")
async def orchestrator_start():
    """Start the orchestrator."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")
    
    await orchestrator.start()
    return {"success": True, "message": "Orchestrator started"}


@app.post("/orchestrator/stop")
async def orchestrator_stop():
    """Stop the orchestrator."""
    if not orchestrator:
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")
    
    await orchestrator.stop()
    return {"success": True, "message": "Orchestrator stopped"}


# Audit log endpoint

@app.get("/audit")
async def get_audit_logs(
    request: Request,
    action: str | None = None,
    since: str | None = None,
    limit: int = 100,
):
    """Get audit logs (admin only)."""
    from datetime import datetime
    
    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format")
    
    logger = get_audit_logger()
    entries = logger.query(action=action, since=since_dt, limit=limit)
    
    return [
        {
            "id": e.id,
            "timestamp": e.timestamp.isoformat(),
            "actor_type": e.actor_type,
            "actor_id": e.actor_id,
            "action": e.action,
            "resource_type": e.resource_type,
            "resource_id": e.resource_id,
            "status": e.status,
            "error": e.error,
            "metadata": e.metadata,
        }
        for e in entries
    ]


def create_app() -> FastAPI:
    """Create and return the FastAPI app."""
    return app


def run_server(host: str = "127.0.0.1", port: int = 8420):
    """Run the server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)
