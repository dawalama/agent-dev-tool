"""MCP server for agent-dev-tool.

Exposes tools, skills, and knowledge as MCP resources for AI assistants.
"""

from .server import create_server, main

__all__ = ["create_server", "main"]
