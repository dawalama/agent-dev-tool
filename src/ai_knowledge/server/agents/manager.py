"""Agent lifecycle management."""

import asyncio
import json
import subprocess
import signal
import os
import threading
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field

from ..config import Config, get_adt_home
from ..scrubber import scrub_log_content


class AgentStatus(str, Enum):
    """Agent status states."""
    IDLE = "idle"
    SPAWNING = "spawning"
    WORKING = "working"
    WAITING = "waiting"  # Waiting for human input
    TESTING = "testing"
    ERROR = "error"
    STOPPED = "stopped"


class AgentState(BaseModel):
    """Persistent state for an agent."""
    project: str
    status: AgentStatus = AgentStatus.IDLE
    provider: str = "cursor"
    pid: int | None = None
    worktree: str | None = None
    current_task: str | None = None
    started_at: datetime | None = None
    last_activity: datetime | None = None
    error: str | None = None
    retry_count: int = 0
    
    def save(self) -> None:
        """Save state to file."""
        path = get_adt_home() / "agents" / f"{self.project}.state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2))
    
    @classmethod
    def load(cls, project: str) -> "AgentState | None":
        """Load state from file."""
        path = get_adt_home() / "agents" / f"{project}.state.json"
        if not path.exists():
            return None
        try:
            return cls.model_validate_json(path.read_text())
        except Exception:
            return None
    
    @classmethod
    def delete(cls, project: str) -> None:
        """Delete state file."""
        path = get_adt_home() / "agents" / f"{project}.state.json"
        if path.exists():
            path.unlink()


