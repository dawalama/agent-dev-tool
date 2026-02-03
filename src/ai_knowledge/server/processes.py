"""Process management for long-running project services (dev servers, etc.)."""

from __future__ import annotations

import subprocess
import signal
import os
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable
from enum import Enum
from pydantic import BaseModel, Field

from .config import get_adt_home


class ProcessType(str, Enum):
    DEV_SERVER = "dev_server"
    DATABASE = "database"
    WORKER = "worker"
    CUSTOM = "custom"


class ProcessStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"
    STARTING = "starting"


class ProcessState(BaseModel):
    """State of a managed process."""
    id: str
    project: str
    name: str
    process_type: ProcessType = ProcessType.DEV_SERVER
    command: str
    cwd: str
    status: ProcessStatus = ProcessStatus.STOPPED
    pid: Optional[int] = None
    port: Optional[int] = None
    started_at: Optional[datetime] = None
    exit_code: Optional[int] = None
    error: Optional[str] = None
    
    def state_path(self) -> Path:
        return get_adt_home() / "processes" / f"{self.id}.state.json"
    
    def log_path(self) -> Path:
        return get_adt_home() / "logs" / "processes" / f"{self.id}.log"
    
    def save(self):
        self.state_path().parent.mkdir(parents=True, exist_ok=True)
        self.state_path().write_text(self.model_dump_json(indent=2))
    
    @classmethod
    def load(cls, process_id: str) -> Optional["ProcessState"]:
        path = get_adt_home() / "processes" / f"{process_id}.state.json"
        if path.exists():
            return cls.model_validate_json(path.read_text())
        return None


# Common dev server commands by stack
DEV_COMMANDS = {
    "react": "npm run dev",
    "vite": "npm run dev",
    "next": "npm run dev",
    "vue": "npm run dev",
    "express": "npm run dev",
    "fastapi": "uvicorn main:app --reload",
    "django": "python manage.py runserver",
    "flask": "flask run --reload",
}


def detect_dev_command(project_path: str) -> Optional[tuple[str, int]]:
    """Detect the appropriate dev command for a project.
    
    Returns (command, default_port) or None.
    """
    path = Path(project_path)
    
    # Check package.json for Node.js projects
    pkg_json = path / "package.json"
    if pkg_json.exists():
        import json
        try:
            pkg = json.loads(pkg_json.read_text())
            scripts = pkg.get("scripts", {})
            
            if "dev" in scripts:
                # Try to detect port from script
                dev_script = scripts["dev"]
                port = 3000  # default
                if "--port" in dev_script:
                    # Extract port number
                    parts = dev_script.split("--port")
                    if len(parts) > 1:
                        port_str = parts[1].strip().split()[0]
                        try:
                            port = int(port_str)
                        except ValueError:
                            pass
                elif "5173" in dev_script:  # Vite default
                    port = 5173
                    
                return ("npm run dev", port)
            elif "start" in scripts:
                return ("npm start", 3000)
        except json.JSONDecodeError:
            pass
    
    # Check for Python projects
    if (path / "main.py").exists() or (path / "app.py").exists():
        if (path / "requirements.txt").exists():
            reqs = (path / "requirements.txt").read_text().lower()
            if "fastapi" in reqs or "uvicorn" in reqs:
                main_file = "main" if (path / "main.py").exists() else "app"
                return (f"uvicorn {main_file}:app --reload --port 8000", 8000)
            elif "flask" in reqs:
                return ("flask run --reload --port 5000", 5000)
            elif "django" in reqs:
                return ("python manage.py runserver 8000", 8000)
    
    # Check for pyproject.toml
    if (path / "pyproject.toml").exists():
        toml_content = (path / "pyproject.toml").read_text().lower()
        if "fastapi" in toml_content:
            return ("uvicorn main:app --reload --port 8000", 8000)
    
    return None


