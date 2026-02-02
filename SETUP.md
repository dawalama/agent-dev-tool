# Agent Dev Tool Setup Guide

## 1. Installation (Already Done)

```bash
cd ~/agent-dev-tool
pip install -e .
adt init
```

## 2. Configure Cursor MCP

Add to `~/.cursor/mcp.json` (create if doesn't exist):

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

Then restart Cursor.

## 3. Verify MCP is Working

In Cursor, the AI should now have access to:
- All tools (git_staged_files, find_todos, worktree_add, etc.)
- All resources (rules, learnings, skills, project context)

Test by asking: "List the available MCP tools from agent-dev-tool"

## 4. Current State

### Registered Projects
```bash
adt list
```

### Available Skills
| Trigger | What it does |
|---------|--------------|
| `/techdebt` | Find code issues, TODOs, duplication |
| `/review` | Code review staged changes |
| `/commit` | Generate commit message |
| `/context` | Generate full context dump |
| `/parallel` | Set up parallel work with worktrees |

### Available Tools (21 total)
```bash
adt tool list
```

Key tools:
- `git_*` - Git operations (status, staged, log, diff)
- `worktree_*` - Parallel work with git worktrees
- `find_*` - Code analysis (todos, duplicates)
- `file_*` - File operations (read, list, tree)

## 5. Working with Me

### Starting a Session
```
adt context --project <name>
```
Or via MCP: Read resource `adt://projects/<name>/context`

### Sequential Work (Default)
1. Discuss task
2. Work on it
3. Complete, test, commit
4. Next task

### Parallel Work (After Planning)
1. Break work into independent tasks
2. `/parallel action=setup tasks="task1,task2,task3"`
3. Each task gets its own worktree/branch
4. Multiple agents can work simultaneously
5. `/parallel action=merge` when done

### When I Make a Mistake
Say: "Add this to learnings"
I'll run: `adt learn "Title" -i "..." -c "..."`

### Quick Commands
```bash
adt tree                    # View knowledge hierarchy
adt skill show /techdebt    # See skill details
adt tool run git_status_summary  # Execute a tool
adt learn "..." -i "..." -c "..."  # Add learning
```

## 6. Directory Locations

| Path | Purpose |
|------|---------|
| `~/.ai/` | Global rules, learnings, skills, tools |
| `~/.ai/skills/` | Global skill definitions (markdown) |
| `~/.ai/tools/` | Global tool functions (Python) |
| `~/.config/agent-dev-tool/` | Config and index |
| `<project>/.ai/` | Project-specific knowledge |
