"""CLI interface for agent-dev-tool."""

import json
import os
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from .indexer import build_full_index
from .models import GlobalConfig, KnowledgeNode, NodeType, ProjectConfig
from .store import (
    get_config_path,
    get_index_path,
    load_config,
    load_index,
    save_config,
    save_index,
)

app = typer.Typer(
    name="adt",
    help="Agent Dev Tool - Hierarchical knowledge management for AI-assisted development",
    no_args_is_help=True,
)
console = Console()


@app.command()
def init(
    name: Annotated[Optional[str], typer.Argument(help="Project name (omit for global init)")] = None,
    description: Annotated[Optional[str], typer.Option("--desc", "-d", help="Project description for AI analysis")] = None,
    path: Annotated[Optional[Path], typer.Option("--path", "-p", help="Project path (defaults to ./<name>)")] = None,
    proj_type: Annotated[Optional[str], typer.Option("--type", "-t", help="Override: backend, frontend, fullstack")] = None,
    backend: Annotated[Optional[str], typer.Option("--backend", "-b", help="Override: fastapi, express, django")] = None,
    frontend: Annotated[Optional[str], typer.Option("--frontend", "-f", help="Override: react, vue, nextjs")] = None,
    database: Annotated[Optional[str], typer.Option("--database", help="Override: postgres, mongodb, sqlite")] = None,
    deployment: Annotated[Optional[str], typer.Option("--deploy", help="Override: docker, render, vercel")] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
    no_register: Annotated[bool, typer.Option("--no-register", help="Don't register with adt")] = False,
):
    """Initialize a new project or global .ai directory.
    
    Without arguments: Initialize global ~/.ai/ directory.
    With name: Create a new project with AI-inferred configuration.
    
    Examples:
        adt init                                    # Global init
        adt init myapi --desc "REST API for invoices"
        adt init myapp --type=fullstack --backend=fastapi
    """
    # Global init if no name provided
    if not name:
        _init_global()
        return
    
    # Project init
    from .llm import analyze_project_description, is_ollama_available
    from .scaffold import create_project
    
    # Get project configuration
    if description:
        rprint(f"[bold]Analyzing project description...[/bold]")
        if is_ollama_available():
            rprint("  Using local LLM (Ollama)")
        else:
            rprint("  Using heuristics (Ollama not available)")
        
        inferred = analyze_project_description(description)
        inferred["description"] = description
    else:
        inferred = {
            "type": "backend",
            "stack": {"backend": "fastapi", "frontend": "none"},
            "database": "postgres",
            "deployment": "docker",
            "features": [],
            "reasoning": "Default configuration (no description provided)",
        }
    
    # Check if LLM suggested a better name
    suggested_name = inferred.get("suggested_name")
    generic_names = {"myapi", "myapp", "myproject", "app", "api", "project", "test", "demo"}
    
    if suggested_name and name.lower() in generic_names:
        # LLM found a name in description and user gave generic name
        project_name = suggested_name
        rprint(f"  [cyan]Suggested name:[/cyan] {suggested_name} (from description)")
    elif suggested_name and name.lower() != suggested_name.lower():
        # LLM found a different name - will ask user
        project_name = name  # Use provided name for now, ask later
    else:
        project_name = name
    
    project_path = path or Path.cwd() / project_name
    
    # Apply overrides
    if proj_type:
        inferred["type"] = proj_type
    if backend:
        inferred["stack"]["backend"] = backend
    if frontend:
        inferred["stack"]["frontend"] = frontend
    if database:
        inferred["database"] = database
    if deployment:
        inferred["deployment"] = deployment
    
    # Show configuration
    rprint("")
    rprint(Panel(
        f"[bold]Name:[/bold]       {project_name}\n"
        f"[bold]Type:[/bold]       {inferred['type']}\n"
        f"[bold]Backend:[/bold]    {inferred['stack'].get('backend', 'none')}\n"
        f"[bold]Frontend:[/bold]   {inferred['stack'].get('frontend', 'none')}\n"
        f"[bold]Database:[/bold]   {inferred.get('database', 'none')}\n"
        f"[bold]Deployment:[/bold] {inferred.get('deployment', 'docker')}\n"
        f"[bold]Features:[/bold]   {', '.join(inferred.get('features', [])) or 'none'}\n"
        f"\n[dim]{inferred.get('reasoning', '')}[/dim]",
        title="Project Configuration",
        border_style="cyan"
    ))
    rprint(f"[bold]Path:[/bold] {project_path}")
    rprint("")
    
    # Confirm
    if not yes:
        proceed = typer.confirm("Create project with this configuration?", default=True)
        if not proceed:
            # Allow editing
            edit = typer.confirm("Edit configuration?", default=True)
            if edit:
                # Allow changing the name
                new_name = typer.prompt("Name", default=project_name)
                new_type = typer.prompt("Type", default=inferred["type"])
                new_backend = typer.prompt("Backend", default=inferred["stack"].get("backend", "none"))
                new_frontend = typer.prompt("Frontend", default=inferred["stack"].get("frontend", "none"))
                new_db = typer.prompt("Database", default=inferred.get("database", "none"))
                new_deploy = typer.prompt("Deployment", default=inferred.get("deployment", "docker"))
                
                project_name = new_name
                project_path = path or Path.cwd() / project_name
                inferred["type"] = new_type
                inferred["stack"]["backend"] = new_backend
                inferred["stack"]["frontend"] = new_frontend
                inferred["database"] = new_db
                inferred["deployment"] = new_deploy
            else:
                rprint("[yellow]Cancelled.[/yellow]")
                raise typer.Exit(0)
    
    # Create project
    rprint("")
    rprint(f"[bold]Creating project...[/bold]")
    
    result = create_project(
        path=project_path,
        name=project_name,
        config=inferred,
        register=not no_register,
    )
    
    for f in result["created_files"]:
        rprint(f"  [green]✓[/green] {f}")
    
    # Register with adt
    if not no_register:
        config = load_config()
        project = ProjectConfig(
            name=project_name,
            path=project_path,
            description=description,
            tags=[inferred["type"]] + inferred.get("features", []),
        )
        config.add_project(project)
        save_config(config)
        rprint(f"  [green]✓[/green] Registered with adt")
    
    # Initialize git
    import subprocess
    try:
        subprocess.run(["git", "init"], cwd=project_path, capture_output=True, check=True)
        rprint(f"  [green]✓[/green] Initialized git repository")
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    
    rprint("")
    rprint(f"[green]✓ Project created at {project_path}[/green]")
    rprint("")
    rprint("[bold]Next steps:[/bold]")
    rprint(f"  cd {project_path}")
    
    if inferred["stack"].get("backend") in ("fastapi", "django"):
        rprint("  uv sync")
        rprint("  make dev")
    elif inferred["stack"].get("backend") == "express":
        rprint("  pnpm install")
        rprint("  pnpm dev")
    elif inferred["stack"].get("frontend") != "none":
        if inferred["type"] == "fullstack":
            rprint("  uv sync && cd frontend && pnpm install")
        else:
            rprint("  pnpm install")
            rprint("  pnpm dev")