class ProcessManager:
    """Manages long-running processes for projects."""
    
    def __init__(self):
        self._processes: dict[str, ProcessState] = {}
        self._subprocesses: dict[str, subprocess.Popen] = {}
        self._log_files: dict[str, object] = {}
        self._callbacks: dict[str, list[Callable]] = {}
        
        # Load existing process states
        self._load_states()
    
    def _load_states(self):
        """Load persisted process states."""
        state_dir = get_adt_home() / "processes"
        if state_dir.exists():
            for state_file in state_dir.glob("*.state.json"):
                try:
                    state = ProcessState.model_validate_json(state_file.read_text())
                    # Mark as stopped since we just started
                    if state.status == ProcessStatus.RUNNING:
                        state.status = ProcessStatus.STOPPED
                        state.pid = None
                        state.save()
                    self._processes[state.id] = state
                except Exception:
                    pass
    
    def on(self, event: str, callback: Callable):
        """Register event callback."""
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)
    
    def _emit(self, event: str, *args):
        """Emit event to callbacks."""
        for callback in self._callbacks.get(event, []):
            try:
                callback(*args)
            except Exception:
                pass
    
    def register(
        self,
        project: str,
        name: str,
        command: str,
        cwd: str,
        process_type: ProcessType = ProcessType.DEV_SERVER,
        port: Optional[int] = None,
    ) -> ProcessState:
        """Register a new process configuration."""
        process_id = f"{project}-{name}".lower().replace(" ", "-")
        
        state = ProcessState(
            id=process_id,
            project=project,
            name=name,
            process_type=process_type,
            command=command,
            cwd=cwd,
            port=port,
        )
        state.save()
        self._processes[process_id] = state
        return state
    
    def start(self, process_id: str) -> ProcessState:
        """Start a registered process."""
        state = self._processes.get(process_id)
        if not state:
            raise ValueError(f"Process not found: {process_id}")
        
        if state.status == ProcessStatus.RUNNING:
            raise ValueError(f"Process already running: {process_id}")
        
        # Ensure log directory exists
        state.log_path().parent.mkdir(parents=True, exist_ok=True)
        
        # Open log file
        log_file = open(state.log_path(), "a")
        log_file.write(f"\n\n=== Process started at {datetime.now().isoformat()} ===\n")
        log_file.write(f"Command: {state.command}\n")
        log_file.write(f"CWD: {state.cwd}\n")
        log_file.write("=" * 50 + "\n\n")
        log_file.flush()
        
        self._log_files[process_id] = log_file
        
        # Start the process
        try:
            env = os.environ.copy()
            # Add common dev environment variables
            env["FORCE_COLOR"] = "1"
            env["NODE_ENV"] = "development"
            
            process = subprocess.Popen(
                state.command,
                shell=True,
                cwd=state.cwd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
                preexec_fn=os.setsid,  # Create new process group
            )
            
            self._subprocesses[process_id] = process
            
            state.status = ProcessStatus.RUNNING
            state.pid = process.pid
            state.started_at = datetime.now()
            state.exit_code = None
            state.error = None
            state.save()
            
            # Start monitoring thread
            monitor = threading.Thread(
                target=self._monitor_process,
                args=(process_id, process),
                daemon=True,
            )
            monitor.start()
            
            self._emit("started", process_id, state)
            
        except Exception as e:
            state.status = ProcessStatus.FAILED
            state.error = str(e)
            state.save()
            log_file.close()
            del self._log_files[process_id]
            raise
        
        return state
    
    def stop(self, process_id: str, force: bool = False) -> ProcessState:
        """Stop a running process."""
        state = self._processes.get(process_id)
        if not state:
            raise ValueError(f"Process not found: {process_id}")
        
        if state.status != ProcessStatus.RUNNING:
            return state
        
        process = self._subprocesses.get(process_id)
        if process:
            try:
                # Kill the entire process group
                sig = signal.SIGKILL if force else signal.SIGTERM
                os.killpg(os.getpgid(process.pid), sig)
            except ProcessLookupError:
                pass
            except Exception as e:
                state.error = str(e)
        
        state.status = ProcessStatus.STOPPED
        state.pid = None
        state.save()
        
        self._emit("stopped", process_id, state)
        
        return state
    
    def restart(self, process_id: str) -> ProcessState:
        """Restart a process."""
        self.stop(process_id)
        return self.start(process_id)
    
    def _monitor_process(self, process_id: str, process: subprocess.Popen):
        """Monitor a process and update state when it exits."""
        exit_code = process.wait()
        
        # Close log file
        if process_id in self._log_files:
            try:
                log_file = self._log_files[process_id]
                log_file.write(f"\n\n=== Process exited with code {exit_code} at {datetime.now().isoformat()} ===\n")
                log_file.close()
            except Exception:
                pass
            del self._log_files[process_id]
        
        # Remove from subprocesses
        if process_id in self._subprocesses:
            del self._subprocesses[process_id]
        
        # Update state
        state = self._processes.get(process_id)
        if state:
            state.status = ProcessStatus.FAILED if exit_code != 0 else ProcessStatus.STOPPED
            state.exit_code = exit_code
            state.pid = None
            state.save()
            
            self._emit("exited", process_id, exit_code, state)
    
    def get(self, process_id: str) -> Optional[ProcessState]:
        """Get a process by ID."""
        return self._processes.get(process_id)
    
    def list(self, project: Optional[str] = None) -> list[ProcessState]:
        """List all processes, optionally filtered by project."""
        processes = list(self._processes.values())
        if project:
            processes = [p for p in processes if p.project == project]
        return processes
    
    def list_running(self) -> list[ProcessState]:
        """List only running processes."""
        return [p for p in self._processes.values() if p.status == ProcessStatus.RUNNING]
    
    def get_logs(self, process_id: str, lines: int = 100) -> str:
        """Get recent log lines for a process."""
        state = self._processes.get(process_id)
        if not state:
            return ""
        
        log_path = state.log_path()
        if not log_path.exists():
            return ""
        
        content = log_path.read_text()
        log_lines = content.split("\n")
        return "\n".join(log_lines[-lines:])
    
    def auto_detect(self, project: str, project_path: str) -> list[ProcessState]:
        """Auto-detect and register dev processes for a project."""
        detected = []
        path = Path(project_path)
        
        # Check for frontend
        frontend_dirs = ["frontend", "client", "web", "ui"]
        for frontend_dir in frontend_dirs:
            frontend_path = path / frontend_dir
            if frontend_path.exists():
                result = detect_dev_command(str(frontend_path))
                if result:
                    cmd, port = result
                    state = self.register(
                        project=project,
                        name="frontend",
                        command=cmd,
                        cwd=str(frontend_path),
                        port=port,
                    )
                    detected.append(state)
                break
        
        # Check for backend
        backend_dirs = ["backend", "server", "api"]
        for backend_dir in backend_dirs:
            backend_path = path / backend_dir
            if backend_path.exists():
                result = detect_dev_command(str(backend_path))
                if result:
                    cmd, port = result
                    state = self.register(
                        project=project,
                        name="backend",
                        command=cmd,
                        cwd=str(backend_path),
                        port=port,
                    )
                    detected.append(state)
                break
        
        # Check root for single-app projects
        if not detected:
            result = detect_dev_command(str(path))
            if result:
                cmd, port = result
                state = self.register(
                    project=project,
                    name="app",
                    command=cmd,
                    cwd=str(path),
                    port=port,
                )
                detected.append(state)
        
        return detected
    
    def stop_all(self):
        """Stop all running processes."""
        for process_id in list(self._subprocesses.keys()):
            try:
                self.stop(process_id, force=True)
            except Exception:
                pass


# Global process manager
_process_manager: Optional[ProcessManager] = None


def get_process_manager() -> ProcessManager:
    """Get the global process manager."""
    global _process_manager
    if _process_manager is None:
        _process_manager = ProcessManager()
    return _process_manager
