# Quick Setup

## 1. Install

```bash
cd ~/agent-dev-tool
uv sync  # or: pip install -e .
```

## 2. Initialize

```bash
adt init
```

## 3. (Optional) Install Ollama for Smart Features

```bash
brew install ollama
ollama serve
ollama pull llama3.2:3b
```

## 4. Create Your First Project

```bash
adt init myproject --desc "Description of what you're building"
```

## 5. Start Developing

```bash
cd myproject
uv sync  # or: pnpm install for frontend
make dev
```

---

## For AI Agents

Add to your workflow:

```bash
# Find issues
adt run skill techdebt

# Review changes
adt run skill review

# Get context
adt context

# Record learnings
adt learn "Title" -i "issue" -c "correction"
```

---

## Full Documentation

- [Human Guide](docs/human-guide.md)
- [AI Agent Guide](docs/ai-agent-guide.md)
- [MCP Setup](docs/mcp-setup.md)