def _init_global():
    """Initialize global .ai directory."""
    config = load_config()
    
    global_ai_dir = config.global_ai_dir
    global_ai_dir.mkdir(parents=True, exist_ok=True)
    
    rules_file = global_ai_dir / "rules.md"
    if not rules_file.exists():
        rules_file.write_text("""# Global AI Rules

> Universal rules for all projects. AI assistants should follow these unless project-specific rules override them.

## Agent Dev Tool (adt)

You have access to `adt` - a CLI for knowledge, skills, and tools:

```bash
# Run skills (high-level workflows)
adt run skill techdebt              # Find code issues
adt run skill review                # Code review

# Run tools (single-purpose functions)
adt run tool git_status_summary     # Git status as JSON
adt run tool find_todos path=src    # Find TODOs

# Discovery
adt skill list                      # List available skills
adt tool list                       # List available tools
```

## Code Style

- Write concise, functional code
- Keep variable names clear and minimal
- No obvious comments unless explicitly requested
- Clean up unused imports after changes
- Add error handling only where critical

## Behavior

- Don't jump to the first solution—verify assumptions first
- High confidence: proceed. Low confidence: ask.
- Suggest solutions the user didn't think of
- Value good arguments over authority
- Speculation is fine, but flag it

## After Corrections

When corrected, ask: "Should I add this to learnings?"
Then run: `adt learn "Title" -i "issue" -c "correction"`
""")
    
    learnings_file = global_ai_dir / "learnings.md"
    if not learnings_file.exists():
        learnings_file.write_text("""# Global Learnings

> Universal corrections that apply across all projects.

<!-- New entries are added below this line -->

---

*No entries yet.*
""")
    
    # Create skills and tools directories
    (global_ai_dir / "skills").mkdir(exist_ok=True)
    (global_ai_dir / "tools").mkdir(exist_ok=True)
    
    save_config(config)
    
    rprint(f"[green]✓[/green] Initialized global AI directory at {global_ai_dir}")
    rprint(f"[green]✓[/green] Configuration saved to {get_config_path()}")


@app.command()
def add(
    path: Annotated[Path, typer.Argument(help="Path to the project directory")],
    name: Annotated[Optional[str], typer.Option("--name", "-n", help="Project name")] = None,
    description: Annotated[Optional[str], typer.Option("--desc", "-d", help="Project description")] = None,
    tags: Annotated[Optional[str], typer.Option("--tags", "-t", help="Comma-separated tags")] = None,
):
    """Register a project with the knowledge system."""
    path = path.expanduser().resolve()
    
    if not path.exists():
        rprint(f"[red]Error:[/red] Path does not exist: {path}")
        raise typer.Exit(1)
    
    project_name = name or path.name
    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    
    config = load_config()
    
    project = ProjectConfig(
        name=project_name,
        path=path,
        description=description,
        tags=tag_list,
    )
    
    ai_dir = project.full_ai_path
    if not ai_dir.exists():
        ai_dir.mkdir(parents=True)
        
        (ai_dir / "rules.md").write_text(f"""# {project_name} Rules

> Project-specific rules and patterns for AI assistants.

## Stack

<!-- Add your technology stack here -->

## Conventions

<!-- Add project-specific conventions -->

## Patterns

- Check `plan/decisions.md` for architectural context
- Check `.ai/learnings.md` for past corrections
""")
        
        (ai_dir / "learnings.md").write_text(f"""# {project_name} Learnings

> Project-specific corrections and lessons learned.

---

*No entries yet.*
""")
        
        (ai_dir / "context.md").write_text(f"""# {project_name} Context

> Quick reference for AI assistants.

## Overview

<!-- What is this project? -->

## Key Directories

<!-- Important directories and their purpose -->

## Common Tasks

<!-- How to perform common operations -->
""")
        
        rprint(f"[green]✓[/green] Created .ai/ directory with templates")
    
    config.add_project(project)
    save_config(config)
    
    rprint(f"[green]✓[/green] Registered project: {project_name}")
    rprint(f"   Path: {path}")
    if description:
        rprint(f"   Description: {description}")
    if tag_list:
        rprint(f"   Tags: {', '.join(tag_list)}")


@app.command()
def remove(
    name: Annotated[str, typer.Argument(help="Project name to remove")],
):
    """Remove a project from the knowledge system."""
    config = load_config()
    project = config.get_project(name)
    
    if not project:
        rprint(f"[red]Error:[/red] Project not found: {name}")
        raise typer.Exit(1)
    
    config.projects.remove(project)
    save_config(config)
    
    rprint(f"[green]✓[/green] Removed project: {name}")
    rprint(f"   Note: .ai/ directory was not deleted from {project.path}")


@app.command(name="list")
def list_projects():
    """List all registered projects."""
    config = load_config()
    
    if not config.projects:
        rprint("[yellow]No projects registered.[/yellow]")
        rprint("Use 'adt add <path>' to register a project.")
        return
    
    table = Table(title="Registered Projects")
    table.add_column("Name", style="cyan")
    table.add_column("Path")
    table.add_column("Tags", style="green")
    table.add_column(".ai/ exists", style="yellow")
    
    for p in config.projects:
        ai_exists = "✓" if p.full_ai_path.exists() else "✗"
        table.add_row(p.name, str(p.path), ", ".join(p.tags) or "-", ai_exists)
    
    console.print(table)


@app.command()
def index(
    refresh: Annotated[bool, typer.Option("--refresh", "-r", help="Force rebuild index")] = False,
):
    """Build or refresh the knowledge index."""
    config = load_config()
    
    existing = load_index()
    if existing and not refresh:
        rprint("[yellow]Index exists.[/yellow] Use --refresh to rebuild.")
        rprint(f"   Location: {get_index_path()}")
        return
    
    rprint("Building knowledge index...")
    root = build_full_index(config)
    save_index(root)
    
    stats = {
        "projects": len(root.find_by_type(NodeType.PROJECT)),
        "documents": len(root.find_by_type(NodeType.DOCUMENT)),
        "sections": len(root.find_by_type(NodeType.SECTION)),
    }
    
    rprint(f"[green]✓[/green] Index built successfully")
    rprint(f"   Projects: {stats['projects']}")
    rprint(f"   Documents: {stats['documents']}")
    rprint(f"   Sections: {stats['sections']}")
    rprint(f"   Location: {get_index_path()}")


@app.command()
def tree():
    """Display the knowledge tree structure."""
    index = load_index()
    
    if not index:
        rprint("[yellow]No index found.[/yellow] Run 'adt index' first.")
        return
    
    rprint(Panel(index.to_toc(), title="Knowledge Tree", border_style="blue"))


@app.command()
def toc(
    format: Annotated[str, typer.Option("--format", "-f", help="Output format: text, json")] = "text",
):
    """Output the table of contents for LLM consumption."""
    index = load_index()
    
    if not index:
        rprint("[yellow]No index found.[/yellow] Run 'adt index' first.")
        raise typer.Exit(1)
    
    if format == "json":
        print(json.dumps(index.to_compact_json(), indent=2))
    else:
        print(index.to_toc())


