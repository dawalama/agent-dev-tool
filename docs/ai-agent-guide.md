# AI Agent Guide to Agent Dev Tool

Instructions for AI assistants (Claude, GPT, Cursor, etc.) on how to use `adt`.

---

## Quick Reference

```bash
# Skills (high-level workflows)
adt run skill techdebt              # Find code issues
adt run skill techdebt --path=src   # Scope to directory
adt run skill review                # Review staged changes
adt run skill commit                # Generate commit message

# Tools (specific functions)
adt run tool git_status_summary     # Git status as JSON
adt run tool find_todos path=src    # Find TODOs
adt run tool git_staged_files       # List staged files

# Knowledge
adt tree                            # View knowledge structure
adt context --project myproject     # Get project context

# Learning
adt learn "Title" -i "issue" -c "correction"
```

---

## When to Use adt

### Use `adt run skill` for:
- High-level analysis tasks
- Multi-step workflows
- When user asks for `/techdebt`, `/review`, etc.

### Use `adt run tool` for:
- Single specific operations
- Getting structured data (JSON)
- Git operations, file analysis

### Use `adt learn` for:
- Recording corrections from user
- Documenting lessons learned
- Always ask user first: "Should I add this to learnings?"

---

## Available Skills

### /techdebt - Find Technical Debt

Finds TODOs, FIXMEs, duplicate code, and potential issues.

```bash
adt run skill techdebt
adt run skill techdebt --path=backend
adt run skill techdebt --json
```

Output includes:
- TODO/FIXME comments with locations
- Potential code duplicates
- Suggestions for improvement

### /review - Code Review

Reviews staged git changes.

```bash
adt run skill review
```

Use when:
- User asks for code review
- Before committing changes
- After significant modifications

### /commit - Generate Commit Message

Analyzes staged changes and generates a conventional commit message.

```bash
adt run skill commit
```

Output format:
```
type(scope): description

- Detail 1
- Detail 2
```

### /context - Context Dump

Generates comprehensive project context.

```bash
adt run skill context
```

Use when:
- Starting work on unfamiliar codebase
- Need to understand project structure
- Onboarding to new project

### /parallel - Parallel Work Setup

Sets up git worktrees for parallel task execution.

```bash
adt run skill parallel action=setup tasks="task1,task2,task3"
adt run skill parallel action=status
adt run skill parallel action=merge
```

Use when:
- Work has been planned and broken into independent tasks
- User wants to run multiple agents simultaneously

---

## Available Tools

### Git Tools

```bash
# Get staged files as list
adt run tool git_staged_files
# Returns: ["file1.py", "file2.py"]

# Get git status as JSON
adt run tool git_status_summary
# Returns: {"staged": [...], "modified": [...], "untracked": [...]}

# Get recent commits
adt run tool git_log_summary count=10
# Returns: [{"hash": "...", "message": "...", "author": "..."}]
```

### Code Analysis Tools

```bash
# Find TODO/FIXME comments
adt run tool find_todos path=src
# Returns: [{"file": "...", "line": 10, "text": "TODO: ..."}]

# Find duplicate code
adt run tool find_duplicates path=src min_lines=5
# Returns: [{"pattern": "...", "occurrences": [...]}]
```

### Worktree Tools

```bash
# List worktrees
adt run tool worktree_list
# Returns: [{"path": "...", "branch": "...", "head": "..."}]

# Add worktree
adt run tool worktree_add name="feature-x" branch="feature/x"

# Remove worktree
adt run tool worktree_remove name="feature-x"

# Set up parallel tasks
adt run tool parallel_task_setup tasks="auth,api,ui"

# Merge parallel tasks
adt run tool parallel_task_merge branches="task/auth,task/api"
```

### File Tools

```bash
# Read file content
adt run tool read_file path="src/main.py"

# List directory
adt run tool list_files path="src" pattern="*.py"
```

---

## Recording Learnings

When the user corrects you, always offer to record the learning:

### Workflow

1. User corrects a mistake
2. Ask: "Should I add this to learnings?"
3. If yes, run:

```bash
adt learn "Brief Title" \
  -i "What I did wrong" \
  -c "What I should do instead" \
  [-p project_name]  # Optional: for project-specific learning
```

### Examples

```bash
# Global learning
adt learn "Import order in Python" \
  -i "Put third-party imports before local imports" \
  -c "Standard library first, then third-party, then local"

# Project-specific learning
adt learn "API response format" \
  -i "Returned raw data without wrapper" \
  -c "Always wrap responses in {data: ..., meta: ...}" \
  -p myproject
```

---

## Checking Context

### Before Starting Work

```bash
# View knowledge hierarchy
adt tree

# Get project-specific context
adt context --project myproject

# List registered projects
adt list
```

### Read Project Rules

Project rules are in `.ai/rules.md`. Check for:
- Stack information
- Coding conventions
- Project-specific patterns

### Read Learnings

Learnings are in `.ai/learnings.md`. Contains:
- Past corrections
- Best practices discovered
- Mistakes to avoid

---

## Parallel Work Mode

When user wants parallel execution:

### 1. Setup

```bash
adt run tool parallel_task_setup tasks="auth,api,dashboard"
```

This creates separate worktrees for each task.

### 2. Inform User

```
Created worktrees:
- ~/project-task-auth/ (task/auth branch)
- ~/project-task-api/ (task/api branch)
- ~/project-task-dashboard/ (task/dashboard branch)

Each can be worked on independently. Switch directories to work on each task.
```

### 3. Check Status

```bash
adt run tool worktree_status
```

### 4. Merge

```bash
adt run tool parallel_task_merge branches="task/auth,task/api,task/dashboard"
```

---

## Output Formats

### Get JSON Output

Most commands support `--json` for structured output:

```bash
adt run skill techdebt --json
adt run tool git_status_summary --json
```

### Verbose Output

```bash
adt run skill techdebt --verbose
```

---

## Error Handling

### Tool Not Found

If a tool isn't found, suggest rebuilding the index:

```bash
adt index --refresh
```

### Skill Not Found

List available skills:

```bash
adt skill list
```

### Permission Issues

Some operations need to run from the project directory:

```bash
cd /path/to/project
adt run skill techdebt
```

---

## Best Practices

1. **Check context first** - Run `adt context` or `adt tree` when starting
2. **Use appropriate scope** - Pass `--path` to limit analysis
3. **Record learnings** - Always offer to record corrections
4. **Use JSON for parsing** - Use `--json` when you need to process output
5. **Respect project rules** - Check `.ai/rules.md` for conventions
6. **Don't guess** - If unsure, check available skills/tools with `list` commands

---

## Command Cheatsheet

| Task | Command |
|------|---------|
| Find code issues | `adt run skill techdebt` |
| Code review | `adt run skill review` |
| Generate commit | `adt run skill commit` |
| Git status | `adt run tool git_status_summary` |
| Find TODOs | `adt run tool find_todos path=src` |
| List skills | `adt skill list` |
| List tools | `adt tool list` |
| View knowledge | `adt tree` |
| Record learning | `adt learn "Title" -i "..." -c "..."` |
| Parallel setup | `adt run tool parallel_task_setup tasks="a,b,c"` |
