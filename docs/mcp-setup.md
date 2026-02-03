# MCP Integration Guide

Set up Agent Dev Tool with Model Context Protocol for direct AI integration.

## What is MCP?

[Model Context Protocol](https://modelcontextprotocol.io/) allows AI assistants to directly call tools and read resources without going through the command line.

**Benefits:**
- AI can call tools directly (no shell commands needed)
- Structured data exchange
- Access to knowledge resources

**When to use MCP vs CLI:**
- **MCP**: Cursor IDE, Claude Desktop, other MCP-compatible clients
- **CLI**: cursor-agent, terminal-based workflows, any AI that can run shell commands

---

## Cursor IDE Setup

### 1. Find Your MCP Config

Cursor stores MCP config at:
- macOS/Linux: `~/.cursor/mcp.json`
- Windows: `%APPDATA%\Cursor\mcp.json`

Create the file if it doesn't exist.

### 2. Add Configuration

```json
{
  "mcpServers": {
    "agent-dev-tool": {
      "command": "python",
      "args": ["-m", "ai_knowledge.mcp.server"],
      "env": {
        "PYTHONPATH": "/Users/YOUR_USERNAME/agent-dev-tool/src"
      }
    }
  }
}
```

**Important:** Replace `/Users/YOUR_USERNAME/agent-dev-tool` with your actual path.

### 3. Restart Cursor

Completely quit and reopen Cursor for changes to take effect.

### 4. Verify

In Cursor, the AI should now have access to:
- All registered tools
- Knowledge resources (rules, learnings)
- Skill definitions

---

## Alternative: Using adt-mcp Command

If `adt` is installed globally:

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

This requires `adt-mcp` to be in your PATH.

---

## What MCP Exposes

### Tools

All registered tools are available for direct AI invocation:

| Tool | Description |
|------|-------------|
| `git_staged_files` | Get list of staged files |
| `git_status_summary` | Get git status as JSON |
| `git_log_summary` | Get recent commits |
| `find_todos` | Find TODO/FIXME comments |
| `find_duplicates` | Find duplicate code |
| `worktree_list` | List git worktrees |
| `worktree_add` | Create a worktree |
| `worktree_remove` | Remove a worktree |
| `parallel_task_setup` | Set up parallel work |
| `parallel_task_merge` | Merge parallel tasks |

Plus any custom tools you've created.

### Resources

Resources are readable content the AI can access:

| URI | Description |
|-----|-------------|
| `adt://global/rules` | Global AI rules |
| `adt://global/learnings` | Global learnings |
| `adt://skills/{id}` | Skill definition |
| `adt://projects/{name}/rules` | Project-specific rules |
| `adt://projects/{name}/learnings` | Project learnings |
| `adt://projects/{name}/context` | Project context |
| `adt://index` | Full knowledge tree |
| `adt://tools/docs` | Tool documentation |

---

## Troubleshooting

### MCP Server Not Starting

Check if the module can be imported:

```bash
PYTHONPATH=/path/to/agent-dev-tool/src python -c "from ai_knowledge.mcp.server import main; print('OK')"
```

### Tools Not Showing

1. Rebuild the index:
   ```bash
   adt index --refresh
   ```

2. Check tool registration:
   ```bash
   adt tool list
   ```

### Cursor Not Detecting MCP

1. Ensure `mcp.json` is valid JSON
2. Restart Cursor completely (not just reload)
3. Check Cursor's developer console for errors

### Permission Errors

Ensure the Python environment has access to your project directories.

---

## For Other MCP Clients

The MCP server follows the standard protocol. Configuration varies by client, but the server command is always:

```bash
python -m ai_knowledge.mcp.server
```

With `PYTHONPATH` set to include the `src` directory.

---

## Testing MCP Locally

You can test the MCP server manually:

```bash
cd /path/to/agent-dev-tool
PYTHONPATH=src python -m ai_knowledge.mcp.server
```

The server communicates over stdio, so you'll see it waiting for input. Press Ctrl+C to exit.

---

## When NOT to Use MCP

If you're using:
- `cursor-agent` (CLI-based) - Use `adt` commands directly
- Terminal AI workflows - Use `adt` commands
- Scripts or automation - Use `adt` commands

MCP is primarily for GUI-based AI assistants that support the protocol.