@app.command()
def get(
    node_id: Annotated[str, typer.Argument(help="Node ID to retrieve")],
    content: Annotated[bool, typer.Option("--content", "-c", help="Include file content")] = False,
):
    """Retrieve a specific node by ID."""
    index = load_index()
    
    if not index:
        rprint("[yellow]No index found.[/yellow] Run 'adt index' first.")
        raise typer.Exit(1)
    
    node = index.find_by_id(node_id)
    
    if not node:
        rprint(f"[red]Error:[/red] Node not found: {node_id}")
        raise typer.Exit(1)
    
    rprint(Panel(
        f"[bold]Name:[/bold] {node.name}\n"
        f"[bold]Type:[/bold] {node.node_type.value}\n"
        f"[bold]Summary:[/bold] {node.summary or 'N/A'}\n"
        f"[bold]File:[/bold] {node.file_path or 'N/A'}\n"
        f"[bold]Lines:[/bold] {node.start_line}-{node.end_line}" if node.start_line else "",
        title=f"Node: {node_id}",
        border_style="cyan"
    ))
    
    if content and node.file_path and node.file_path.exists():
        file_content = node.file_path.read_text()
        if node.start_line is not None and node.end_line is not None:
            lines = file_content.split("\n")
            file_content = "\n".join(lines[node.start_line:node.end_line + 1])
        rprint(Panel(file_content, title="Content", border_style="green"))


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Search query")],
    tag: Annotated[Optional[str], typer.Option("--tag", "-t", help="Filter by tag")] = None,
):
    """Search the knowledge base."""
    index = load_index()
    
    if not index:
        rprint("[yellow]No index found.[/yellow] Run 'adt index' first.")
        raise typer.Exit(1)
    
    results = []
    query_lower = query.lower()
    
    def search_node(node: "KnowledgeNode"):
        if tag and tag not in node.tags:
            return
        
        match_score = 0
        if query_lower in node.name.lower():
            match_score += 2
        if node.summary and query_lower in node.summary.lower():
            match_score += 1
        
        if match_score > 0:
            results.append((node, match_score))
        
        for child in node.children:
            search_node(child)
    
    search_node(index)
    
    if not results:
        rprint(f"[yellow]No results for:[/yellow] {query}")
        return
    
    results.sort(key=lambda x: x[1], reverse=True)
    
    table = Table(title=f"Search Results: '{query}'")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Type", style="green")
    table.add_column("Summary")
    
    for node, _ in results[:10]:
        summary = (node.summary[:50] + "...") if node.summary and len(node.summary) > 50 else (node.summary or "-")
        table.add_row(node.id, node.name, node.node_type.value, summary)
    
    console.print(table)


@app.command()
def context(
    project: Annotated[Optional[str], typer.Option("--project", "-p", help="Specific project")] = None,
    output: Annotated[str, typer.Option("--output", "-o", help="Output format: text, json, markdown")] = "markdown",
):
    """Generate context for an AI assistant session."""
    index = load_index()
    config = load_config()
    
    if not index:
        rprint("[yellow]No index found.[/yellow] Run 'adt index' first.")
        raise typer.Exit(1)
    
    if output == "json":
        if project:
            proj_node = next(
                (n for n in index.find_by_type(NodeType.PROJECT) if n.name == project),
                None
            )
            if proj_node:
                print(json.dumps(proj_node.to_compact_json(), indent=2))
            else:
                rprint(f"[red]Error:[/red] Project not found: {project}")
        else:
            print(json.dumps(index.to_compact_json(), indent=2))
    else:
        lines = ["# AI Knowledge Context", ""]
        lines.append("## How to Use This Index")
        lines.append("")
        lines.append("1. Read the Table of Contents below to understand available knowledge")
        lines.append("2. Use node IDs to request specific content: `adt get <node_id> --content`")
        lines.append("3. Search for topics: `adt search <query>`")
        lines.append("")
        lines.append("## Table of Contents")
        lines.append("")
        lines.append("```")
        lines.append(index.to_toc())
        lines.append("```")
        
        print("\n".join(lines))


@app.command()
def learn(
    title: Annotated[str, typer.Argument(help="Brief title for the learning")],
    issue: Annotated[str, typer.Option("--issue", "-i", help="What was done incorrectly")] = "",
    correction: Annotated[str, typer.Option("--correction", "-c", help="What should be done instead")] = "",
    context_text: Annotated[Optional[str], typer.Option("--context", help="Additional context")] = None,
    project: Annotated[Optional[str], typer.Option("--project", "-p", help="Project name (omit for global)")] = None,
    interactive: Annotated[bool, typer.Option("--interactive", "-I", help="Interactive mode")] = False,
):
    """Add a new learning entry."""
    from datetime import datetime
    
    config = load_config()
    
    if interactive or not issue or not correction:
        rprint("[bold]Add a new learning[/bold]\n")
        if not issue:
            issue = typer.prompt("Issue (what went wrong)")
        if not correction:
            correction = typer.prompt("Correction (what to do instead)")
        if context_text is None:
            context_text = typer.prompt("Context (optional, press Enter to skip)", default="")
    
    if project:
        proj = config.get_project(project)
        if not proj:
            rprint(f"[red]Error:[/red] Project not found: {project}")
            raise typer.Exit(1)
        learnings_path = proj.full_ai_path / "learnings.md"
    else:
        learnings_path = config.global_ai_dir / "learnings.md"
    
    if not learnings_path.exists():
        rprint(f"[red]Error:[/red] Learnings file not found: {learnings_path}")
        raise typer.Exit(1)
    
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    entry = f"""
### {date_str}: {title}

**Issue:** {issue}

**Correction:** {correction}
"""
    if context_text:
        entry += f"\n**Context:** {context_text}\n"
    
    content = learnings_path.read_text()
    
    insert_marker = "<!-- New entries are added below this line -->"
    if insert_marker in content:
        new_content = content.replace(insert_marker, insert_marker + "\n" + entry)
    elif "---\n" in content:
        parts = content.split("---\n", 1)
        new_content = parts[0] + "---\n" + entry + "\n" + parts[1].lstrip()
    else:
        new_content = content.rstrip() + "\n" + entry
    
    if "*No entries yet.*" in new_content:
        new_content = new_content.replace("*No entries yet.*", "")
    
    learnings_path.write_text(new_content)
    
    scope = f"project '{project}'" if project else "global"
    rprint(f"[green]✓[/green] Added learning to {scope}: {title}")
    
    adt_index = load_index()
    if adt_index:
        rprint("   Rebuilding index...")
        new_index = build_full_index(config)
        save_index(new_index)
        rprint("   [green]✓[/green] Index updated")


@app.command()
def watch():
    """Watch .ai/ directories and auto-rebuild index on changes."""
    from .watcher import watch_knowledge_dirs
    watch_knowledge_dirs()


# Run subcommand group (unified execution)
run_app = typer.Typer(help="Run skills or tools")
app.add_typer(run_app, name="run")


@run_app.command("skill")
def run_skill(
    name: Annotated[str, typer.Argument(help="Skill name (e.g., techdebt, review, commit)")],
    path: Annotated[str, typer.Option("--path", "-p", help="Working directory")] = ".",
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show progress")] = False,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
):
    """Execute a skill by running all its referenced tools."""
    from .skill_executor import (
        execute_skill,
        format_techdebt_report,
        format_generic_report,
    )
    
    # Normalize name - remove leading / if present
    skill_name = name.lstrip("/")
    
    if verbose:
        rprint(f"[bold]Executing skill:[/bold] {skill_name}")
        rprint(f"[bold]Path:[/bold] {path}")
        rprint("")
    
    # Try to find by name or with / prefix
    results = execute_skill(skill_name, path=path, verbose=verbose)
    if "error" in results and "not found" in results.get("error", "").lower():
        results = execute_skill(f"/{skill_name}", path=path, verbose=verbose)
    
    if "error" in results and not results.get("tools_executed"):
        rprint(f"[red]Error:[/red] {results['error']}")
        if "hint" in results:
            rprint(f"[yellow]Hint:[/yellow] {results['hint']}")
        raise typer.Exit(1)
    
    if json_output:
        print(json.dumps(results, indent=2, default=str))
    else:
        # Use specialized formatter for known skills
        if skill_name in ("techdebt", "Find Tech Debt"):
            report = format_techdebt_report(results)
        else:
            report = format_generic_report(results)
        
        rprint(Panel(report, title=f"Skill: {results.get('skill', skill_name)}", border_style="green"))


