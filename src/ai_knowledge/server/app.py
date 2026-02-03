"""FastAPI server for ADT Command Center."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
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


class AssignRequest(BaseModel):
    task: str


# Global state
config: Config | None = None
agent_manager: AgentManager | None = None
task_queue: TaskQueue | None = None
event_bus: EventBus | None = None
telegram_bot = None
connected_clients: set[WebSocket] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    global config, agent_manager, task_queue, event_bus, telegram_bot
    
    ensure_adt_home()
    config = Config.load()
    agent_manager = AgentManager(config)
    task_queue = TaskQueue()
    event_bus = get_event_bus()
    
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
    
    # Emit server started event
    event_bus.emit(EventType.SERVER_STARTED)
    
    yield
    
    # Cleanup
    if telegram_bot:
        await telegram_bot.stop()
    event_bus.emit(EventType.SERVER_STOPPED)


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
async def spawn_agent(req: SpawnRequest):
    """Spawn a new agent."""
    try:
        state = agent_manager.spawn(
            project=req.project,
            provider=req.provider,
            task=req.task,
            worktree=req.worktree,
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
async def retry_agent(project: str, request: RetryRequest | None = None):
    """Retry a failed agent with optional new task."""
    agent = agent_manager.get(project)
    
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent not found: {project}")
    
    if agent.status != AgentStatus.ERROR:
        raise HTTPException(status_code=400, detail=f"Agent is not in error state: {agent.status}")
    
    # Get task - use new one if provided, otherwise use the previous task
    task = None
    if request and request.task:
        task = request.task
    elif agent.current_task:
        task = agent.current_task
    
    try:
        # Stop first to clean up
        agent_manager.stop(project, force=True)
        
        # Respawn with task
        state = agent_manager.spawn(project, task=task)
        event_bus.emit(EventType.AGENT_STARTED, project=project, task=task)
        
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
    include_completed: bool = False,
):
    """List tasks in the queue."""
    status_filter = TaskStatus(status) if status else None
    tasks = task_queue.list(
        project=project,
        status=status_filter,
        include_completed=include_completed,
    )
    
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
async def create_task(req: TaskRequest):
    """Create a new task."""
    try:
        priority = TaskPriority(req.priority)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid priority: {req.priority}")
    
    task = task_queue.create(
        project=req.project,
        description=req.description,
        priority=priority,
    )
    
    event_bus.emit(
        EventType.TASK_CREATED,
        project=req.project,
        task_id=task.id,
        description=req.description,
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


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """Get a task by ID."""
    task = task_queue.get(task_id)
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
        "result": task.result,
        "error": task.error,
    }


@app.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """Cancel a task."""
    task = task_queue.cancel(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    
    return {"success": True, "task_id": task_id}


@app.get("/tasks/stats")
async def task_stats():
    """Get queue statistics."""
    return task_queue.stats()


# =============================================================================
# WebSocket for Real-time Updates
# =============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await websocket.accept()
    connected_clients.add(websocket)
    
    try:
        # Send current state on connect
        await websocket.send_json({
            "type": "connected",
            "data": {
                "agents": len(agent_manager.list()) if agent_manager else 0,
                "tasks": task_queue.stats() if task_queue else {},
            },
        })
        
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
                
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                await websocket.send_json({"type": "ping"})
                
    except WebSocketDisconnect:
        pass
    finally:
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


def create_app() -> FastAPI:
    """Create and return the FastAPI app."""
    return app


def run_server(host: str = "127.0.0.1", port: int = 8420):
    """Run the server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)
