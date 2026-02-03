# Human Guide to Agent Dev Tool

Complete guide for developers using `adt` for AI-assisted development.

## Table of Contents

1. [Installation](#installation)
2. [Creating New Projects](#creating-new-projects)
3. [Managing Knowledge](#managing-knowledge)
4. [Using Skills](#using-skills)
5. [Using Tools](#using-tools)
6. [Parallel Work Mode](#parallel-work-mode)
7. [Working with AI Agents](#working-with-ai-agents)
8. [Customization](#customization)

---

## Installation

### Prerequisites

- Python 3.11 or higher
- Git
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

Optional:
- [Ollama](https://ollama.com/) for smart project inference
- [pnpm](https://pnpm.io/) for Node.js projects

### Install adt

```bash
# Clone the repository
git clone https://github.com/dawalama/agent-dev-tool.git
cd agent-dev-tool

# Install with uv (recommended)
uv sync

# Or with pip
pip install -e .
```

### Install Ollama (Optional)

For AI-powered project scaffolding:

```bash
# macOS
brew install ollama

# Start Ollama
ollama serve

# Pull a model (in another terminal)
ollama pull llama3.2:3b
```

### Initialize Global Knowledge

```bash
adt init
```

This creates `~/.ai/` with:
- `rules.md` - Global rules for AI assistants
- `learnings.md` - Cross-project lessons
- `skills/` - Reusable AI workflows
- `tools/` - Python utility functions

---

## Creating New Projects

### Basic Usage

```bash
# Describe your project, let AI infer the stack
adt init myproject --desc "REST API for managing invoices with PDF generation"
```

The AI analyzes your description and suggests:
- Project type (backend/frontend/fullstack)
- Stack (FastAPI, React, etc.)
- Database (Postgres, MongoDB, etc.)
- Deployment (Docker, Render, etc.)
- Features (auth, pdf, email, etc.)

### What Gets Created

```
myproject/
├── .ai/                    # AI configuration
│   ├── rules.md            # Project-specific rules
│   ├── learnings.md        # Project lessons
│   └── context.md          # Quick reference
├── .github/workflows/      # CI/CD
├── app/                    # Backend code (FastAPI)
│   ├── api/
│   ├── core/
│   ├── models/
│   └── services/
├── frontend/               # Frontend (if fullstack)
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── pyproject.toml
└── README.md
```

### Override Defaults

```bash
# Specify type explicitly
adt init myapp --desc "..." --type=backend

# Choose specific stack
adt init myapp --desc "..." --backend=express --database=mongodb

# Skip confirmation
adt init myapp --desc "..." -y

# Don't register with adt
adt init myapp --desc "..." --no-register
```

### Edit During Confirmation

When prompted, you can edit the configuration:

```
Create project with this configuration? [Y/n]: n
Edit configuration? [Y/n]: y
Name [myapp]: my-awesome-app
Type [fullstack]: backend
Backend [fastapi]: 
...
```

### Project Naming

If you use a generic name like `myapi` but mention a specific name in your description:

```bash
adt init myapi --desc "Let's call it invoice-manager. It should..."
# → Uses "invoice-manager" as the project name
```

---

## Managing Knowledge

### Two-Tier System

**Global** (`~/.ai/`): Rules and learnings that apply everywhere
**Project** (`project/.ai/`): Specific to one project

### Register Existing Projects

```bash
# Register a project
adt add ~/code/myproject --name myproject --desc "My project"

# With tags for organization
adt add ~/code/myproject -n myproject --tags "python,api,production"
```

### View Registered Projects

```bash
adt list
```

### Unregister Projects

```bash
adt remove myproject
# Note: This doesn't delete files, just unregisters from adt
```

### View Knowledge Tree

```bash
# Visual tree
adt tree

# As JSON
adt toc --format json
```

### Rebuild Index

After adding or modifying files in `.ai/`:

```bash
adt index --refresh
```

### Auto-Watch for Changes

```bash
adt watch
# Automatically rebuilds index when .ai/ files change
```

---

## Using Skills

Skills are high-level AI workflows defined in markdown.

### List Available Skills

```bash
adt skill list
```

### Run a Skill

```bash
# Run tech debt analysis
adt run skill techdebt

# Scope to a directory
adt run skill techdebt --path=backend

# Get JSON output
adt run skill techdebt --json
```

### View Skill Details

```bash
adt skill show techdebt
```

### Built-in Skills

| Skill | What it Does |
|-------|--------------|
| `techdebt` | Finds TODOs, FIXMEs, duplicate code, potential issues |
| `review` | Reviews staged git changes |
| `commit` | Generates conventional commit message |
| `context` | Dumps comprehensive project context |
| `parallel` | Sets up git worktrees for parallel work |

### Create Custom Skills

```bash
adt skill new "Database Migration" --trigger /migrate
```

Edit the created file at `~/.ai/skills/database-migration.md`:

```markdown
---
name: Database Migration
trigger: /migrate
tags: database, devops
---

Helps create and run database migrations.

## Tools Used
- `tool:git_status_summary`

## Steps
1. Check current migration status
2. Generate new migration file
3. Review changes
4. Apply migration

## Inputs
- `action` (required): create, run, rollback
- `name` (optional): Migration name
```

---

## Using Tools

Tools are Python functions that can be called directly.

### List Available Tools

```bash
adt tool list
```

### Run a Tool

```bash
# Basic usage
adt run tool find_todos

# With arguments
adt run tool find_todos path=src

# JSON output
adt run tool git_status_summary --json
```

### View Tool Details

```bash
adt tool show find_todos
```

### Create Custom Tools

```bash
adt tool new "check_dependencies" --desc "Check for outdated dependencies"
```

Edit the created file:

```python
# ~/.ai/tools/check_dependencies.py
from ai_knowledge.tools import tool

@tool(
    name="check_dependencies",
    description="Check for outdated dependencies",
    tags=["deps", "maintenance"]
)
def check_dependencies(path: str = ".") -> dict:
    """
    Check for outdated Python dependencies.
    
    Args:
        path: Project path
        
    Returns:
        Dict with outdated packages
    """
    import subprocess
    result = subprocess.run(
        ["pip", "list", "--outdated", "--format=json"],
        capture_output=True,
        text=True,
        cwd=path
    )
    import json
    return json.loads(result.stdout) if result.returncode == 0 else []
```

Rebuild index:
```bash
adt index --refresh
```

---

## Parallel Work Mode

Use git worktrees to work on multiple tasks simultaneously.

### When to Use

- After planning, work is broken into independent tasks
- Each task takes 1-2 hours
- Tasks don't conflict (different files/features)
- You want to run multiple AI agents simultaneously

### Setup Parallel Tasks

```bash
# Create worktrees for each task
adt run tool parallel_task_setup tasks="auth,api,dashboard"
```

This creates:
```
~/project/                  # Main branch (unchanged)
~/project-task-auth/        # task/auth branch
~/project-task-api/         # task/api branch
~/project-task-dashboard/   # task/dashboard branch
```

### Check Status

```bash
adt run tool worktree_status
```

### Work on Tasks

Open each worktree in a separate terminal/editor:
```bash
cd ~/project-task-auth
# Work on auth feature...
git add . && git commit -m "feat(auth): implement login"
```

### Merge When Done

```bash
adt run tool parallel_task_merge branches="task/auth,task/api,task/dashboard"
```

### Cleanup

After merging:
```bash
adt run tool worktree_remove name="task-auth"
```

---

## Working with AI Agents

### Setup for cursor-agent (CLI)

The AI agent can run `adt` commands directly. Ensure your `~/.ai/rules.md` includes:

```markdown
## Agent Dev Tool (adt)

You have access to `adt` - a CLI for knowledge, skills, and tools:

```bash
# Run skills
adt run skill techdebt
adt run skill review

# Run tools
adt run tool git_status_summary
adt run tool find_todos path=src

# Add learnings
adt learn "Title" -i "issue" -c "correction"
```
```

### Setup for Cursor IDE (MCP)

Add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "agent-dev-tool": {
      "command": "python",
      "args": ["-m", "ai_knowledge.mcp.server"],
      "env": {
        "PYTHONPATH": "/Users/yourname/agent-dev-tool/src"
      }
    }
  }
}
```

Restart Cursor after adding.

### Teaching AI from Corrections

When the AI makes a mistake:

1. Correct the AI
2. Ask: "Should I add this to learnings?"
3. AI runs: `adt learn "Title" -i "what was wrong" -c "what to do instead"`

This creates an entry in `learnings.md` that the AI will reference in future sessions.

---

## Customization

### Global Rules

Edit `~/.ai/rules.md` to customize AI behavior:

```markdown
## Code Style
- Use type hints in Python
- Prefer functional over OOP
- Max line length: 100

## Behavior
- Always run tests before committing
- Use conventional commits
```

### Project Rules

Each project can have its own rules in `project/.ai/rules.md`:

```markdown
## Stack
- Backend: FastAPI with SQLAlchemy
- Frontend: React with TypeScript
- Database: PostgreSQL

## Conventions
- API routes in `app/api/v1/`
- Use Pydantic for validation
- All endpoints need OpenAPI docs
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `ADT_GLOBAL_DIR` | Override global .ai/ location (default: `~/.ai`) |
| `ADT_CONFIG_DIR` | Override config location (default: `~/.config/agent-dev-tool`) |

---

## Troubleshooting

### adt command not found

Ensure it's installed and in PATH:
```bash
pip install -e /path/to/agent-dev-tool
which adt
```

### Ollama not available

Skills will still work, but `adt init` will use heuristics instead of LLM:
```bash
ollama serve  # Start Ollama
ollama list   # Check models
```

### Index out of date

Rebuild after changing `.ai/` files:
```bash
adt index --refresh
```

### Tool not found

Check if registered:
```bash
adt tool list
```

Rebuild index if needed:
```bash
adt index --refresh
```