@run_app.command("tool")
def run_tool(
    name: Annotated[str, typer.Argument(help="Tool name (e.g., find_todos, git_status_summary)")],
    args: Annotated[Optional[list[str]], typer.Argument(help="Arguments as key=value")] = None,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
):
    """Execute a tool and display results."""
    from .tools import load_all_tools
    
    config = load_config()
    registry = load_all_tools(config)
    t = registry.get(name)
    
    if not t:
        rprint(f"[red]Error:[/red] Tool not found: {name}")
        raise typer.Exit(1)
    
    # Parse arguments
    kwargs = {}
    if args:
        for arg in args:
            if "=" in arg:
                key, value = arg.split("=", 1)
                try:
                    kwargs[key] = json.loads(value)
                except json.JSONDecodeError:
                    kwargs[key] = value
            else:
                rprint(f"[red]Error:[/red] Invalid argument format: {arg}")
                rprint("Use key=value format")
                raise typer.Exit(1)
    
    try:
        result = t(**kwargs)
        
        if json_output:
            print(json.dumps({"result": result}, indent=2, default=str))
        else:
            if isinstance(result, (list, dict)):
                rprint(Panel(json.dumps(result, indent=2, default=str), title="Result"))
            else:
                rprint(f"[green]Result:[/green] {result}")
    except Exception as e:
        rprint(f"[red]Error executing tool:[/red] {e}")
        raise typer.Exit(1)


# Skills subcommand group (for management: list, show, new)
skills_app = typer.Typer(help="Manage reusable AI skills/workflows")
app.add_typer(skills_app, name="skill")


@skills_app.command("new")
def skill_new(
    name: Annotated[str, typer.Argument(help="Name for the new skill")],
    trigger: Annotated[Optional[str], typer.Option("--trigger", "-t", help="Slash command trigger")] = None,
    project: Annotated[Optional[str], typer.Option("--project", "-p", help="Project (omit for global)")] = None,
):
    """Create a new skill from template."""
    from .skills import create_skill_template, generate_skill_id
    
    config = load_config()
    
    if project:
        proj = config.get_project(project)
        if not proj:
            rprint(f"[red]Error:[/red] Project not found: {project}")
            raise typer.Exit(1)
        skills_dir = proj.skills_path
    else:
        skills_dir = config.global_skills_path
    
    skills_dir.mkdir(parents=True, exist_ok=True)
    
    skill_id = generate_skill_id(name)
    skill_path = skills_dir / f"{skill_id}.md"
    
    if skill_path.exists():
        rprint(f"[red]Error:[/red] Skill already exists: {skill_path}")
        raise typer.Exit(1)
    
    template = create_skill_template(name, trigger)
    skill_path.write_text(template)
    
    scope = f"project '{project}'" if project else "global"
    rprint(f"[green]✓[/green] Created skill in {scope}: {skill_path}")
    rprint(f"   Edit the file to define your skill's steps and inputs")


@skills_app.command("list")
def skill_list(
    project: Annotated[Optional[str], typer.Option("--project", "-p", help="Filter by project")] = None,
):
    """List all available skills."""
    from .skills import load_all_skills, load_skills_from_dir
    
    config = load_config()
    
    if project:
        proj = config.get_project(project)
        if not proj:
            rprint(f"[red]Error:[/red] Project not found: {project}")
            raise typer.Exit(1)
        skills = load_skills_from_dir(proj.skills_path, project)
    else:
        skills = load_all_skills(config)
    
    if not skills:
        rprint("[yellow]No skills found.[/yellow]")
        rprint("Use 'adt skill new <name>' to create one.")
        return
    
    table = Table(title="Available Skills")
    table.add_column("Name", style="cyan")
    table.add_column("Trigger", style="green")
    table.add_column("Scope")
    table.add_column("Description")
    
    for skill in skills:
        desc = (skill.description[:40] + "...") if len(skill.description) > 40 else skill.description
        table.add_row(
            skill.name,
            skill.trigger or "-",
            skill.scope,
            desc.replace("\n", " "),
        )
    
    console.print(table)


@skills_app.command("show")
def skill_show(
    name: Annotated[str, typer.Argument(help="Skill name or trigger")],
    prompt: Annotated[bool, typer.Option("--prompt", help="Output as LLM prompt")] = False,
):
    """Show details of a specific skill."""
    from .skills import load_all_skills
    
    config = load_config()
    skills = load_all_skills(config)
    
    # Find by name or trigger
    skill = next(
        (s for s in skills if s.name.lower() == name.lower() or s.trigger == name),
        None
    )
    
    if not skill:
        rprint(f"[red]Error:[/red] Skill not found: {name}")
        raise typer.Exit(1)
    
    if prompt:
        print(skill.to_prompt())
    else:
        rprint(Panel(
            f"[bold]Name:[/bold] {skill.name}\n"
            f"[bold]Trigger:[/bold] {skill.trigger or 'N/A'}\n"
            f"[bold]Scope:[/bold] {skill.scope}\n"
            f"[bold]File:[/bold] {skill.file_path}\n"
            f"[bold]Tags:[/bold] {', '.join(skill.tags) or 'N/A'}\n\n"
            f"[bold]Description:[/bold]\n{skill.description}\n\n"
            f"[bold]Steps:[/bold]\n" + "\n".join(f"  {i}. {s}" for i, s in enumerate(skill.steps, 1)),
            title=f"Skill: {skill.name}",
            border_style="cyan"
        ))


@skills_app.command("prompt")
def skill_prompt(
    name: Annotated[str, typer.Argument(help="Skill name or trigger")],
):
    """Output skill as LLM prompt (for piping to AI tools)."""
    from .skills import load_all_skills
    
    config = load_config()
    skills = load_all_skills(config)
    
    # Normalize name
    skill_name = name.lstrip("/")
    
    skill = next(
        (s for s in skills if s.name.lower() == skill_name.lower() 
         or s.trigger == name or s.trigger == f"/{skill_name}"),
        None
    )
    
    if not skill:
        rprint(f"[red]Error:[/red] Skill not found: {name}", file=__import__("sys").stderr)
        raise typer.Exit(1)
    
    print(skill.to_prompt())


# Tools subcommand group
tools_app = typer.Typer(help="Manage reusable code tools/functions")
app.add_typer(tools_app, name="tool")


