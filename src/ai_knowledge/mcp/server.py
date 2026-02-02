"""MCP server implementation for agent-dev-tool."""

import json
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    ResourceTemplate,
    TextContent,
    Tool,
    CallToolResult,
    ListResourcesResult,
    ListToolsResult,
    ReadResourceResult,
)

from ..store import load_config, load_index
from ..tools import load_all_tools
from ..skills import load_all_skills


def create_server() -> Server:
    """Create and configure the MCP server."""
    server = Server("agent-dev-tool")
    config = load_config()
    
    # =========================================================================
    # TOOLS - Expose all registered tools as MCP tools
    # =========================================================================
    
    @server.list_tools()
    async def list_tools() -> ListToolsResult:
        """List all available tools."""
        registry = load_all_tools(config)
        tools = []
        
        for t in registry.list():
            # Build input schema from tool params
            properties = {}
            required = []
            
            for p in t.params:
                properties[p.name] = {
                    "type": _python_type_to_json(p.type),
                    "description": p.description or f"Parameter {p.name}",
                }
                if p.required:
                    required.append(p.name)
            
            tools.append(Tool(
                name=t.name,
                description=t.description,
                inputSchema={
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            ))
        
        return tools
    
    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> CallToolResult:
        """Execute a tool and return results."""
        registry = load_all_tools(config)
        t = registry.get(name)
        
        if not t:
            return [TextContent(type="text", text=f"Error: Tool not found: {name}")]
        
        try:
            result = t(**arguments)
            
            if isinstance(result, (dict, list)):
                text = json.dumps(result, indent=2, default=str)
            else:
                text = str(result)
            
            return [TextContent(type="text", text=text)]
        except Exception as e:
            return [TextContent(type="text", text=f"Error executing tool: {e}")]
    
    # =========================================================================
    # RESOURCES - Expose knowledge, skills, and context
    # =========================================================================
    
    @server.list_resources()
    async def list_resources() -> ListResourcesResult:
        """List all available resources."""
        resources = []
        
        # Global knowledge files
        global_ai = config.global_ai_dir
        if global_ai.exists():
            for md_file in global_ai.glob("*.md"):
                resources.append(Resource(
                    uri=f"adt://global/{md_file.stem}",
                    name=f"Global: {md_file.stem}",
                    description=f"Global {md_file.stem} knowledge",
                    mimeType="text/markdown",
                ))
        
        # Global skills
        skills = load_all_skills(config)
        for skill in skills:
            trigger = f" ({skill.trigger})" if skill.trigger else ""
            resources.append(Resource(
                uri=f"adt://skills/{skill.id}",
                name=f"Skill: {skill.name}{trigger}",
                description=skill.description[:100] if skill.description else "",
                mimeType="text/markdown",
            ))
        
        # Project knowledge
        for project in config.projects:
            ai_path = project.full_ai_path
            if ai_path.exists():
                for md_file in ai_path.glob("*.md"):
                    resources.append(Resource(
                        uri=f"adt://projects/{project.name}/{md_file.stem}",
                        name=f"{project.name}: {md_file.stem}",
                        description=f"Project {md_file.stem} for {project.name}",
                        mimeType="text/markdown",
                    ))
        
        # Knowledge index (ToC)
        resources.append(Resource(
            uri="adt://index",
            name="Knowledge Index",
            description="Hierarchical table of contents for all knowledge",
            mimeType="text/plain",
        ))
        
        # Tool documentation
        resources.append(Resource(
            uri="adt://tools/docs",
            name="Tool Documentation",
            description="Documentation for all available tools",
            mimeType="text/markdown",
        ))
        
        return resources
    
    @server.read_resource()
    async def read_resource(uri: str) -> ReadResourceResult:
        """Read a specific resource."""
        parts = uri.replace("adt://", "").split("/")
        
        if not parts:
            return [TextContent(type="text", text="Invalid URI")]
        
        category = parts[0]
        
        # Global knowledge
        if category == "global" and len(parts) >= 2:
            file_path = config.global_ai_dir / f"{parts[1]}.md"
            if file_path.exists():
                return [TextContent(type="text", text=file_path.read_text())]
            return [TextContent(type="text", text=f"File not found: {parts[1]}")]
        
        # Skills
        if category == "skills" and len(parts) >= 2:
            skill_id = parts[1]
            skills = load_all_skills(config)
            skill = next((s for s in skills if s.id == skill_id), None)
            if skill:
                return [TextContent(type="text", text=skill.to_prompt())]
            return [TextContent(type="text", text=f"Skill not found: {skill_id}")]
        
        # Project knowledge
        if category == "projects" and len(parts) >= 3:
            project_name = parts[1]
            file_name = parts[2]
            project = config.get_project(project_name)
            if project:
                file_path = project.full_ai_path / f"{file_name}.md"
                if file_path.exists():
                    return [TextContent(type="text", text=file_path.read_text())]
            return [TextContent(type="text", text=f"Not found: {project_name}/{file_name}")]
        
        # Knowledge index
        if category == "index":
            index = load_index()
            if index:
                return [TextContent(type="text", text=index.to_toc())]
            return [TextContent(type="text", text="Index not built. Run 'adt index' first.")]
        
        # Tool documentation
        if category == "tools" and len(parts) >= 2 and parts[1] == "docs":
            registry = load_all_tools(config)
            return [TextContent(type="text", text=registry.to_prompt())]
        
        return [TextContent(type="text", text=f"Unknown resource: {uri}")]
    
    return server


def _python_type_to_json(python_type: str) -> str:
    """Convert Python type name to JSON schema type."""
    mapping = {
        "str": "string",
        "int": "integer",
        "float": "number",
        "bool": "boolean",
        "list": "array",
        "dict": "object",
        "List": "array",
        "Dict": "object",
        "None": "null",
        "NoneType": "null",
    }
    return mapping.get(python_type, "string")


async def run_server():
    """Run the MCP server."""
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main():
    """Entry point for the MCP server."""
    import asyncio
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
