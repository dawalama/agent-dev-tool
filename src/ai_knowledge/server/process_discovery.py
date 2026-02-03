"""LLM-powered process discovery for projects."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from pydantic import BaseModel

from ..llm import ollama_generate


class DiscoveredProcess(BaseModel):
    """A process discovered from project config."""
    name: str  # e.g., "frontend", "backend", "worker"
    command: str  # e.g., "npm run dev", "npm run worker:dev"
    description: str  # What this process does
    default_port: Optional[int] = None  # If it's a server
    cwd: Optional[str] = None  # Subdirectory if any


class ProjectProcessConfig(BaseModel):
    """Process configuration for a project."""
    project: str
    processes: list[DiscoveredProcess]


def read_project_files(project_path: str) -> dict[str, str]:
    """Read relevant config files from a project."""
    path = Path(project_path)
    files = {}
    
    # Root level files
    for filename in ["package.json", "pyproject.toml", "Makefile", "docker-compose.yml", "docker-compose.yaml"]:
        filepath = path / filename
        if filepath.exists():
            try:
                files[filename] = filepath.read_text()[:5000]  # Limit size
            except Exception:
                pass
    
    # Check subdirectories
    for subdir in ["frontend", "backend", "client", "server", "api", "worker", "workers"]:
        subpath = path / subdir
        if subpath.exists():
            for filename in ["package.json", "pyproject.toml"]:
                filepath = subpath / filename
                if filepath.exists():
                    try:
                        files[f"{subdir}/{filename}"] = filepath.read_text()[:3000]
                    except Exception:
                        pass
    
    return files


def analyze_with_llm(project_name: str, files: dict[str, str]) -> list[DiscoveredProcess]:
    """Use LLM to analyze project files and discover processes."""
    
    prompt = f"""Analyze this project's configuration files and identify all the dev processes that can be run.

Project: {project_name}

Files:
"""
    for filename, content in files.items():
        prompt += f"\n--- {filename} ---\n{content}\n"
    
    prompt += """

Based on these files, identify all runnable dev processes. For each process, provide:
1. name: A short name (e.g., "frontend", "backend", "worker", "db", "queue")
2. command: The exact command to run it (e.g., "npm run dev", "npm run worker:dev", "uvicorn main:app --reload")
3. description: Brief description of what it does
4. default_port: The port it runs on (if it's a server), or null
5. cwd: The subdirectory to run from (e.g., "frontend", "backend"), or null for root

Return ONLY valid JSON array, no other text:
[
  {"name": "...", "command": "...", "description": "...", "default_port": ..., "cwd": ...},
  ...
]

Important:
- Look for scripts in package.json (dev, start, worker, worker:dev, etc.)
- Look for Python commands in pyproject.toml
- Consider docker-compose services
- Include ALL runnable dev processes, not just frontend/backend
"""

    try:
        response = ollama_generate(prompt, model="llama3.2")
        
        # Extract JSON from response
        response = response.strip()
        
        # Find JSON array in response
        start = response.find('[')
        end = response.rfind(']') + 1
        
        if start >= 0 and end > start:
            json_str = response[start:end]
            data = json.loads(json_str)
            
            return [DiscoveredProcess(**p) for p in data]
    except Exception as e:
        print(f"LLM analysis failed: {e}")
    
    return []


def analyze_with_heuristics(project_path: str, files: dict[str, str]) -> list[DiscoveredProcess]:
    """Fallback heuristic-based discovery without LLM."""
    processes = []
    path = Path(project_path)
    
    # Check root package.json
    if "package.json" in files:
        try:
            pkg = json.loads(files["package.json"])
            scripts = pkg.get("scripts", {})
            
            for script_name in ["dev", "start", "serve"]:
                if script_name in scripts:
                    processes.append(DiscoveredProcess(
                        name="app",
                        command=f"npm run {script_name}",
                        description=f"Main application ({script_name})",
                        default_port=3000,
                    ))
                    break
            
            # Look for worker scripts
            for script_name, script_cmd in scripts.items():
                if "worker" in script_name.lower():
                    processes.append(DiscoveredProcess(
                        name=script_name.replace(":", "-"),
                        command=f"npm run {script_name}",
                        description=f"Worker process",
                    ))
        except json.JSONDecodeError:
            pass
    
    # Check subdirectories
    for subdir in ["frontend", "backend", "client", "server", "api"]:
        pkg_key = f"{subdir}/package.json"
        if pkg_key in files:
            try:
                pkg = json.loads(files[pkg_key])
                scripts = pkg.get("scripts", {})
                
                if "dev" in scripts or "start" in scripts:
                    script = "dev" if "dev" in scripts else "start"
                    port = 3000 if subdir in ["frontend", "client"] else 8000
                    processes.append(DiscoveredProcess(
                        name=subdir,
                        command=f"npm run {script}",
                        description=f"{subdir.title()} server",
                        default_port=port,
                        cwd=subdir,
                    ))
                
                # Check for worker scripts in subdirs
                for script_name in scripts:
                    if "worker" in script_name.lower():
                        processes.append(DiscoveredProcess(
                            name=f"{subdir}-{script_name.replace(':', '-')}",
                            command=f"npm run {script_name}",
                            description=f"Worker in {subdir}",
                            cwd=subdir,
                        ))
            except json.JSONDecodeError:
                pass
        
        # Check for Python
        pyproject_key = f"{subdir}/pyproject.toml"
        if pyproject_key in files or (path / subdir / "main.py").exists():
            port = 8000 if subdir in ["backend", "server", "api"] else 8080
            processes.append(DiscoveredProcess(
                name=subdir,
                command="uvicorn main:app --reload",
                description=f"{subdir.title()} API server",
                default_port=port,
                cwd=subdir,
            ))
    
    return processes


def discover_processes(project_name: str, project_path: str, use_llm: bool = True) -> list[DiscoveredProcess]:
    """Discover all runnable processes for a project.
    
    Args:
        project_name: Name of the project
        project_path: Path to project root
        use_llm: Whether to use LLM for smart discovery (falls back to heuristics if fails)
    
    Returns:
        List of discovered processes
    """
    files = read_project_files(project_path)
    
    if not files:
        return []
    
    processes = []
    
    if use_llm:
        processes = analyze_with_llm(project_name, files)
    
    # Fall back to heuristics if LLM failed or was disabled
    if not processes:
        processes = analyze_with_heuristics(project_path, files)
    
    return processes
