"""Authentication and authorization for ADT Command Center."""

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from .config import get_adt_home


class Role(str, Enum):
    """User roles with different permission levels."""
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"
    AGENT = "agent"


class Permission(str, Enum):
    """Available permissions."""
    # Admin only
    TOKENS_MANAGE = "tokens.manage"
    CONFIG_WRITE = "config.write"
    SECRETS_MANAGE = "secrets.manage"
    
    # Operator+
    AGENTS_SPAWN = "agents.spawn"
    AGENTS_STOP = "agents.stop"
    TASKS_CREATE = "tasks.create"
    TASKS_CANCEL = "tasks.cancel"
    
    # Viewer+
    AGENTS_READ = "agents.read"
    TASKS_READ = "tasks.read"
    LOGS_READ = "logs.read"
    STATUS_READ = "status.read"
    PROJECTS_READ = "projects.read"
    
    # Agent (for agent-to-server)
    HEARTBEAT = "heartbeat"
    TASK_UPDATE = "task.update"
    LOGS_WRITE = "logs.write"


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN: set(Permission),  # All permissions
    Role.OPERATOR: {
        Permission.AGENTS_SPAWN,
        Permission.AGENTS_STOP,
        Permission.TASKS_CREATE,
        Permission.TASKS_CANCEL,
        Permission.AGENTS_READ,
        Permission.TASKS_READ,
        Permission.LOGS_READ,
        Permission.STATUS_READ,
        Permission.PROJECTS_READ,
    },
    Role.VIEWER: {
        Permission.AGENTS_READ,
        Permission.TASKS_READ,
        Permission.LOGS_READ,
        Permission.STATUS_READ,
        Permission.PROJECTS_READ,
    },
    Role.AGENT: {
        Permission.HEARTBEAT,
        Permission.TASK_UPDATE,
        Permission.LOGS_WRITE,
        Permission.STATUS_READ,
    },
}


class TokenInfo(BaseModel):
    """Information about an API token."""
    id: str
    name: str
    role: Role
    created_at: datetime
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    revoked: bool = False


class AuthManager:
    """Manages authentication tokens and authorization."""
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or get_adt_home() / "data" / "auth.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize the auth database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tokens (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    last_used_at TIMESTAMP,
                    revoked BOOLEAN DEFAULT FALSE,
                    created_by TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_tokens_hash ON tokens(token_hash)
            """)
            conn.commit()
    
    def _hash_token(self, token: str) -> str:
        """Hash a token for storage."""
        return hashlib.sha256(token.encode()).hexdigest()
    
    def create_token(
        self,
        name: str,
        role: Role = Role.OPERATOR,
        expires_in_days: Optional[int] = None,
        created_by: Optional[str] = None,
    ) -> tuple[str, TokenInfo]:
        """Create a new API token. Returns (plain_token, token_info)."""
        token_id = secrets.token_hex(8)
        plain_token = f"adt_{secrets.token_urlsafe(32)}"
        token_hash = self._hash_token(plain_token)
        
        now = datetime.now()
        expires_at = None
        if expires_in_days:
            expires_at = now + timedelta(days=expires_in_days)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO tokens (id, name, token_hash, role, created_at, expires_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (token_id, name, token_hash, role.value, now.isoformat(), 
                  expires_at.isoformat() if expires_at else None, created_by))
            conn.commit()
        
        info = TokenInfo(
            id=token_id,
            name=name,
            role=role,
            created_at=now,
            expires_at=expires_at,
        )
        
        return plain_token, info
    
    def validate_token(self, token: str) -> Optional[TokenInfo]:
        """Validate a token and return its info if valid."""
        if not token:
            return None
        
        # Strip "Bearer " prefix if present
        if token.startswith("Bearer "):
            token = token[7:]
        
        token_hash = self._hash_token(token)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM tokens WHERE token_hash = ?
            """, (token_hash,))
            row = cursor.fetchone()
        
        if not row:
            return None
        
        # Check if revoked
        if row["revoked"]:
            return None
        
        # Check if expired
        if row["expires_at"]:
            expires = datetime.fromisoformat(row["expires_at"])
            if expires < datetime.now():
                return None
        
        # Update last used
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE tokens SET last_used_at = ? WHERE id = ?
            """, (datetime.now().isoformat(), row["id"]))
            conn.commit()
        
        return TokenInfo(
            id=row["id"],
            name=row["name"],
            role=Role(row["role"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
            last_used_at=datetime.now(),
            revoked=False,
        )
    
    def has_permission(self, token_info: TokenInfo, permission: Permission) -> bool:
        """Check if a token has a specific permission."""
        if not token_info:
            return False
        return permission in ROLE_PERMISSIONS.get(token_info.role, set())
    
    def list_tokens(self) -> list[TokenInfo]:
        """List all tokens (without the actual token values)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM tokens ORDER BY created_at DESC
            """)
            rows = cursor.fetchall()
        
        tokens = []
        for row in rows:
            tokens.append(TokenInfo(
                id=row["id"],
                name=row["name"],
                role=Role(row["role"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
                last_used_at=datetime.fromisoformat(row["last_used_at"]) if row["last_used_at"] else None,
                revoked=bool(row["revoked"]),
            ))
        
        return tokens
    
    def revoke_token(self, token_id: str) -> bool:
        """Revoke a token by its ID."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                UPDATE tokens SET revoked = TRUE WHERE id = ?
            """, (token_id,))
            conn.commit()
            return cursor.rowcount > 0
    
    def delete_token(self, token_id: str) -> bool:
        """Permanently delete a token."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                DELETE FROM tokens WHERE id = ?
            """, (token_id,))
            conn.commit()
            return cursor.rowcount > 0
    
    def has_any_tokens(self) -> bool:
        """Check if any tokens exist (for first-run setup)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM tokens WHERE NOT revoked")
            count = cursor.fetchone()[0]
        return count > 0
    
    def create_initial_admin_token(self) -> Optional[tuple[str, TokenInfo]]:
        """Create initial admin token if none exist."""
        if self.has_any_tokens():
            return None
        return self.create_token("Initial Admin Token", role=Role.ADMIN)


# Global instance
_auth_manager: Optional[AuthManager] = None


def get_auth_manager() -> AuthManager:
    """Get the global auth manager instance."""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthManager()
    return _auth_manager
