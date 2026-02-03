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
    STOPPED = "stopped"  # Was running, now stopped
    FAILED = "failed"    # Crashed unexpectedly
    STARTING = "starting"
    IDLE = "idle"        # Registered but never started


class ProcessState(BaseModel):
    """State of a managed process."""
    id: str
    project: str
    name: str
    process_type: ProcessType = ProcessType.DEV_SERVER
    command: str
    cwd: str
    status: ProcessStatus = ProcessStatus.IDLE  # Start as idle, not stopped
    pid: Optional[int] = None
    port: Optional[int] = None
    started_at: Optional[datetime] = None
    exit_code: Optional[int] = None
    error: Optional[str] = None
    description: Optional[str] = None  # What this process does
    
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


def detect_dev_command(project_path: str, assigned_port: Optional[int] = None) -> Optional[tuple[str, int]]:
    """Detect the appropriate dev command for a project.
    
    Returns (command, port) or None.
    If assigned_port is given, the command will use that port.
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
        self._stopping: set[str] = set()  # Processes being intentionally stopped
        
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
        force_update: bool = False,
    ) -> ProcessState:
        """Register a new process configuration.
        
        If force_update is True, updates existing config even if already registered.
        """
        process_id = f"{project}-{name}".lower().replace(" ", "-")
        
        # Check if already exists and not forcing update
        existing = self._processes.get(process_id)
        if existing and not force_update:
            # Update port if changed
            if port and existing.port != port:
                existing.port = port
                existing.command = command
                existing.save()
            return existing
        
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
        from .ports import get_port_manager
        
        state = self._processes.get(process_id)
        if not state:
            raise ValueError(f"Process not found: {process_id}")
        
        if state.status == ProcessStatus.RUNNING:
            raise ValueError(f"Process already running: {process_id}")
        
        # Check if port has been updated in the registry
        port_manager = get_port_manager()
        registered_port = port_manager.get_port(state.project, state.name)
        if registered_port and registered_port != state.port:
            # Port was changed - update the command
            old_port = state.port
            state.port = registered_port
            state.command = self._update_command_port(state.command, old_port, registered_port)
            state.save()
        
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
        
        # Mark as intentionally stopping so monitor doesn't mark as failed
        self._stopping.add(process_id)
        
        sig = signal.SIGKILL if force else signal.SIGTERM
        killed = False
        
        # Try to kill via subprocess reference first
        process = self._subprocesses.get(process_id)
        if process:
            try:
                # Kill the entire process group
                os.killpg(os.getpgid(process.pid), sig)
                killed = True
            except ProcessLookupError:
                pass
            except Exception as e:
                state.error = str(e)
        
        # If we have a PID stored, try killing that too
        if state.pid and not killed:
            try:
                os.killpg(os.getpgid(state.pid), sig)
                killed = True
            except ProcessLookupError:
                pass
            except Exception:
                pass
        
        # Last resort: find and kill any process using our port
        if state.port and not killed:
            self._kill_port_process(state.port, sig)
        
        state.status = ProcessStatus.STOPPED
        state.pid = None
        state.error = None  # Clear any previous error
        state.save()
        
        self._emit("stopped", process_id, state)
        
        return state
    
    def _kill_port_process(self, port: int, sig: int = signal.SIGTERM):
        """Find and kill any process using the given port."""
        import subprocess as sp
        try:
            # Use lsof to find PIDs using this port
            result = sp.run(
                ["lsof", "-t", "-i", f":{port}"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.stdout.strip():
                for pid_str in result.stdout.strip().split('\n'):
                    try:
                        pid = int(pid_str.strip())
                        os.kill(pid, sig)
                    except (ValueError, ProcessLookupError):
                        pass
        except Exception:
            pass
    
    def restart(self, process_id: str) -> ProcessState:
        """Restart a process."""
        self.stop(process_id)
        return self.start(process_id)
    
    def _monitor_process(self, process_id: str, process: subprocess.Popen):
        """Monitor a process and update state when it exits."""
        exit_code = process.wait()
        
        # Check if this was an intentional stop
        was_intentional_stop = process_id in self._stopping
        self._stopping.discard(process_id)
        
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
        
        # Extract error message if failed (and not intentionally stopped)
        error_msg = None
        if exit_code != 0 and not was_intentional_stop:
            error_msg = self._extract_error(process_id)
        
        # Update state
        state = self._processes.get(process_id)
        if state:
            # If intentionally stopped, mark as stopped regardless of exit code
            if was_intentional_stop:
                state.status = ProcessStatus.STOPPED
                state.error = None
            else:
                state.status = ProcessStatus.FAILED if exit_code != 0 else ProcessStatus.STOPPED
                state.error = error_msg
            
            state.exit_code = exit_code
            state.pid = None
            state.save()
            
            self._emit("exited", process_id, exit_code, state)
    
    def _extract_error(self, process_id: str, lines: int = 30) -> str:
        """Extract error message from recent logs."""
        logs = self.get_logs(process_id, lines=lines)
        if not logs:
            return "Process exited with error"
        
        # Look for common error patterns
        error_lines = []
        for line in logs.split("\n"):
            line_lower = line.lower()
            if any(kw in line_lower for kw in ["error", "exception", "failed", "cannot", "unable", "traceback"]):
                error_lines.append(line)
        
        if error_lines:
            return "\n".join(error_lines[-10:])  # Last 10 error lines
        
        # Just return last few lines
        return "\n".join(logs.split("\n")[-10:])
    
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
        """Auto-detect and register dev processes for a project.
        
        Uses PortManager to assign non-conflicting ports.
        """
        from .ports import get_port_manager
        
        detected = []
        path = Path(project_path)
        port_manager = get_port_manager()
        
        # Detect services first, then assign ports
        services_to_register = []
        
        # Check for frontend
        frontend_dirs = ["frontend", "client", "web", "ui"]
        for frontend_dir in frontend_dirs:
            frontend_path = path / frontend_dir
            if frontend_path.exists():
                result = detect_dev_command(str(frontend_path))
                if result:
                    base_cmd, default_port = result
                    services_to_register.append({
                        "name": "frontend",
                        "base_cmd": base_cmd,
                        "cwd": str(frontend_path),
                        "default_port": default_port,
                    })
                break
        
        # Check for backend
        backend_dirs = ["backend", "server", "api"]
        for backend_dir in backend_dirs:
            backend_path = path / backend_dir
            if backend_path.exists():
                result = detect_dev_command(str(backend_path))
                if result:
                    base_cmd, default_port = result
                    services_to_register.append({
                        "name": "backend",
                        "base_cmd": base_cmd,
                        "cwd": str(backend_path),
                        "default_port": default_port,
                    })
                break
        
        # Check root for single-app projects
        if not services_to_register:
            result = detect_dev_command(str(path))
            if result:
                base_cmd, default_port = result
                services_to_register.append({
                    "name": "app",
                    "base_cmd": base_cmd,
                    "cwd": str(path),
                    "default_port": default_port,
                })
        
        # Assign ports and register
        for svc in services_to_register:
            # Get or assign port
            port = port_manager.assign_port(
                project=project,
                service=svc["name"],
                preferred=svc["default_port"],
            )
            
            # Adjust command to use assigned port
            cmd = self._adjust_command_port(svc["base_cmd"], port)
            
            state = self.register(
                project=project,
                name=svc["name"],
                command=cmd,
                cwd=svc["cwd"],
                port=port,
            )
            detected.append(state)
        
        return detected
    
    def _adjust_command_port(self, cmd: str, port: int) -> str:
        """Adjust a dev command to use a specific port."""
        import re
        
        # Handle common patterns
        # For npm scripts, we need to use -- to pass args through
        if cmd.strip() == "npm run dev":
            return f"npm run dev -- --port {port}"
        
        if cmd.strip() == "npm start":
            return f"PORT={port} npm start"
        
        # vite directly
        if "vite" in cmd and "npm" not in cmd:
            cmd = re.sub(r'--port\s*\d+', '', cmd)
            return f"{cmd.strip()} --port {port}"
        
        # next dev
        if "next" in cmd:
            cmd = re.sub(r'-p\s*\d+', '', cmd)
            cmd = re.sub(r'--port\s*\d+', '', cmd)
            return f"{cmd.strip()} -p {port}"
        
        # uvicorn --port XXXX
        if "uvicorn" in cmd:
            cmd = re.sub(r'--port\s*\d+', '', cmd)
            return f"{cmd.strip()} --port {port}"
        
        # flask run --port XXXX
        if "flask" in cmd:
            cmd = re.sub(r'--port\s*\d+', '', cmd)
            return f"{cmd.strip()} --port {port}"
        
        # django runserver XXXX
        if "runserver" in cmd:
            cmd = re.sub(r'runserver\s*\d*', 'runserver', cmd)
            return f"{cmd.strip()} {port}"
        
        # Generic: try PORT env var
        return f"PORT={port} {cmd}"
    
    def _update_command_port(self, cmd: str, old_port: Optional[int], new_port: int) -> str:
        """Update port in an existing command."""
        import re
        
        if old_port:
            # Replace old port with new port in the command
            cmd = re.sub(rf'--port\s*{old_port}\b', f'--port {new_port}', cmd)
            cmd = re.sub(rf'-p\s*{old_port}\b', f'-p {new_port}', cmd)
            cmd = re.sub(rf'PORT={old_port}\b', f'PORT={new_port}', cmd)
            cmd = re.sub(rf'runserver\s*{old_port}\b', f'runserver {new_port}', cmd)
            return cmd
        
        # No old port, use adjust method
        return self._adjust_command_port(cmd, new_port)
    
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