@tools_app.command("new")
def tool_new(
    name: Annotated[str, typer.Argument(help="Name for the new tool")],
    description: Annotated[str, typer.Option("--desc", "-d", help="Tool description")] = "",
    project: Annotated[Optional[str], typer.Option("--project", "-p", help="Project (omit for global)")] = None,
):
    """Create a new tool from template."""
    config = load_config()
    
    if project:
        proj = config.get_project(project)
        if not proj:
            rprint(f"[red]Error:[/red] Project not found: {project}")
            raise typer.Exit(1)
        tools_dir = proj.full_ai_path / "tools"
    else:
        tools_dir = config.global_ai_dir / "tools"
    
    tools_dir.mkdir(parents=True, exist_ok=True)
    
    # Convert name to valid Python identifier
    tool_filename = name.lower().replace("-", "_").replace(" ", "_")
    tool_path = tools_dir / f"{tool_filename}.py"
    
    if tool_path.exists():
        rprint(f"[red]Error:[/red] Tool file already exists: {tool_path}")
        raise typer.Exit(1)
    
    func_name = tool_filename
    desc = description or f"Description for {name}"
    
    template = f'''"""Tools for {name}."""

from ai_knowledge.tools import tool


@tool(name="{func_name}", description="{desc}", tags=[])
def {func_name}() -> str:
    """
    {desc}
    
    Returns:
        Result of the operation
    """
    # TODO: Implement this tool
    return "Not implemented"
'''
    
    tool_path.write_text(template)
    
    scope = f"project '{project}'" if project else "global"
    rprint(f"[green]✓[/green] Created tool in {scope}: {tool_path}")
    rprint(f"   Edit the file to implement your tool function")


@tools_app.command("list")
def tool_list(
    project: Annotated[Optional[str], typer.Option("--project", "-p", help="Filter by project")] = None,
    tag: Annotated[Optional[str], typer.Option("--tag", "-t", help="Filter by tag")] = None,
):
    """List all available tools."""
    from .tools import load_all_tools
    
    config = load_config()
    registry = load_all_tools(config)
    tools = registry.list(scope=project, tag=tag)
    
    if not tools:
        rprint("[yellow]No tools found.[/yellow]")
        rprint("Use 'adt tool new <name>' to create one.")
        return
    
    table = Table(title="Available Tools")
    table.add_column("Name", style="cyan")
    table.add_column("Signature", style="green")
    table.add_column("Scope")
    table.add_column("Tags")
    
    for t in tools:
        table.add_row(
            t.name,
            t.to_signature(),
            t.scope,
            ", ".join(t.tags) or "-",
        )
    
    console.print(table)


@tools_app.command("show")
def tool_show(
    name: Annotated[str, typer.Argument(help="Tool name")],
    prompt: Annotated[bool, typer.Option("--prompt", help="Output as LLM prompt")] = False,
):
    """Show details of a specific tool."""
    from .tools import load_all_tools
    
    config = load_config()
    registry = load_all_tools(config)
    t = registry.get(name)
    
    if not t:
        rprint(f"[red]Error:[/red] Tool not found: {name}")
        raise typer.Exit(1)
    
    if prompt:
        print(t.to_prompt())
    else:
        params_str = "\n".join(
            f"  - {p.name} ({p.type}): {'required' if p.required else 'optional'}"
            for p in t.params
        ) or "  (none)"
        
        rprint(Panel(
            f"[bold]Name:[/bold] {t.name}\n"
            f"[bold]Signature:[/bold] {t.to_signature()}\n"
            f"[bold]Scope:[/bold] {t.scope}\n"
            f"[bold]File:[/bold] {t.file_path}\n"
            f"[bold]Tags:[/bold] {', '.join(t.tags) or 'N/A'}\n\n"
            f"[bold]Description:[/bold]\n{t.description}\n\n"
            f"[bold]Parameters:[/bold]\n{params_str}\n\n"
            f"[bold]Returns:[/bold] {t.returns}",
            title=f"Tool: {t.name}",
            border_style="cyan"
        ))


@tools_app.command("prompt")
def tool_prompt(
    name: Annotated[str, typer.Argument(help="Tool name")],
):
    """Output tool documentation as LLM prompt."""
    from .tools import load_all_tools
    
    config = load_config()
    registry = load_all_tools(config)
    t = registry.get(name)
    
    if not t:
        rprint(f"[red]Error:[/red] Tool not found: {name}")
        raise typer.Exit(1)
    
    print(t.to_prompt())


# Keep old tool run as hidden alias for backwards compatibility
@tools_app.command("run", hidden=True)
def tool_run_legacy(
    name: Annotated[str, typer.Argument(help="Tool name")],
    args: Annotated[Optional[list[str]], typer.Argument(help="Arguments as key=value")] = None,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
):
    """[Deprecated] Use 'adt run tool <name>' instead."""
    from .tools import load_all_tools
    
    config = load_config()
    registry = load_all_tools(config)
    t = registry.get(name)
    
    if not t:
        rprint(f"[red]Error:[/red] Tool not found: {name}")
        raise typer.Exit(1)
    
    # Parse arguments
    kwargs = {}
    if args:
        for arg in args:
            if "=" in arg:
                key, value = arg.split("=", 1)
                # Try to parse as JSON for complex types
                try:
                    kwargs[key] = json.loads(value)
                except json.JSONDecodeError:
                    kwargs[key] = value
            else:
                rprint(f"[red]Error:[/red] Invalid argument format: {arg}")
                rprint("Use key=value format")
                raise typer.Exit(1)
    
    try:
        result = t(**kwargs)
        
        if json_output:
            print(json.dumps({"result": result}, indent=2, default=str))
        else:
            if isinstance(result, (list, dict)):
                rprint(Panel(json.dumps(result, indent=2, default=str), title="Result"))
            else:
                rprint(f"[green]Result:[/green] {result}")
    except Exception as e:
        rprint(f"[red]Error executing tool:[/red] {e}")
        raise typer.Exit(1)


@tools_app.command("docs")
def tool_docs(
    output: Annotated[str, typer.Option("--output", "-o", help="Output format: text, json")] = "text",
):
    """Generate documentation for all tools."""
    from .tools import load_all_tools
    
    config = load_config()
    registry = load_all_tools(config)
    
    if output == "json":
        tools_data = [t.to_dict() for t in registry.list()]
        print(json.dumps(tools_data, indent=2))
    else:
        print(registry.to_prompt())


# =============================================================================
# Server Commands (Command Center)
# =============================================================================

server_app = typer.Typer(help="ADT Command Center server")
app.add_typer(server_app, name="server")


@server_app.command("start")
def server_start(
    host: Annotated[str, typer.Option("--host", "-h", help="Host to bind")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", "-p", help="Port to bind")] = 8420,
    daemon: Annotated[bool, typer.Option("--daemon", "-d", help="Run in background")] = False,
    reload: Annotated[bool, typer.Option("--reload", "-r", help="Auto-reload on changes")] = False,
):
    """Start the ADT Command Center server."""
    from .server.config import ensure_adt_home
    
    ensure_adt_home()
    
    if daemon:
        # Run in background
        import subprocess
        import sys
        
        log_path = Path.home() / ".adt" / "logs" / "server.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(log_path, "a") as log_file:
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", 
                 "ai_knowledge.server.app:app",
                 "--host", host,
                 "--port", str(port)],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        
        # Save PID
        pid_path = Path.home() / ".adt" / "server.pid"
        pid_path.write_text(str(process.pid))
        
        rprint(f"[green]✓[/green] Server started in background")
        rprint(f"   PID: {process.pid}")
        rprint(f"   URL: http://{host}:{port}")
        rprint(f"   Logs: {log_path}")
        rprint("")
        rprint(f"Stop with: adt server stop")
        return
    
    rprint(f"[bold]Starting ADT Command Center...[/bold]")
    rprint(f"  URL: http://{host}:{port}")
    rprint(f"  API docs: http://{host}:{port}/docs")
    rprint(f"  WebSocket: ws://{host}:{port}/ws")
    rprint("")
    rprint("[dim]Press Ctrl+C to stop[/dim]")
    rprint("")
    
    import uvicorn
    uvicorn.run(
        "ai_knowledge.server.app:app",
        host=host,
        port=port,
        reload=reload,
    )


