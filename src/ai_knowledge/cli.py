"""CLI interface for agent-dev-tool."""

import json
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
def init():
    """Initialize the global .ai directory and configuration."""
    config = load_config()
    
    global_ai_dir = config.global_ai_dir
    global_ai_dir.mkdir(parents=True, exist_ok=True)
    
    rules_file = global_ai_dir / "rules.md"
    if not rules_file.exists():
        rules_file.write_text("""# Global AI Rules

> Universal rules for all projects. AI assistants should follow these unless project-specific rules override them.

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
Then update the appropriate file:
- `~/.ai/learnings.md` for universal lessons
- `.ai/learnings.md` for project-specific lessons
""")
    
    learnings_file = global_ai_dir / "learnings.md"
    if not learnings_file.exists():
        learnings_file.write_text("""# Global Learnings

> Universal corrections that apply across all projects.

## Format

### YYYY-MM-DD: Brief Title

**Issue:** What was done incorrectly

**Correction:** What should be done instead

**Context:** Optional additional context

---

*No entries yet.*
""")
    
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


if __name__ == "__main__":
    app()
