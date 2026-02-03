"""Database connection management."""

import sqlite3
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

from ..config import get_adt_home


class DatabaseManager:
    """Manages SQLite database connections."""
    
    def __init__(self, db_dir: Optional[Path] = None):
        self.db_dir = db_dir or get_adt_home() / "data"
        self.db_dir.mkdir(parents=True, exist_ok=True)
        
        self._connections: dict[str, sqlite3.Connection] = {}
    
    def get_connection(self, db_name: str) -> sqlite3.Connection:
        """Get or create a connection to a database."""
        if db_name not in self._connections:
            db_path = self.db_dir / f"{db_name}.db"
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._connections[db_name] = conn
        return self._connections[db_name]
    
    @contextmanager
    def transaction(self, db_name: str):
        """Context manager for database transactions."""
        conn = self.get_connection(db_name)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    
    def close_all(self):
        """Close all database connections."""
        for conn in self._connections.values():
            conn.close()
        self._connections.clear()


# Global database manager
_db_manager: Optional[DatabaseManager] = None


def get_db_manager() -> DatabaseManager:
    """Get the global database manager."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


def get_db(db_name: str) -> sqlite3.Connection:
    """Get a database connection by name."""
    return get_db_manager().get_connection(db_name)


def init_databases():
    """Initialize all database schemas."""
    manager = get_db_manager()
    
    # Main database - projects, config
    with manager.transaction("main") as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                name TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                config JSON
            );
            
            CREATE TABLE IF NOT EXISTS agent_registry (
                project TEXT PRIMARY KEY REFERENCES projects(name),
                provider TEXT DEFAULT 'cursor',
                preferred_worktree TEXT,
                config JSON
            );
        """)
    
    # Tasks database - queue and history
    with manager.transaction("tasks") as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                project TEXT NOT NULL,
                description TEXT NOT NULL,
                priority TEXT DEFAULT 'normal',
                status TEXT DEFAULT 'pending',
                assigned_to TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                result TEXT,
                error TEXT,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                metadata JSON
            );
            
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project);
            CREATE INDEX IF NOT EXISTS idx_tasks_priority_status ON tasks(priority, status);
            CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
        """)
    
    # Logs database - events and agent runs
    with manager.transaction("logs") as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                type TEXT NOT NULL,
                project TEXT,
                agent TEXT,
                task_id TEXT,
                level TEXT DEFAULT 'info',
                message TEXT,
                data JSON
            );
            
            CREATE INDEX IF NOT EXISTS idx_events_time ON events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_events_project ON events(project);
            CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
            
            CREATE TABLE IF NOT EXISTS agent_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                provider TEXT,
                task TEXT,
                task_id TEXT,
                pid INTEGER,
                started_at TIMESTAMP NOT NULL,
                ended_at TIMESTAMP,
                exit_code INTEGER,
                status TEXT,
                error TEXT,
                log_file TEXT
            );
            
            CREATE INDEX IF NOT EXISTS idx_runs_project ON agent_runs(project);
            CREATE INDEX IF NOT EXISTS idx_runs_time ON agent_runs(started_at);
            CREATE INDEX IF NOT EXISTS idx_runs_status ON agent_runs(status);
        """)


def close_databases():
    """Close all database connections."""
    global _db_manager
    if _db_manager:
        _db_manager.close_all()
        _db_manager = None
