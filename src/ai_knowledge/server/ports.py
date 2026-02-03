"""Port management and coordination for multiple projects."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

from .config import get_adt_home


class PortAssignment(BaseModel):
    """A port assignment for a project service."""
    project: str
    service: str  # e.g., "frontend", "backend", "db"
    port: int
    in_use: bool = False


class PortRegistry(BaseModel):
    """Registry of all port assignments."""
    range_start: int = 3000
    range_end: int = 9000
    reserved: list[int] = Field(default_factory=lambda: [
        5432,   # PostgreSQL
        5433,   # PostgreSQL alt
        6379,   # Redis
        8420,   # ADT server
        27017,  # MongoDB
    ])
    assignments: dict[str, PortAssignment] = Field(default_factory=dict)
    
    def registry_path(self) -> Path:
        return get_adt_home() / "ports.json"
    
    def save(self):
        self.registry_path().write_text(self.model_dump_json(indent=2))
    
    @classmethod
    def load(cls) -> "PortRegistry":
        path = get_adt_home() / "ports.json"
        if path.exists():
            try:
                return cls.model_validate_json(path.read_text())
            except Exception:
                pass
        return cls()


def is_port_available(port: int) -> bool:
    """Check if a port is available for binding."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


def find_available_port(start: int, end: int, reserved: list[int]) -> Optional[int]:
    """Find the next available port in range."""
    for port in range(start, end):
        if port not in reserved and is_port_available(port):
            return port
    return None


class PortManager:
    """Manages port assignments across projects."""
    
    def __init__(self):
        self.registry = PortRegistry.load()
    
    def _assignment_key(self, project: str, service: str) -> str:
        return f"{project}:{service}"
    
    def get_port(self, project: str, service: str) -> Optional[int]:
        """Get assigned port for a project service."""
        key = self._assignment_key(project, service)
        assignment = self.registry.assignments.get(key)
        return assignment.port if assignment else None
    
    def assign_port(
        self, 
        project: str, 
        service: str, 
        preferred: Optional[int] = None,
    ) -> int:
        """Assign a port to a project service.
        
        If preferred port is given and available, use it.
        Otherwise, find the next available port.
        """
        key = self._assignment_key(project, service)
        
        # Check if already assigned
        existing = self.registry.assignments.get(key)
        if existing and is_port_available(existing.port):
            return existing.port
        
        # Try preferred port
        if preferred and preferred not in self.registry.reserved:
            if is_port_available(preferred):
                self._save_assignment(key, project, service, preferred)
                return preferred
        
        # Find next available
        port = find_available_port(
            self.registry.range_start,
            self.registry.range_end,
            self.registry.reserved + list(self._used_ports()),
        )
        
        if not port:
            raise RuntimeError("No available ports in range")
        
        self._save_assignment(key, project, service, port)
        return port
    
    def _used_ports(self) -> set[int]:
        """Get all currently assigned ports."""
        return {a.port for a in self.registry.assignments.values()}
    
    def _save_assignment(self, key: str, project: str, service: str, port: int):
        """Save a port assignment."""
        self.registry.assignments[key] = PortAssignment(
            project=project,
            service=service,
            port=port,
        )
        self.registry.save()
    
    def release_port(self, project: str, service: str):
        """Release a port assignment."""
        key = self._assignment_key(project, service)
        if key in self.registry.assignments:
            del self.registry.assignments[key]
            self.registry.save()
    
    def set_port(self, project: str, service: str, port: int) -> bool:
        """Explicitly set a port for a service. Returns False if port is in use."""
        if port in self.registry.reserved:
            return False
        
        if not is_port_available(port):
            # Check if it's assigned to us
            key = self._assignment_key(project, service)
            existing = self.registry.assignments.get(key)
            if not existing or existing.port != port:
                return False
        
        key = self._assignment_key(project, service)
        self._save_assignment(key, project, service, port)
        return True
    
    def list_assignments(self, project: Optional[str] = None) -> list[PortAssignment]:
        """List all port assignments, optionally filtered by project."""
        assignments = list(self.registry.assignments.values())
        if project:
            assignments = [a for a in assignments if a.project == project]
        
        # Update in_use status
        for a in assignments:
            a.in_use = not is_port_available(a.port)
        
        return assignments
    
    def get_project_ports(self, project: str) -> dict[str, int]:
        """Get all port assignments for a project as a dict."""
        return {
            a.service: a.port 
            for a in self.list_assignments(project)
        }
    
    def suggest_ports(self, project: str, services: list[str]) -> dict[str, int]:
        """Suggest ports for a list of services (doesn't assign yet)."""
        suggestions = {}
        used = self._used_ports() | set(self.registry.reserved)
        
        current_port = self.registry.range_start
        for service in services:
            # Check if already assigned
            existing = self.get_port(project, service)
            if existing:
                suggestions[service] = existing
                continue
            
            # Find next available
            while current_port in used or not is_port_available(current_port):
                current_port += 1
                if current_port >= self.registry.range_end:
                    break
            
            if current_port < self.registry.range_end:
                suggestions[service] = current_port
                used.add(current_port)
                current_port += 1
        
        return suggestions


# Global port manager
_port_manager: Optional[PortManager] = None


def get_port_manager() -> PortManager:
    """Get the global port manager."""
    global _port_manager
    if _port_manager is None:
        _port_manager = PortManager()
    return _port_manager
