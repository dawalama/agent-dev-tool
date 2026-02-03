# ADT Data Layer Architecture

## Current: File-based
- Agent state: `~/.adt/agents/{project}.state.json`
- Task queue: `~/.adt/queue/tasks.json`
- Config: `~/.adt/config.yml`
- Logs: `~/.adt/logs/agents/{project}.log`

## Planned: SQLite (local) / Turso (remote)

### Database Split
```
~/.adt/data/
├── main.db      # Config, projects, agent registry
├── tasks.db     # Task queue + history  
└── logs.db      # Time-series events, agent logs
```

### Why Separate DBs
- **main.db**: Small, stable, easy backup
- **tasks.db**: Higher writes, can archive old completed tasks
- **logs.db**: Append-heavy, can rotate without affecting core state

### Schema Overview

#### main.db
```sql
-- Projects registered with ADT
CREATE TABLE projects (
    name TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    config JSON  -- project-specific overrides
);

-- Agent registry (not runtime state)
CREATE TABLE agents (
    project TEXT PRIMARY KEY REFERENCES projects(name),
    provider TEXT DEFAULT 'cursor',
    preferred_worktree TEXT,
    config JSON
);
```

#### tasks.db
```sql
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    description TEXT NOT NULL,
    priority TEXT DEFAULT 'normal',
    status TEXT DEFAULT 'pending',
    assigned_to TEXT,  -- agent/project
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    result TEXT,
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    metadata JSON
);

CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_project ON tasks(project);
CREATE INDEX idx_tasks_created ON tasks(created_at);
```

#### logs.db
```sql
-- Time-series events
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    type TEXT NOT NULL,  -- agent.started, task.completed, etc.
    project TEXT,
    agent TEXT,
    task_id TEXT,
    data JSON,
    level TEXT DEFAULT 'info'  -- debug, info, warn, error
);

CREATE INDEX idx_events_time ON events(timestamp);
CREATE INDEX idx_events_project ON events(project);
CREATE INDEX idx_events_type ON events(type);

-- Agent run history
CREATE TABLE agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    provider TEXT,
    task TEXT,
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    exit_code INTEGER,
    status TEXT,  -- completed, error, stopped
    error TEXT,
    log_path TEXT
);

CREATE INDEX idx_runs_project ON agent_runs(project);
CREATE INDEX idx_runs_time ON agent_runs(started_at);
```

### SQLite Patterns for Queue/PubSub

#### Task Queue (no Redis needed)
```python
# Claim next task atomically
UPDATE tasks 
SET status = 'in_progress', 
    assigned_to = ?, 
    started_at = CURRENT_TIMESTAMP
WHERE id = (
    SELECT id FROM tasks 
    WHERE status = 'pending' 
    ORDER BY 
        CASE priority 
            WHEN 'urgent' THEN 0 
            WHEN 'high' THEN 1 
            WHEN 'normal' THEN 2 
            ELSE 3 
        END,
        created_at
    LIMIT 1
)
RETURNING *;
```

#### Pub/Sub via Polling
```python
# Subscriber keeps track of last seen
SELECT * FROM events 
WHERE id > ? 
ORDER BY id 
LIMIT 100;
```

#### Agent Heartbeats
```sql
-- Update heartbeat
UPDATE agents SET last_heartbeat = CURRENT_TIMESTAMP WHERE project = ?;

-- Find stale agents (no heartbeat in 30s)
SELECT * FROM agents 
WHERE last_heartbeat < datetime('now', '-30 seconds')
  AND status = 'working';
```

### Turso Migration Path

Same code works with Turso - just change connection:

```python
# Local SQLite
db = libsql.connect("~/.adt/data/main.db")

# Turso (when ready for remote)
db = libsql.connect(
    "libsql://your-db.turso.io",
    auth_token=os.environ["TURSO_TOKEN"]
)
```

### Future: Heavy Server Deployment

When running on dedicated server, can optionally upgrade to:
- PostgreSQL + TimescaleDB (same schema, more scale)
- Redis (faster pub/sub, distributed queue)
- ClickHouse or Loki (high-volume logs)

But SQLite/Turso should handle:
- Dozens of concurrent agents
- Thousands of tasks/day
- Months of log retention

Only upgrade if hitting limits.