class AgentManager:
    """Manages agent lifecycle and coordination."""
    
    def __init__(self, config: Config):
        self.config = config
        self._agents: dict[str, AgentState] = {}
        self._processes: dict[str, subprocess.Popen] = {}
        self._log_files: dict[str, any] = {}
        self._monitors: dict[str, threading.Thread] = {}
        self._callbacks: dict[str, list[Callable]] = {
            "status_change": [],
            "task_complete": [],
            "error": [],
            "escalation": [],
        }
        self._load_states()
    
    def _load_states(self) -> None:
        """Load persisted agent states."""
        agents_dir = get_adt_home() / "agents"
        if not agents_dir.exists():
            return
        
        for state_file in agents_dir.glob("*.state.json"):
            project = state_file.stem.replace(".state", "")
            state = AgentState.load(project)
            if state:
                # Check if process is still running
                if state.pid:
                    if not self._is_process_running(state.pid):
                        state.status = AgentStatus.STOPPED
                        state.pid = None
                        state.save()
                self._agents[project] = state
    
    def _is_process_running(self, pid: int) -> bool:
        """Check if a process is running."""
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    
    def on(self, event: str, callback: Callable) -> None:
        """Register an event callback."""
        if event in self._callbacks:
            self._callbacks[event].append(callback)
    
    def _emit(self, event: str, *args, **kwargs) -> None:
        """Emit an event to all callbacks."""
        for callback in self._callbacks.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception:
                pass
    
    def list(self) -> list[AgentState]:
        """List all agents."""
        return list(self._agents.values())
    
    def get(self, project: str) -> AgentState | None:
        """Get agent state for a project."""
        return self._agents.get(project)
    
    def spawn(
        self,
        project: str,
        provider: str | None = None,
        worktree: str | None = None,
        task: str | None = None,
    ) -> AgentState:
        """Spawn a new agent for a project."""
        from ...store import load_config as load_adt_config
        
        # Check if already running
        existing = self._agents.get(project)
        if existing and existing.status not in (AgentStatus.STOPPED, AgentStatus.ERROR):
            if existing.pid and self._is_process_running(existing.pid):
                raise ValueError(f"Agent for {project} is already running")
        
        # Get project path
        adt_config = load_adt_config()
        proj = adt_config.get_project(project)
        if not proj:
            raise ValueError(f"Project not found: {project}")
        
        project_path = proj.path
        if worktree:
            # Use worktree path instead
            project_path = Path(worktree)
        
        # Determine provider
        provider = provider or self.config.agents.default_provider
        
        # Create state
        state = AgentState(
            project=project,
            status=AgentStatus.SPAWNING,
            provider=provider,
            worktree=worktree,
            current_task=task,
            started_at=datetime.now(),
            last_activity=datetime.now(),
        )
        
        # Spawn the agent process
        try:
            process = self._spawn_agent_process(project, project_path, provider, task)
            state.pid = process.pid
            state.status = AgentStatus.WORKING if task else AgentStatus.IDLE
            self._processes[project] = process
        except Exception as e:
            state.status = AgentStatus.ERROR
            state.error = str(e)
        
        state.save()
        self._agents[project] = state
        self._emit("status_change", project, state)
        
        return state
    
    def _spawn_agent_process(
        self,
        project: str,
        project_path: Path,
        provider: str,
        task: str | None,
    ) -> subprocess.Popen:
        """Spawn the actual agent process."""
        log_path = get_adt_home() / "logs" / "agents" / f"{project}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Build command based on provider
        if provider == "cursor" or provider == "cursor-agent":
            cmd = ["cursor-agent", "-p"]
            if task:
                cmd.append(task)
        else:
            # For other providers, we'll use a wrapper script
            cmd = [
                "python", "-m", "ai_knowledge.server.agents.runner",
                "--project", project,
                "--provider", provider,
            ]
            if task:
                cmd.extend(["--task", task])
        
        # Open log file (scrubbing happens when reading logs, not writing)
        log_file = open(log_path, "a")
        log_file.write(f"\n\n=== Agent started at {datetime.now().isoformat()} ===\n")
        log_file.write(f"Project: {project}\n")
        log_file.write(f"Provider: {provider}\n")
        log_file.write(f"Task: {task or 'none'}\n")
        log_file.write("=" * 50 + "\n\n")
        log_file.flush()
        
        process = subprocess.Popen(
            cmd,
            cwd=project_path,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        
        # Store log file reference for cleanup
        self._log_files[project] = log_file
        
        # Start a monitor thread to watch for process exit
        monitor = threading.Thread(
            target=self._monitor_process,
            args=(project, process),
            daemon=True,
        )
        monitor.start()
        self._monitors[project] = monitor
        
        return process
    
    def _monitor_process(self, project: str, process: subprocess.Popen) -> None:
        """Monitor a process and update state when it exits."""
        exit_code = process.wait()
        
        # Close log file
        if project in self._log_files:
            try:
                log_file = self._log_files[project]
                log_file.write(f"\n\n=== Agent exited with code {exit_code} at {datetime.now().isoformat()} ===\n")
                log_file.close()
            except Exception:
                pass
            del self._log_files[project]
        
        # Capture output from log file
        output = self._capture_output(project)
        
        # Update state
        state = self._agents.get(project)
        if state:
            if exit_code == 0:
                state.status = AgentStatus.STOPPED
                state.error = None
            else:
                state.status = AgentStatus.ERROR
                # Try to get last few lines of log for error context
                state.error = self._get_exit_error(project, exit_code)
            
            state.pid = None
            state.save()
            self._emit("status_change", project, state)
            self._emit("task_complete", project, exit_code, output)
            
            if exit_code != 0:
                self._emit("error", project, state.error)
    
    def _capture_output(self, project: str) -> str:
        """Capture the meaningful output from an agent run."""
        log_path = get_adt_home() / "logs" / "agents" / f"{project}.log"
        if not log_path.exists():
            return ""
        
        try:
            content = log_path.read_text()
            lines = content.split("\n")
            
            # Find the last run's output (between === markers)
            output_lines = []
            in_output = False
            
            for line in reversed(lines):
                if line.startswith("=== Agent exited"):
                    in_output = True
                    continue
                if line.startswith("=== Agent started") or line.startswith("=" * 50):
                    if in_output:
                        break
                    continue
                if in_output:
                    output_lines.append(line)
            
            output_lines.reverse()
            output = "\n".join(output_lines).strip()
            
            # Scrub secrets
            return scrub_log_content(output)
        except Exception:
            return ""
    
    def _get_exit_error(self, project: str, exit_code: int) -> str:
        """Extract error message from agent logs."""
        log_path = get_adt_home() / "logs" / "agents" / f"{project}.log"
        if not log_path.exists():
            return f"Agent exited with code {exit_code}"
        
        try:
            content = log_path.read_text()
            lines = content.strip().split("\n")
            # Get last 5 non-empty lines before the exit message
            recent = [l for l in lines[-10:] if l.strip() and not l.startswith("===")]
            if recent:
                return f"Exit code {exit_code}: {recent[-1][:200]}"
            return f"Agent exited with code {exit_code}"
        except Exception:
            return f"Agent exited with code {exit_code}"
    
    def stop(self, project: str, force: bool = False) -> bool:
        """Stop an agent."""
        state = self._agents.get(project)
        if not state:
            return False
        
        if state.pid:
            try:
                sig = signal.SIGKILL if force else signal.SIGTERM
                os.kill(state.pid, sig)
            except OSError:
                pass
        
        # Clean up process reference
        if project in self._processes:
            try:
                self._processes[project].terminate()
            except Exception:
                pass
            del self._processes[project]
        
        state.status = AgentStatus.STOPPED
        state.pid = None
        state.save()
        
        self._emit("status_change", project, state)
        return True
    
    def assign_task(self, project: str, task: str) -> AgentState:
        """Assign a task to an agent."""
        state = self._agents.get(project)
        
        if not state or state.status == AgentStatus.STOPPED:
            # Spawn if not running
            return self.spawn(project, task=task)
        
        if state.status == AgentStatus.WORKING:
            raise ValueError(f"Agent {project} is busy with another task")
        
        # TODO: Send task to running agent via IPC
        state.current_task = task
        state.status = AgentStatus.WORKING
        state.last_activity = datetime.now()
        state.save()
        
        self._emit("status_change", project, state)
        return state
    
    def update_status(self, project: str, status: AgentStatus, **kwargs) -> AgentState | None:
        """Update agent status."""
        state = self._agents.get(project)
        if not state:
            return None
        
        old_status = state.status
        state.status = status
        state.last_activity = datetime.now()
        
        for key, value in kwargs.items():
            if hasattr(state, key):
                setattr(state, key, value)
        
        state.save()
        
        if old_status != status:
            self._emit("status_change", project, state)
        
        return state
    
    def get_logs(self, project: str, lines: int = 100) -> str:
        """Get recent log lines for an agent (scrubbed for secrets)."""
        log_path = get_adt_home() / "logs" / "agents" / f"{project}.log"
        if not log_path.exists():
            return ""
        
        # Read last N lines and scrub secrets
        content = log_path.read_text()
        log_lines = content.split("\n")
        raw_logs = "\n".join(log_lines[-lines:])
        return scrub_log_content(raw_logs)
    
    def cleanup_stopped(self) -> int:
        """Remove state files for stopped agents. Returns count removed."""
        count = 0
        for project, state in list(self._agents.items()):
            if state.status == AgentStatus.STOPPED:
                AgentState.delete(project)
                del self._agents[project]
                count += 1
        return count
    
    def check_health(self) -> dict[str, bool]:
        """Check health of all agents."""
        health = {}
        for project, state in self._agents.items():
            if state.pid:
                health[project] = self._is_process_running(state.pid)
                if not health[project]:
                    state.status = AgentStatus.STOPPED
                    state.pid = None
                    state.save()
            else:
                health[project] = state.status not in (AgentStatus.STOPPED, AgentStatus.ERROR)
        return health
