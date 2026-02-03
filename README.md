# Agent Dev Tool (adt)

A CLI and knowledge system for AI-assisted development. Scaffold projects, manage learnings, and execute reusable skills and tools.

## Quick Start

```bash
# Install
cd ~/agent-dev-tool
uv sync  # or: pip install -e .

# Initialize global knowledge
adt init

# Create a new project with AI-powered scaffolding
adt init myproject --desc "REST API for invoice management with PDF generation"

# Register an existing project
adt add ~/existing-project --name myproject
```

## What It Does

**1. Smart Project Scaffolding** - Describe what you want, get a ready-to-code project:
```bash
adt init myapp --desc "Real-time dashboard with user auth"
# → Infers: fullstack, fastapi, react, postgres, docker
# → Creates: app structure, Dockerfile, CI, .ai/ config
```

**2. Knowledge Management** - Global and project-specific rules/learnings for AI:
```
~/.ai/              # Global knowledge
  rules.md          # Universal AI rules
  learnings.md      # Corrections that apply everywhere
  
myproject/.ai/      # Project-specific
  rules.md          # Project conventions
  learnings.md      # Project-specific lessons
  context.md        # Quick reference for AI
```

**3. Skills & Tools** - Reusable AI workflows and code functions:
```bash
adt run skill techdebt     # Find code issues
adt run skill review       # Code review
adt run tool find_todos    # Find TODO comments
```

## Installation

### Prerequisites
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- [Ollama](https://ollama.com/) (optional, for smart project inference)

### Install

```bash
git clone https://github.com/dawalama/agent-dev-tool.git
cd agent-dev-tool
uv sync  # or: pip install -e .

# Pull a local model for smart features (optional)
ollama pull llama3.2:3b
```

### Verify Installation

```bash
adt --help
adt init  # Creates ~/.ai/ with default rules
```

## Commands

### Project Scaffolding

```bash
# Create new project (AI analyzes description)
adt init myapi --desc "GraphQL API for e-commerce with payments"

# Override inferred settings
adt init myapp --desc "..." --type=backend --backend=fastapi

# Skip confirmation
adt init myapp --desc "..." -y

# Available options:
#   --type: backend, frontend, fullstack
#   --backend: fastapi, express, django
#   --frontend: react, vue, nextjs
#   --database: postgres, mongodb, sqlite
#   --deploy: docker, render, vercel
```

### Knowledge Management

```bash
adt init                    # Initialize ~/.ai/
adt add <path> [-n name]    # Register existing project
adt remove <name>           # Unregister project
adt list                    # List registered projects
adt index --refresh         # Rebuild knowledge index
adt tree                    # View knowledge hierarchy
adt context [-p project]    # Get AI context
```

### Learning from Corrections

```bash
# Add a learning (global)
adt learn "Title" -i "what went wrong" -c "correct approach"

# Add project-specific learning
adt learn "Title" -i "..." -c "..." -p myproject

# Interactive mode
adt learn "Title" -I
```

### Skills (High-Level Workflows)

```bash
adt skill list              # List available skills
adt skill show techdebt     # View skill details
adt skill new "My Skill"    # Create new skill
adt run skill techdebt      # Execute skill
adt run skill review --path=src
```

### Tools (Code Functions)

```bash
adt tool list               # List available tools
adt tool show find_todos    # View tool details
adt tool new "my_tool"      # Create new tool
adt run tool find_todos path=src
adt run tool git_status_summary --json
```

## Built-in Skills

| Skill | Trigger | Description |
|-------|---------|-------------|
| Tech Debt | `/techdebt` | Find TODOs, duplicates, code issues |
| Code Review | `/review` | Review staged changes |
| Commit Helper | `/commit` | Generate commit message |
| Context Dump | `/context` | Generate comprehensive context |
| Parallel Work | `/parallel` | Set up git worktrees for parallel tasks |

## Built-in Tools

| Tool | Description |
|------|-------------|
| `git_staged_files` | List staged files |
| `git_status_summary` | Git status as JSON |
| `git_log_summary` | Recent commits |
| `find_todos` | Find TODO/FIXME comments |
| `find_duplicates` | Find duplicate code |
| `worktree_list` | List git worktrees |
| `worktree_add` | Create worktree |
| `parallel_task_setup` | Set up parallel task branches |
| `parallel_task_merge` | Merge completed tasks |

## Creating Custom Skills

```markdown
# ~/.ai/skills/my-skill.md
---
name: My Custom Skill
trigger: /myskill
tags: custom
---

Description of what this skill does.

## Tools Used
- `tool:find_todos`
- `tool:git_status_summary`

## Steps
1. First, analyze the codebase
2. Then, generate a report
3. Finally, suggest improvements

## Example
User: /myskill
AI: Running analysis...
```

## Creating Custom Tools

```python
# ~/.ai/tools/my_tools.py
from ai_knowledge.tools import tool

@tool(name="my_function", description="Does something useful", tags=["custom"])
def my_function(path: str = ".") -> dict:
    """
    Longer description of the tool.
    
    Args:
        path: Directory to analyze
        
    Returns:
        Analysis results
    """
    return {"path": path, "result": "done"}
```

After creating, rebuild the index:
```bash
adt index --refresh
```

## Package Managers

Projects are scaffolded with modern, fast package managers:

| Stack | Package Manager |
|-------|----------------|
| Python | [uv](https://docs.astral.sh/uv/) |
| Node.js | [pnpm](https://pnpm.io/) |

## MCP Integration

For AI assistants that support [Model Context Protocol](https://modelcontextprotocol.io/):

```json
// ~/.cursor/mcp.json
{
  "mcpServers": {
    "agent-dev-tool": {
      "command": "python",
      "args": ["-m", "ai_knowledge.mcp.server"],
      "env": {
        "PYTHONPATH": "/path/to/agent-dev-tool/src"
      }
    }
  }
}
```

See [docs/mcp-setup.md](docs/mcp-setup.md) for details.

## Documentation

- [Human Guide](docs/human-guide.md) - Complete user guide
- [AI Agent Guide](docs/ai-agent-guide.md) - Instructions for AI assistants
- [MCP Setup](docs/mcp-setup.md) - Model Context Protocol integration

## Philosophy

- **AI-first** - Designed for AI-assisted development workflows
- **No vector DB** - Hierarchical reasoning over structure, not similarity search
- **Git-friendly** - Everything is markdown and Python files
- **Two layers** - Skills (what to do) + Tools (how to do it)
- **Fast tooling** - Uses `uv` and `pnpm` for speed
