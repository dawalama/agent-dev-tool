"""Middleware for ADT Command Center (auth, rate limiting, etc.)."""

import time
import secrets
from collections import defaultdict
from datetime import datetime
from typing import Callable, Optional

from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .auth import get_auth_manager, Permission, TokenInfo, ROLE_PERMISSIONS
from .audit import audit, AuditAction


class RateLimiter:
    """Simple in-memory rate limiter."""
    
    def __init__(
        self,
        requests_per_minute: int = 60,
        requests_per_second: int = 10,
    ):
        self.rpm = requests_per_minute
        self.rps = requests_per_second
        self._minute_requests: dict[str, list[float]] = defaultdict(list)
        self._second_requests: dict[str, list[float]] = defaultdict(list)
    
    def check(self, client_id: str) -> tuple[bool, Optional[str]]:
        """Check if request is allowed. Returns (allowed, reason)."""
        now = time.time()
        
        # Check per-second limit
        second_ago = now - 1
        self._second_requests[client_id] = [
            t for t in self._second_requests[client_id] if t > second_ago
        ]
        if len(self._second_requests[client_id]) >= self.rps:
            return False, f"Rate limit exceeded: {self.rps} requests/second"
        
        # Check per-minute limit
        minute_ago = now - 60
        self._minute_requests[client_id] = [
            t for t in self._minute_requests[client_id] if t > minute_ago
        ]
        if len(self._minute_requests[client_id]) >= self.rpm:
            return False, f"Rate limit exceeded: {self.rpm} requests/minute"
        
        # Record this request
        self._second_requests[client_id].append(now)
        self._minute_requests[client_id].append(now)
        
        return True, None
    
    def cleanup(self):
        """Remove old entries to prevent memory bloat."""
        now = time.time()
        minute_ago = now - 60
        
        for client_id in list(self._minute_requests.keys()):
            self._minute_requests[client_id] = [
                t for t in self._minute_requests[client_id] if t > minute_ago
            ]
            if not self._minute_requests[client_id]:
                del self._minute_requests[client_id]
                if client_id in self._second_requests:
                    del self._second_requests[client_id]


# Path patterns that don't require authentication
PUBLIC_PATHS = {
    "/",           # Dashboard (will check auth via JS)
    "/health",     # Health check
    "/docs",       # OpenAPI docs
    "/openapi.json",
    "/redoc",
}

# Path patterns that have optional auth (work without token but with limited access)
OPTIONAL_AUTH_PATHS = {
    "/ws",         # WebSocket (auth via message)
}

# Endpoint to permission mapping
ENDPOINT_PERMISSIONS: dict[tuple[str, str], Permission] = {
    # Agents
    ("GET", "/agents"): Permission.AGENTS_READ,
    ("POST", "/agents/spawn"): Permission.AGENTS_SPAWN,
    ("POST", "/agents/{project}/stop"): Permission.AGENTS_STOP,
    ("POST", "/agents/{project}/retry"): Permission.AGENTS_SPAWN,
    ("GET", "/agents/{project}"): Permission.AGENTS_READ,
    ("GET", "/agents/{project}/logs"): Permission.LOGS_READ,
    ("POST", "/agents/{project}/assign"): Permission.AGENTS_SPAWN,
    
    # Tasks
    ("GET", "/tasks"): Permission.TASKS_READ,
    ("POST", "/tasks"): Permission.TASKS_CREATE,
    ("GET", "/tasks/{task_id}"): Permission.TASKS_READ,
    ("POST", "/tasks/{task_id}/cancel"): Permission.TASKS_CANCEL,
    ("GET", "/tasks/stats"): Permission.TASKS_READ,
    
    # Projects
    ("GET", "/projects"): Permission.PROJECTS_READ,
    
    # Status
    ("GET", "/status"): Permission.STATUS_READ,
    
    # Events
    ("GET", "/events"): Permission.LOGS_READ,
    
    # Config (admin only)
    ("GET", "/config"): Permission.CONFIG_WRITE,
    ("POST", "/config"): Permission.CONFIG_WRITE,
    
    # Tokens (admin only)
    ("GET", "/tokens"): Permission.TOKENS_MANAGE,
    ("POST", "/tokens"): Permission.TOKENS_MANAGE,
    ("DELETE", "/tokens/{token_id}"): Permission.TOKENS_MANAGE,
    
    # Audit (admin only)
    ("GET", "/audit"): Permission.TOKENS_MANAGE,
}


