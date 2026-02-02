# Agent Dev Tool (adt)

A hierarchical knowledge management system for AI-assisted development with MCP integration.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         AI Assistant                            │
│                    (Cursor, Claude, etc.)                       │
└─────────────────────────┬───────────────────────────────────────┘
                          │ MCP Protocol
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Agent Dev Tool                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │  Knowledge   │  │    Skills    │  │       Tools          │   │
│  │  (markdown)  │  │  (markdown)  │  │      (Python)        │   │
│  │              │  │              │  │                      │   │
│  │ • rules      │  │ • /techdebt  │  │ • git_staged_files() │   │
│  │ • learnings  │  │ • /review    │  │ • find_todos()       │   │
│  │ • context    │  │ • /parallel  │  │ • worktree_add()     │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Installation

```bash
cd ~/agent-dev-tool
pip install -e .

# Initialize global knowledge
adt init

# Register a project
adt add ~/my-project --name myproject
```

## MCP Integration

### Cursor Setup

Add to your Cursor MCP settings (`~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "agent-dev-tool": {
      "command": "adt-mcp",
      "args": []
    }
  }
}
```

### What MCP Exposes

**Tools** (directly callable by AI):
- All registered tools: `git_staged_files`, `find_todos`, `worktree_add`, etc.
- AI can call these directly without user intervention

**Resources** (readable by AI):
- `adt://global/rules` - Global rules
- `adt://global/learnings` - Global learnings
- `adt://skills/<id>` - Skill definitions
- `adt://projects/<name>/rules` - Project rules
- `adt://index` - Full knowledge tree
- `adt://tools/docs` - Tool documentation

## Work Modes

### Sequential Mode (Default)
Single task at a time. Good for exploration, debugging, learning.

### Parallel Mode
Use git worktrees for simultaneous work on multiple tasks.

```bash
# After planning, set up parallel tasks
adt tool run parallel_task_setup tasks="auth,api,frontend"

# Creates:
# ~/project/              (main branch)
# ~/project-task-auth/    (task/auth branch)
# ~/project-task-api/     (task/api branch)
# ~/project-task-frontend/ (task/frontend branch)

# Check status
adt tool run worktree_status

# Merge when done
adt tool run parallel_task_merge branches="task/auth,task/api,task/frontend"
```

**When to use parallel mode:**
- Work has been broken into independent tasks
- Each task is 1-2 hours of work
- Multiple AI agents or sessions can work simultaneously
- Tasks have clear boundaries

## Directory Structure

```
~/.ai/                          # Global knowledge
├── rules.md                    # Universal rules
├── learnings.md                # Cross-project lessons
├── skills/                     # AI workflows
│   ├── techdebt.md
│   ├── code-review.md
│   ├── commit-helper.md
│   └── parallel-work.md
└── tools/                      # Python functions
    ├── git_utils.py
    ├── code_analysis.py
    ├── file_utils.py
    └── worktree.py

~/project/.ai/                  # Project-specific
├── rules.md
├── learnings.md
├── context.md
├── skills/
└── tools/

~/.config/agent-dev-tool/
├── config.json                 # Registered projects
└── index.json                  # Knowledge tree index
```

## CLI Commands

### Knowledge
```bash
adt init                    # Initialize ~/.ai/
adt add <path>              # Register project
adt list                    # List projects
adt index --refresh         # Rebuild index
adt tree                    # View knowledge tree
adt context --project X     # Get project context
```

### Learning
```bash
adt learn "Title" -i "issue" -c "correction" [-p project]
```

### Skills
```bash
adt skill list              # List skills
adt skill show /techdebt    # View skill
adt skill new "Name"        # Create skill
```

### Tools
```bash
adt tool list               # List tools
adt tool run <name> [args]  # Execute tool
adt tool new "name"         # Create tool
adt tool docs               # Generate docs
```

## Built-in Skills

| Trigger | Description |
|---------|-------------|
| `/techdebt` | Find technical debt, duplication, TODOs |
| `/review` | Code review on staged changes |
| `/commit` | Generate conventional commit message |
| `/context` | Generate comprehensive context dump |
| `/parallel` | Set up parallel work with worktrees |

## Built-in Tools

| Tool | Description |
|------|-------------|
| `git_staged_files` | Get staged file list |
| `git_status_summary` | Get git status as JSON |
| `git_log_summary` | Get recent commits |
| `find_todos` | Find TODO/FIXME comments |
| `find_duplicates` | Find duplicate code |
| `worktree_list` | List git worktrees |
| `worktree_add` | Create worktree |
| `parallel_task_setup` | Set up parallel tasks |
| `parallel_task_merge` | Merge parallel tasks |

## Creating Custom Tools

```python
# ~/.ai/tools/my_tools.py
from ai_knowledge.tools import tool

@tool(name="my_function", description="Does something", tags=["custom"])
def my_function(param: str) -> dict:
    """Implementation here."""
    return {"result": param}
```

Rebuild index: `adt index --refresh`

## Creating Custom Skills

```markdown
# ~/.ai/skills/my-skill.md
---
name: My Skill
trigger: /myskill
tags: custom
---

Description of the skill.

## Tools Used
- `tool:my_function`

## Steps
1. Do this
2. Then that
```

## Philosophy

- **No vector DB** - Reasoning over structure, not similarity
- **Two layers** - Skills (what) + Tools (how)
- **Git-friendly** - Everything is markdown/Python
- **Tool-agnostic** - Works with any AI via MCP
- **Parallel-ready** - Git worktrees for concurrent work