@server_app.command("status")
def server_status():
    """Check server status."""
    import urllib.request
    import urllib.error
    from .server.config import Config
    
    config = Config.load()
    url = f"http://{config.server.host}:{config.server.port}/status"
    
    # Check PID file
    pid_path = Path.home() / ".adt" / "server.pid"
    pid = None
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            # Check if process is running
            os.kill(pid, 0)
        except (ValueError, OSError):
            pid = None
            pid_path.unlink(missing_ok=True)
    
    # Try to connect
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            data = json.loads(response.read().decode())
            
            rprint("[green]● Server is running[/green]")
            rprint(f"  URL: http://{config.server.host}:{config.server.port}")
            if pid:
                rprint(f"  PID: {pid}")
            rprint(f"  Agents: {data.get('agents', {}).get('running', 0)} running")
            rprint(f"  Tasks: {data.get('queue', {}).get('pending', 0)} pending")
            rprint(f"  Clients: {data.get('connected_clients', 0)} connected")
    except urllib.error.URLError:
        if pid:
            rprint(f"[yellow]● Server process exists (PID {pid}) but not responding[/yellow]")
        else:
            rprint("[dim]○ Server is not running[/dim]")
            rprint(f"  Start with: adt server start")


@server_app.command("stop")
def server_stop(
    force: Annotated[bool, typer.Option("--force", "-f", help="Force kill")] = False,
):
    """Stop the running server."""
    import signal
    
    pid_path = Path.home() / ".adt" / "server.pid"
    
    if not pid_path.exists():
        rprint("[yellow]No server PID file found.[/yellow]")
        return
    
    try:
        pid = int(pid_path.read_text().strip())
        sig = signal.SIGKILL if force else signal.SIGTERM
        os.kill(pid, sig)
        pid_path.unlink()
        rprint(f"[green]✓[/green] Server stopped (PID {pid})")
    except ValueError:
        rprint("[red]Invalid PID file[/red]")
        pid_path.unlink()
    except OSError as e:
        if e.errno == 3:  # No such process
            rprint("[yellow]Server process not found (already stopped?)[/yellow]")
            pid_path.unlink()
        else:
            rprint(f"[red]Error stopping server:[/red] {e}")


# =============================================================================
# Config Commands
# =============================================================================

config_app = typer.Typer(help="Manage ADT configuration")
app.add_typer(config_app, name="config")


@config_app.command("init")
def config_init(
    force: Annotated[bool, typer.Option("--force", "-f", help="Overwrite existing")] = False,
):
    """Initialize ADT configuration."""
    from .server.config import get_adt_home, get_default_config_template, ensure_adt_home
    
    ensure_adt_home()
    config_path = get_adt_home() / "config.yml"
    
    if config_path.exists() and not force:
        rprint(f"[yellow]Config already exists:[/yellow] {config_path}")
        rprint("Use --force to overwrite")
        return
    
    config_path.write_text(get_default_config_template())
    rprint(f"[green]✓[/green] Created config at {config_path}")
    rprint(f"   Edit to customize providers, channels, and agents")


@config_app.command("edit")
def config_edit():
    """Open config in editor."""
    import subprocess
    from .server.config import get_adt_home, ensure_adt_home
    
    ensure_adt_home()
    config_path = get_adt_home() / "config.yml"
    
    if not config_path.exists():
        rprint("[yellow]Config not found. Run 'adt config init' first.[/yellow]")
        return
    
    editor = os.environ.get("EDITOR", "vim")
    subprocess.run([editor, str(config_path)])


@config_app.command("show")
def config_show():
    """Show current configuration."""
    from .server.config import Config, get_adt_home
    
    config_path = get_adt_home() / "config.yml"
    
    if not config_path.exists():
        rprint("[yellow]No config found. Using defaults.[/yellow]")
        rprint("Run 'adt config init' to create config file.")
        return
    
    rprint(Panel(config_path.read_text(), title="~/.adt/config.yml", border_style="cyan"))


@config_app.command("path")
def config_path():
    """Show config file path."""
    from .server.config import get_adt_home
    print(get_adt_home() / "config.yml")


@config_app.command("set-secret")
def config_set_secret(
    key: Annotated[str, typer.Argument(help="Secret key name")],
    value: Annotated[str, typer.Option("--value", "-v", help="Secret value", prompt=True, hide_input=True)] = "",
):
    """Store a secret securely."""
    from .server.vault import set_secret
    
    set_secret(key, value)
    rprint(f"[green]✓[/green] Stored secret: {key}")


@config_app.command("get-secret")
def config_get_secret(
    key: Annotated[str, typer.Argument(help="Secret key name")],
):
    """Get a secret value."""
    from .server.vault import get_secret
    
    value = get_secret(key)
    if value:
        print(value)
    else:
        rprint(f"[yellow]Secret not found:[/yellow] {key}")
        raise typer.Exit(1)


@config_app.command("list-secrets")
def config_list_secrets():
    """List stored secrets and show which ones are needed."""
    from .server.vault import get_vault
    from .server.config import Config, get_adt_home
    import re
    
    vault = get_vault()
    stored_keys = set(vault.list_keys())
    
    # Find secrets actively used in config (not commented out)
    active_secrets: dict[str, str] = {}
    commented_secrets: dict[str, str] = {}
    
    config_path = get_adt_home() / "config.yml"
    if config_path.exists():
        lines = config_path.read_text().split('\n')
        for i, line in enumerate(lines):
            # Skip lines that start with #
            stripped = line.strip()
            if stripped.startswith('#'):
                # Check commented lines for potential secrets
                for match in re.finditer(r'\$\{([A-Z][A-Z0-9_]+)\}', line):
                    key = match.group(1)
                    if key != "VAR_NAME":  # Skip example placeholder
                        commented_secrets[key] = _get_secret_description(key)
                continue
            
            # Active (uncommented) secrets
            for match in re.finditer(r'\$\{([A-Z][A-Z0-9_]+)\}', line):
                key = match.group(1)
                if key != "VAR_NAME":
                    active_secrets[key] = _get_secret_description(key)
    
    # Display stored secrets
    if stored_keys:
        table = Table(title="Stored Secrets")
        table.add_column("Key", style="cyan")
        table.add_column("Status")
        table.add_column("Used For")
        
        for key in sorted(stored_keys):
            table.add_row(key, "[green]✓ set[/green]", _get_secret_description(key))
        
        console.print(table)
    else:
        rprint("[dim]No secrets stored yet.[/dim]")
    
    # Show secrets needed (uncommented in config but not set)
    needed = set(active_secrets.keys()) - stored_keys
    if needed:
        rprint("")
        rprint("[yellow]Secrets needed (referenced in config):[/yellow]")
        for key in sorted(needed):
            rprint(f"  [yellow]○[/yellow] {key} - {active_secrets[key]}")
        rprint("")
        rprint("[dim]Set with: adt config set-secret <KEY>[/dim]")
    
    # Show available providers and their requirements
    rprint("")
    rprint("[bold]Provider Requirements:[/bold]")
    rprint("  [green]cursor[/green] - No API key needed (uses Cursor login)")
    rprint("  [green]ollama[/green] - No API key needed (runs locally)")
    rprint("  [dim]claude[/dim] - Needs ANTHROPIC_API_KEY")
    rprint("  [dim]openai[/dim] - Needs OPENAI_API_KEY")
    rprint("  [dim]gemini[/dim] - Needs GEMINI_API_KEY")