def get_client_id(request: Request) -> str:
    """Get a unique identifier for the client."""
    # Use token if available, otherwise IP
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return f"token:{auth_header[7:20]}"  # First part of token
    
    # Fall back to IP
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return f"ip:{forwarded.split(',')[0].strip()}"
    
    client = request.client
    return f"ip:{client.host if client else 'unknown'}"


def match_path_pattern(path: str, pattern: str) -> bool:
    """Check if a path matches a pattern with {param} placeholders."""
    path_parts = path.strip("/").split("/")
    pattern_parts = pattern.strip("/").split("/")
    
    if len(path_parts) != len(pattern_parts):
        return False
    
    for path_part, pattern_part in zip(path_parts, pattern_parts):
        if pattern_part.startswith("{") and pattern_part.endswith("}"):
            continue  # Wildcard match
        if path_part != pattern_part:
            return False
    
    return True


def get_required_permission(method: str, path: str) -> Optional[Permission]:
    """Get the permission required for an endpoint."""
    # Check exact match first
    key = (method, path)
    if key in ENDPOINT_PERMISSIONS:
        return ENDPOINT_PERMISSIONS[key]
    
    # Check pattern matches
    for (ep_method, ep_pattern), permission in ENDPOINT_PERMISSIONS.items():
        if ep_method == method and match_path_pattern(path, ep_pattern):
            return permission
    
    return None


class AuthMiddleware(BaseHTTPMiddleware):
    """Authentication and authorization middleware."""
    
    def __init__(self, app, auth_enabled: bool = True):
        super().__init__(app)
        self.auth_enabled = auth_enabled
        self.auth_manager = get_auth_manager()
        self.rate_limiter = RateLimiter()
    
    async def dispatch(self, request: Request, call_next: Callable):
        # Generate request ID for tracing
        request_id = secrets.token_hex(8)
        request.state.request_id = request_id
        
        path = request.url.path
        method = request.method
        client_id = get_client_id(request)
        client_ip = request.client.host if request.client else None
        
        # Rate limiting (always on)
        allowed, reason = self.rate_limiter.check(client_id)
        if not allowed:
            audit(
                AuditAction.SECURITY_RATE_LIMIT,
                actor_type="client",
                actor_id=client_id,
                actor_ip=client_ip,
                request_id=request_id,
                channel="api",
                status="denied",
                error=reason,
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": reason},
            )
        
        # Skip auth for public paths
        if path in PUBLIC_PATHS or path.startswith("/docs") or path.startswith("/redoc"):
            return await call_next(request)
        
        # Skip auth if disabled (dev mode)
        if not self.auth_enabled:
            request.state.token_info = None
            return await call_next(request)
        
        # Check for auth token
        auth_header = request.headers.get("Authorization", "")
        token_info: Optional[TokenInfo] = None
        
        if auth_header:
            token_info = self.auth_manager.validate_token(auth_header)
            if token_info:
                request.state.token_info = token_info
            elif path not in OPTIONAL_AUTH_PATHS:
                audit(
                    AuditAction.AUTH_LOGIN_FAILED,
                    actor_type="client",
                    actor_id=client_id,
                    actor_ip=client_ip,
                    request_id=request_id,
                    channel="api",
                    status="denied",
                    error="Invalid or expired token",
                )
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Invalid or expired token"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
        elif path not in OPTIONAL_AUTH_PATHS:
            # No token provided for protected endpoint
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Authentication required"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Check permission
        required_permission = get_required_permission(method, path)
        if required_permission and token_info:
            if not self.auth_manager.has_permission(token_info, required_permission):
                audit(
                    AuditAction.AUTH_DENIED,
                    actor_type="user",
                    actor_id=token_info.id,
                    actor_ip=client_ip,
                    request_id=request_id,
                    channel="api",
                    status="denied",
                    error=f"Missing permission: {required_permission.value}",
                    resource_type="endpoint",
                    resource_id=path,
                )
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": f"Permission denied: {required_permission.value}"},
                )
        
        # Store info in request state for handlers
        request.state.token_info = token_info
        request.state.client_ip = client_ip
        
        return await call_next(request)


def require_permission(permission: Permission):
    """Decorator to require a specific permission for an endpoint."""
    def decorator(func: Callable):
        async def wrapper(request: Request, *args, **kwargs):
            token_info = getattr(request.state, "token_info", None)
            if not token_info:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                )
            
            auth_manager = get_auth_manager()
            if not auth_manager.has_permission(token_info, permission):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission denied: {permission.value}",
                )
            
            return await func(request, *args, **kwargs)
        
        return wrapper
    return decorator