def _get_secret_description(key: str) -> str:
    """Get description for a secret key."""
    descriptions = {
        "ANTHROPIC_API_KEY": "Claude/Anthropic API",
        "OPENAI_API_KEY": "OpenAI API",
        "GEMINI_API_KEY": "Google Gemini API",
        "TELEGRAM_BOT_TOKEN": "Telegram bot",
        "TWILIO_SID": "Twilio account SID",
        "TWILIO_TOKEN": "Twilio auth token",
        "ADT_SECRET_KEY": "Server security",
    }
    return descriptions.get(key, "")


@config_app.command("delete-secret")
def config_delete_secret(
    key: Annotated[str, typer.Argument(help="Secret key name")],
):
    """Delete a stored secret."""
    from .server.vault import get_vault
    
    vault = get_vault()
    if vault.delete(key):
        rprint(f"[green]✓[/green] Deleted secret: {key}")
    else:
        rprint(f"[yellow]Secret not found:[/yellow] {key}")


# =============================================================================
# Token Commands
# =============================================================================

token_app = typer.Typer(help="Manage API tokens")
app.add_typer(token_app, name="token")


@token_app.command("create")
def token_create(
    name: Annotated[str, typer.Argument(help="Token name/description")],
    role: Annotated[str, typer.Option("--role", "-r", help="Role: admin, operator, viewer, agent")] = "operator",
    expires: Annotated[Optional[int], typer.Option("--expires", "-e", help="Expires in N days")] = None,
):
    """Create a new API token."""
    from .server.auth import get_auth_manager, Role
    
    try:
        role_enum = Role(role)
    except ValueError:
        rprint(f"[red]Invalid role:[/red] {role}")
        rprint("Valid roles: admin, operator, viewer, agent")
        raise typer.Exit(1)
    
    auth = get_auth_manager()
    plain_token, info = auth.create_token(
        name=name,
        role=role_enum,
        expires_in_days=expires,
    )
    
    rprint()
    rprint(Panel(
        f"[bold green]{plain_token}[/bold green]",
        title="New API Token",
        subtitle="Save this - it won't be shown again!",
    ))
    rprint()
    rprint(f"[dim]ID:[/dim] {info.id}")
    rprint(f"[dim]Name:[/dim] {info.name}")
    rprint(f"[dim]Role:[/dim] {info.role.value}")
    if info.expires_at:
        rprint(f"[dim]Expires:[/dim] {info.expires_at.isoformat()}")
    rprint()
    rprint("[dim]Use with:[/dim]")
    rprint(f"  curl -H 'Authorization: Bearer {plain_token}' http://127.0.0.1:8420/status")


@token_app.command("list")
def token_list():
    """List all API tokens."""
    from .server.auth import get_auth_manager
    
    auth = get_auth_manager()
    tokens = auth.list_tokens()
    
    if not tokens:
        rprint("[dim]No tokens found. Create one with:[/dim] adt token create <name>")
        return
    
    table = Table(title="API Tokens")
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("Role")
    table.add_column("Created")
    table.add_column("Last Used")
    table.add_column("Status")
    
    for t in tokens:
        status = "[red]revoked[/red]" if t.revoked else "[green]active[/green]"
        if t.expires_at and not t.revoked:
            from datetime import datetime
            if t.expires_at < datetime.now():
                status = "[yellow]expired[/yellow]"
        
        table.add_row(
            t.id,
            t.name,
            t.role.value,
            t.created_at.strftime("%Y-%m-%d"),
            t.last_used_at.strftime("%Y-%m-%d %H:%M") if t.last_used_at else "[dim]never[/dim]",
            status,
        )
    
    rprint(table)


@token_app.command("revoke")
def token_revoke(
    token_id: Annotated[str, typer.Argument(help="Token ID to revoke")],
):
    """Revoke an API token."""
    from .server.auth import get_auth_manager
    
    auth = get_auth_manager()
    if auth.revoke_token(token_id):
        rprint(f"[green]✓[/green] Token revoked: {token_id}")
    else:
        rprint(f"[red]Token not found:[/red] {token_id}")


@token_app.command("delete")
def token_delete(
    token_id: Annotated[str, typer.Argument(help="Token ID to delete")],
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation")] = False,
):
    """Permanently delete an API token."""
    from .server.auth import get_auth_manager
    
    if not force:
        confirm = typer.confirm(f"Permanently delete token {token_id}?")
        if not confirm:
            raise typer.Abort()
    
    auth = get_auth_manager()
    if auth.delete_token(token_id):
        rprint(f"[green]✓[/green] Token deleted: {token_id}")
    else:
        rprint(f"[red]Token not found:[/red] {token_id}")


# =============================================================================
# Agent Commands
# =============================================================================

agent_app = typer.Typer(help="Manage AI agents")
app.add_typer(agent_app, name="agent")


@agent_app.command("list")
def agent_list():
    """List all agents."""
    from .server.config import Config, ensure_adt_home
    from .server.agents import AgentManager
    
    ensure_adt_home()
    config = Config.load()
    manager = AgentManager(config)
    
    agents = manager.list()
    
    if not agents:
        rprint("[yellow]No agents found.[/yellow]")
        rprint("Use 'adt agent spawn <project>' to start one.")
        return
    
    table = Table(title="Agents")
    table.add_column("Project", style="cyan")
    table.add_column("Status")
    table.add_column("Provider")
    table.add_column("Task")
    table.add_column("PID")
    
    status_colors = {
        "idle": "dim",
        "working": "green",
        "testing": "blue",
        "waiting": "yellow",
        "error": "red",
        "stopped": "dim",
    }
    
    for agent in agents:
        color = status_colors.get(agent.status.value, "white")
        table.add_row(
            agent.project,
            f"[{color}]{agent.status.value}[/{color}]",
            agent.provider,
            agent.current_task[:40] + "..." if agent.current_task and len(agent.current_task) > 40 else (agent.current_task or "-"),
            str(agent.pid) if agent.pid else "-",
        )
    
    console.print(table)


@agent_app.command("spawn")
def agent_spawn(
    project: Annotated[str, typer.Argument(help="Project name")],
    provider: Annotated[Optional[str], typer.Option("--provider", "-p", help="LLM provider")] = None,
    task: Annotated[Optional[str], typer.Option("--task", "-t", help="Initial task")] = None,
    worktree: Annotated[Optional[str], typer.Option("--worktree", "-w", help="Use specific worktree")] = None,
):
    """Spawn an agent for a project."""
    from .server.config import Config, ensure_adt_home
    from .server.agents import AgentManager
    
    ensure_adt_home()
    config = Config.load()
    manager = AgentManager(config)
    
    try:
        state = manager.spawn(project, provider=provider, worktree=worktree, task=task)
        rprint(f"[green]✓[/green] Spawned agent for {project}")
        rprint(f"   Provider: {state.provider}")
        rprint(f"   PID: {state.pid}")
        if task:
            rprint(f"   Task: {task}")
    except ValueError as e:
        rprint(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@agent_app.command("stop")
def agent_stop(
    project: Annotated[str, typer.Argument(help="Project name")],
    force: Annotated[bool, typer.Option("--force", "-f", help="Force kill")] = False,
):
    """Stop an agent."""
    from .server.config import Config, ensure_adt_home
    from .server.agents import AgentManager
    
    ensure_adt_home()
    config = Config.load()
    manager = AgentManager(config)
    
    if manager.stop(project, force=force):
        rprint(f"[green]✓[/green] Stopped agent for {project}")
    else:
        rprint(f"[yellow]No agent found for {project}[/yellow]")


@agent_app.command("logs")
def agent_logs(
    project: Annotated[str, typer.Argument(help="Project name")],
    lines: Annotated[int, typer.Option("--lines", "-n", help="Number of lines")] = 50,
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Follow log output")] = False,
):
    """View agent logs."""
    from .server.config import Config, ensure_adt_home, get_adt_home
    from .server.agents import AgentManager
    
    ensure_adt_home()
    
    log_path = get_adt_home() / "logs" / "agents" / f"{project}.log"
    
    if not log_path.exists():
        rprint(f"[yellow]No logs found for {project}[/yellow]")
        return
    
    if follow:
        import subprocess
        subprocess.run(["tail", "-f", str(log_path)])
    else:
        config = Config.load()
        manager = AgentManager(config)
        logs = manager.get_logs(project, lines=lines)
        print(logs)


@agent_app.command("assign")
def agent_assign(
    project: Annotated[str, typer.Argument(help="Project name")],
    task: Annotated[str, typer.Argument(help="Task description")],
):
    """Assign a task to an agent."""
    from .server.config import Config, ensure_adt_home
    from .server.agents import AgentManager
    
    ensure_adt_home()
    config = Config.load()
    manager = AgentManager(config)
    
    try:
        state = manager.assign_task(project, task)
        rprint(f"[green]✓[/green] Assigned task to {project}")
        rprint(f"   Status: {state.status.value}")
    except ValueError as e:
        rprint(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@agent_app.command("status")
def agent_status(
    project: Annotated[str, typer.Argument(help="Project name")],
):
    """Get detailed status for an agent."""
    from .server.config import Config, ensure_adt_home
    from .server.agents import AgentManager
    
    ensure_adt_home()
    config = Config.load()
    manager = AgentManager(config)
    
    agent = manager.get(project)
    
    if not agent:
        rprint(f"[yellow]No agent found for {project}[/yellow]")
        return
    
    rprint(Panel(
        f"[bold]Project:[/bold] {agent.project}\n"
        f"[bold]Status:[/bold] {agent.status.value}\n"
        f"[bold]Provider:[/bold] {agent.provider}\n"
        f"[bold]PID:[/bold] {agent.pid or 'N/A'}\n"
        f"[bold]Worktree:[/bold] {agent.worktree or 'N/A'}\n"
        f"[bold]Current Task:[/bold] {agent.current_task or 'None'}\n"
        f"[bold]Started:[/bold] {agent.started_at or 'N/A'}\n"
        f"[bold]Last Activity:[/bold] {agent.last_activity or 'N/A'}\n"
        f"[bold]Error:[/bold] {agent.error or 'None'}",
        title=f"Agent: {project}",
        border_style="cyan"
    ))


# =============================================================================
# Queue Commands
# =============================================================================

queue_app = typer.Typer(help="Manage task queue")
app.add_typer(queue_app, name="queue")


@queue_app.command("list")
def queue_list(
    project: Annotated[Optional[str], typer.Option("--project", "-p", help="Filter by project")] = None,
    all_tasks: Annotated[bool, typer.Option("--all", "-a", help="Include completed tasks")] = False,
):
    """List tasks in the queue."""
    from .server.queue import TaskQueue
    from .server.config import ensure_adt_home
    
    ensure_adt_home()
    queue = TaskQueue()
    tasks = queue.list(project=project, include_completed=all_tasks)
    
    if not tasks:
        rprint("[yellow]No tasks in queue.[/yellow]")
        return
    
    table = Table(title="Task Queue")
    table.add_column("ID", style="cyan")
    table.add_column("Project")
    table.add_column("Description")
    table.add_column("Priority")
    table.add_column("Status")
    table.add_column("Assigned")
    
    status_colors = {
        "pending": "white",
        "assigned": "blue",
        "in_progress": "green",
        "blocked": "yellow",
        "completed": "dim",
        "failed": "red",
        "cancelled": "dim",
    }
    
    for task in tasks:
        color = status_colors.get(task.status.value, "white")
        desc = task.description[:35] + "..." if len(task.description) > 35 else task.description
        table.add_row(
            task.id,
            task.project,
            desc,
            task.priority.value,
            f"[{color}]{task.status.value}[/{color}]",
            task.assigned_to or "-",
        )
    
    console.print(table)


@queue_app.command("add")
def queue_add(
    project: Annotated[str, typer.Argument(help="Project name")],
    description: Annotated[str, typer.Argument(help="Task description")],
    priority: Annotated[str, typer.Option("--priority", "-p", help="Priority: low, normal, high, urgent")] = "normal",
):
    """Add a task to the queue."""
    from .server.queue import TaskQueue, TaskPriority
    from .server.config import ensure_adt_home
    
    ensure_adt_home()
    queue = TaskQueue()
    
    try:
        prio = TaskPriority(priority)
    except ValueError:
        rprint(f"[red]Invalid priority:[/red] {priority}")
        rprint("Use: low, normal, high, urgent")
        raise typer.Exit(1)
    
    task = queue.create(project=project, description=description, priority=prio)
    rprint(f"[green]✓[/green] Created task {task.id}")
    rprint(f"   Project: {project}")
    rprint(f"   Priority: {priority}")


@queue_app.command("cancel")
def queue_cancel(
    task_id: Annotated[str, typer.Argument(help="Task ID")],
):
    """Cancel a task."""
    from .server.queue import TaskQueue
    from .server.config import ensure_adt_home
    
    ensure_adt_home()
    queue = TaskQueue()
    
    task = queue.cancel(task_id)
    if task:
        rprint(f"[green]✓[/green] Cancelled task {task_id}")
    else:
        rprint(f"[yellow]Task not found:[/yellow] {task_id}")


@queue_app.command("stats")
def queue_stats():
    """Show queue statistics."""
    from .server.queue import TaskQueue
    from .server.config import ensure_adt_home
    
    ensure_adt_home()
    queue = TaskQueue()
    stats = queue.stats()
    
    rprint(Panel(
        f"[bold]Total:[/bold] {stats['total']}\n"
        f"[bold]Pending:[/bold] {stats['pending']}\n"
        f"[bold]In Progress:[/bold] {stats['in_progress']}\n"
        f"[bold]Blocked:[/bold] {stats['blocked']}\n"
        f"[bold]Completed:[/bold] {stats['completed']}\n"
        f"[bold]Failed:[/bold] {stats['failed']}\n\n"
        f"[bold]By Project:[/bold]\n" + 
        "\n".join(f"  {p}: {c}" for p, c in stats['by_project'].items()),
        title="Queue Stats",
        border_style="cyan"
    ))


if __name__ == "__main__":
    app()
