"""Embedded web dashboard for ADT Command Center."""

DASHBOARD_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ADT Command Center</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .status-working { color: #22c55e; }
        .status-idle { color: #6b7280; }
        .status-error { color: #ef4444; }
        .status-stopped { color: #9ca3af; }
        .status-pending { color: #f59e0b; }
        .status-blocked { color: #eab308; }
        .priority-urgent { background: #fecaca; }
        .priority-high { background: #fed7aa; }
        .priority-normal { background: #e5e7eb; }
        .priority-low { background: #f3f4f6; }
        .log-container { font-family: monospace; font-size: 12px; }
        .fade-in { animation: fadeIn 0.3s ease-in; }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
    </style>
</head>
<body class="bg-gray-900 text-gray-100 min-h-screen">
    <div class="container mx-auto px-4 py-6 max-w-7xl">
        <!-- Header -->
        <div class="flex justify-between items-center mb-6">
            <h1 class="text-2xl font-bold">ADT Command Center</h1>
            <div id="connection-status" class="flex items-center gap-2">
                <span class="w-2 h-2 rounded-full bg-gray-500" id="ws-indicator"></span>
                <span class="text-sm text-gray-400" id="ws-status">Connecting...</span>
            </div>
        </div>

        <!-- Stats Bar -->
        <div class="grid grid-cols-4 gap-4 mb-6">
            <div class="bg-gray-800 rounded-lg p-4">
                <div class="text-3xl font-bold" id="stat-agents">0</div>
                <div class="text-gray-400 text-sm">Active Agents</div>
            </div>
            <div class="bg-gray-800 rounded-lg p-4">
                <div class="text-3xl font-bold" id="stat-tasks">0</div>
                <div class="text-gray-400 text-sm">Pending Tasks</div>
            </div>
            <div class="bg-gray-800 rounded-lg p-4">
                <div class="text-3xl font-bold" id="stat-projects">0</div>
                <div class="text-gray-400 text-sm">Projects</div>
            </div>
            <div class="bg-gray-800 rounded-lg p-4">
                <div class="text-3xl font-bold" id="stat-completed">0</div>
                <div class="text-gray-400 text-sm">Completed Today</div>
            </div>
        </div>

        <div class="grid grid-cols-3 gap-6">
            <!-- Agents Panel -->
            <div class="col-span-1">
                <div class="bg-gray-800 rounded-lg p-4">
                    <div class="flex justify-between items-center mb-4">
                        <h2 class="text-lg font-semibold">Agents</h2>
                        <button onclick="openSpawnModal()" class="bg-green-600 hover:bg-green-700 px-3 py-1 rounded text-sm">
                            + Spawn
                        </button>
                    </div>
                    <div id="agents-list" class="space-y-2">
                        <div class="text-gray-500 text-sm">Loading...</div>
                    </div>
                </div>
                
                <!-- Projects Panel -->
                <div class="bg-gray-800 rounded-lg p-4 mt-4">
                    <h2 class="text-lg font-semibold mb-4">Projects</h2>
                    <div id="projects-list" class="space-y-2 max-h-64 overflow-y-auto">
                        <div class="text-gray-500 text-sm">Loading...</div>
                    </div>
                </div>
            </div>

            <!-- Task Queue Panel -->
            <div class="col-span-1">
                <div class="bg-gray-800 rounded-lg p-4">
                    <div class="flex justify-between items-center mb-4">
                        <h2 class="text-lg font-semibold">Task Queue</h2>
                        <button onclick="openTaskModal()" class="bg-blue-600 hover:bg-blue-700 px-3 py-1 rounded text-sm">
                            + Add Task
                        </button>
                    </div>
                    <div id="tasks-list" class="space-y-2 max-h-96 overflow-y-auto">
                        <div class="text-gray-500 text-sm">Loading...</div>
                    </div>
                </div>
            </div>

            <!-- Activity & Logs Panel -->
            <div class="col-span-1">
                <div class="bg-gray-800 rounded-lg p-4">
                    <div class="flex justify-between items-center mb-4">
                        <h2 class="text-lg font-semibold">Activity</h2>
                        <button onclick="clearEvents()" class="text-gray-400 hover:text-white text-sm">Clear</button>
                    </div>
                    <div id="events-list" class="space-y-1 max-h-64 overflow-y-auto log-container">
                        <div class="text-gray-500 text-sm">Waiting for events...</div>
                    </div>
                </div>
                
                <!-- Agent Logs -->
                <div class="bg-gray-800 rounded-lg p-4 mt-4">
                    <div class="flex justify-between items-center mb-4">
                        <h2 class="text-lg font-semibold">Agent Logs</h2>
                        <select id="log-agent-select" onchange="loadAgentLogs()" class="bg-gray-700 rounded px-2 py-1 text-sm">
                            <option value="">Select agent...</option>
                        </select>
                    </div>
                    <div id="agent-logs" class="max-h-48 overflow-y-auto log-container bg-gray-900 p-2 rounded">
                        <div class="text-gray-500 text-sm">Select an agent to view logs</div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Command Input -->
        <div class="mt-6 bg-gray-800 rounded-lg p-4">
            <div class="flex gap-2">
                <input type="text" id="command-input" 
                       placeholder="Enter command (e.g., spawn documaker, add task documaker Fix the bug)" 
                       class="flex-1 bg-gray-700 rounded px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                       onkeypress="if(event.key==='Enter') executeCommand()">
                <button onclick="executeCommand()" class="bg-blue-600 hover:bg-blue-700 px-6 py-2 rounded">
                    Execute
                </button>
            </div>
            <div id="command-output" class="mt-2 text-sm text-gray-400"></div>
        </div>
    </div>

    <!-- Spawn Agent Modal -->
    <div id="spawn-modal" class="fixed inset-0 bg-black bg-opacity-50 hidden items-center justify-center">
        <div class="bg-gray-800 rounded-lg p-6 w-96">
            <h3 class="text-lg font-semibold mb-4">Spawn Agent</h3>
            <div class="space-y-4">
                <div>
                    <label class="block text-sm text-gray-400 mb-1">Project</label>
                    <select id="spawn-project" class="w-full bg-gray-700 rounded px-3 py-2"></select>
                </div>
                <div>
                    <label class="block text-sm text-gray-400 mb-1">Initial Task (optional)</label>
                    <textarea id="spawn-task" rows="3" class="w-full bg-gray-700 rounded px-3 py-2" 
                              placeholder="Describe the task..."></textarea>
                </div>
                <div class="flex gap-2 justify-end">
                    <button onclick="closeSpawnModal()" class="px-4 py-2 rounded bg-gray-600 hover:bg-gray-500">Cancel</button>
                    <button onclick="spawnAgent()" class="px-4 py-2 rounded bg-green-600 hover:bg-green-700">Spawn</button>
                </div>
            </div>
        </div>
    </div>

    <!-- Retry Agent Modal -->
    <div id="retry-modal" class="fixed inset-0 bg-black bg-opacity-50 hidden items-center justify-center">
        <div class="bg-gray-800 rounded-lg p-6 w-96">
            <h3 class="text-lg font-semibold mb-4">Retry Agent</h3>
            <div class="space-y-4">
                <div>
                    <label class="block text-sm text-gray-400 mb-1">Project</label>
                    <input type="text" id="retry-project" readonly class="w-full bg-gray-600 rounded px-3 py-2 text-gray-300">
                </div>
                <div>
                    <label class="block text-sm text-gray-400 mb-1">Error</label>
                    <div id="retry-error" class="text-red-400 text-sm bg-gray-700 rounded px-3 py-2 max-h-20 overflow-auto"></div>
                </div>
                <div>
                    <label class="block text-sm text-gray-400 mb-1">Task (edit to fix)</label>
                    <textarea id="retry-task" rows="4" class="w-full bg-gray-700 rounded px-3 py-2" 
                              placeholder="Describe the task..."></textarea>
                </div>
                <div class="flex gap-2 justify-end">
                    <button onclick="closeRetryModal()" class="px-4 py-2 rounded bg-gray-600 hover:bg-gray-500">Cancel</button>
                    <button onclick="submitRetry()" class="px-4 py-2 rounded bg-yellow-600 hover:bg-yellow-700">Retry</button>
                </div>
            </div>
        </div>
    </div>

    <!-- Add Task Modal -->
    <div id="task-modal" class="fixed inset-0 bg-black bg-opacity-50 hidden items-center justify-center">
        <div class="bg-gray-800 rounded-lg p-6 w-96">
            <h3 class="text-lg font-semibold mb-4">Add Task</h3>
            <div class="space-y-4">
                <div>
                    <label class="block text-sm text-gray-400 mb-1">Project</label>
                    <select id="task-project" class="w-full bg-gray-700 rounded px-3 py-2"></select>
                </div>
                <div>
                    <label class="block text-sm text-gray-400 mb-1">Description</label>
                    <textarea id="task-description" rows="3" class="w-full bg-gray-700 rounded px-3 py-2" 
                              placeholder="Describe the task..."></textarea>
                </div>
                <div>
                    <label class="block text-sm text-gray-400 mb-1">Priority</label>
                    <select id="task-priority" class="w-full bg-gray-700 rounded px-3 py-2">
                        <option value="low">Low</option>
                        <option value="normal" selected>Normal</option>
                        <option value="high">High</option>
                        <option value="urgent">Urgent</option>
                    </select>
                </div>
                <div class="flex gap-2 justify-end">
                    <button onclick="closeTaskModal()" class="px-4 py-2 rounded bg-gray-600 hover:bg-gray-500">Cancel</button>
                    <button onclick="addTask()" class="px-4 py-2 rounded bg-blue-600 hover:bg-blue-700">Add Task</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        const API_BASE = '';
        let ws = null;
        let projects = [];
        let reconnectAttempts = 0;

        // WebSocket connection
        function connectWebSocket() {
            const wsUrl = `ws://${window.location.host}/ws`;
            ws = new WebSocket(wsUrl);
            
            ws.onopen = () => {
                document.getElementById('ws-indicator').className = 'w-2 h-2 rounded-full bg-green-500';
                document.getElementById('ws-status').textContent = 'Connected';
                reconnectAttempts = 0;
            };
            
            ws.onclose = () => {
                document.getElementById('ws-indicator').className = 'w-2 h-2 rounded-full bg-red-500';
                document.getElementById('ws-status').textContent = 'Disconnected';
                
                // Reconnect after delay
                if (reconnectAttempts < 10) {
                    setTimeout(() => {
                        reconnectAttempts++;
                        connectWebSocket();
                    }, 2000);
                }
            };
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                handleEvent(data);
            };
        }

        function handleEvent(event) {
            // Add to activity log
            const eventsDiv = document.getElementById('events-list');
            if (eventsDiv.querySelector('.text-gray-500')) {
                eventsDiv.innerHTML = '';
            }
            
            const time = new Date().toLocaleTimeString();
            const eventHtml = `<div class="fade-in text-xs">
                <span class="text-gray-500">${time}</span>
                <span class="text-blue-400">${event.type}</span>
                ${event.project ? `<span class="text-green-400">${event.project}</span>` : ''}
            </div>`;
            eventsDiv.insertAdjacentHTML('afterbegin', eventHtml);
            
            // Refresh relevant data
            if (event.type.startsWith('agent.')) {
                loadAgents();
            } else if (event.type.startsWith('task.')) {
                loadTasks();
            }
            
            loadStatus();
        }

        // API calls
        async function api(endpoint, options = {}) {
            const response = await fetch(API_BASE + endpoint, {
                ...options,
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers,
                },
            });
            return response.json();
        }

        async function loadStatus() {
            const status = await api('/status');
            document.getElementById('stat-agents').textContent = status.agents?.running || 0;
            document.getElementById('stat-tasks').textContent = status.queue?.pending || 0;
            document.getElementById('stat-completed').textContent = status.queue?.completed || 0;
        }

        async function loadProjects() {
            projects = await api('/projects');
            document.getElementById('stat-projects').textContent = projects.length;
            
            const projectsHtml = projects.map(p => `
                <div class="bg-gray-700 rounded p-2 text-sm">
                    <div class="font-medium">${p.name}</div>
                    <div class="text-gray-400 text-xs truncate">${p.path}</div>
                </div>
            `).join('');
            document.getElementById('projects-list').innerHTML = projectsHtml || '<div class="text-gray-500 text-sm">No projects</div>';
            
            // Update selects
            const projectOptions = projects.map(p => `<option value="${p.name}">${p.name}</option>`).join('');
            document.getElementById('spawn-project').innerHTML = projectOptions;
            document.getElementById('task-project').innerHTML = projectOptions;
            
            // Update log select
            const logSelect = document.getElementById('log-agent-select');
            const currentValue = logSelect.value;
            logSelect.innerHTML = '<option value="">Select agent...</option>' + projectOptions;
            logSelect.value = currentValue;
        }

        async function loadAgents() {
            const agents = await api('/agents');
            
            if (agents.length === 0) {
                document.getElementById('agents-list').innerHTML = '<div class="text-gray-500 text-sm">No agents running</div>';
                return;
            }
            
            const agentsHtml = agents.map(a => `
                <div class="bg-gray-700 rounded p-3 ${a.status === 'error' ? 'border border-red-500' : ''}">
                    <div class="flex justify-between items-center">
                        <span class="font-medium">${a.project}</span>
                        <span class="status-${a.status} text-sm">${a.status}</span>
                    </div>
                    <div class="text-gray-400 text-xs mt-1">${a.provider}</div>
                    ${a.task ? `<div class="text-gray-300 text-xs mt-1 truncate">${a.task}</div>` : ''}
                    ${a.error ? `<div class="text-red-400 text-xs mt-1 truncate" title="${a.error}">${a.error}</div>` : ''}
                    <div class="flex gap-2 mt-2">
                        ${a.status === 'error' ? 
                            `<button onclick="retryAgent('${a.project}')" class="text-xs bg-yellow-600 hover:bg-yellow-700 px-2 py-1 rounded">Retry</button>
                             <button onclick="openRetryModalFor('${a.project}', '${(a.task || '').replace(/'/g, "\\'")}', '${(a.error || '').replace(/'/g, "\\'")}')" class="text-xs bg-blue-600 hover:bg-blue-700 px-2 py-1 rounded">Edit & Retry</button>` :
                          a.status !== 'stopped' ? 
                            `<button onclick="stopAgent('${a.project}')" class="text-xs bg-red-600 hover:bg-red-700 px-2 py-1 rounded">Stop</button>` : 
                            `<button onclick="openSpawnModalFor('${a.project}')" class="text-xs bg-green-600 hover:bg-green-700 px-2 py-1 rounded">Spawn</button>`
                        }
                        <button onclick="viewLogs('${a.project}')" class="text-xs bg-gray-600 hover:bg-gray-500 px-2 py-1 rounded">Logs</button>
                    </div>
                </div>
            `).join('');
            document.getElementById('agents-list').innerHTML = agentsHtml;
        }

        async function loadTasks() {
            const tasks = await api('/tasks');
            
            if (tasks.length === 0) {
                document.getElementById('tasks-list').innerHTML = '<div class="text-gray-500 text-sm">No pending tasks</div>';
                return;
            }
            
            const tasksHtml = tasks.map(t => `
                <div class="bg-gray-700 rounded p-3 priority-${t.priority}">
                    <div class="flex justify-between items-center">
                        <span class="text-xs text-gray-400">${t.id}</span>
                        <span class="status-${t.status} text-xs">${t.status}</span>
                    </div>
                    <div class="font-medium text-sm mt-1 text-gray-900">${t.description}</div>
                    <div class="flex justify-between items-center mt-2">
                        <span class="text-xs text-gray-600">${t.project}</span>
                        ${t.status === 'pending' ? 
                            `<button onclick="cancelTask('${t.id}')" class="text-xs bg-red-600 hover:bg-red-700 px-2 py-1 rounded text-white">Cancel</button>` : ''}
                    </div>
                </div>
            `).join('');
            document.getElementById('tasks-list').innerHTML = tasksHtml;
        }

        async function loadAgentLogs() {
            const agent = document.getElementById('log-agent-select').value;
            if (!agent) return;
            
            const data = await api(`/agents/${agent}/logs?lines=50`);
            const logsDiv = document.getElementById('agent-logs');
            
            if (data.logs) {
                logsDiv.innerHTML = `<pre class="text-xs text-gray-300 whitespace-pre-wrap">${data.logs}</pre>`;
                logsDiv.scrollTop = logsDiv.scrollHeight;
            } else {
                logsDiv.innerHTML = '<div class="text-gray-500 text-sm">No logs available</div>';
            }
        }

        // Actions
        async function spawnAgent() {
            const project = document.getElementById('spawn-project').value;
            const task = document.getElementById('spawn-task').value;
            
            await api('/agents/spawn', {
                method: 'POST',
                body: JSON.stringify({ project, task: task || null }),
            });
            
            closeSpawnModal();
            loadAgents();
        }

        async function stopAgent(project) {
            await api(`/agents/${project}/stop`, { method: 'POST' });
            loadAgents();
        }

        async function addTask() {
            const project = document.getElementById('task-project').value;
            const description = document.getElementById('task-description').value;
            const priority = document.getElementById('task-priority').value;
            
            await api('/tasks', {
                method: 'POST',
                body: JSON.stringify({ project, description, priority }),
            });
            
            closeTaskModal();
            loadTasks();
        }

        async function cancelTask(taskId) {
            await api(`/tasks/${taskId}/cancel`, { method: 'POST' });
            loadTasks();
        }

        function viewLogs(project) {
            document.getElementById('log-agent-select').value = project;
            loadAgentLogs();
        }

        async function executeCommand() {
            const input = document.getElementById('command-input');
            const output = document.getElementById('command-output');
            const cmd = input.value.trim();
            
            if (!cmd) return;
            
            output.textContent = 'Executing...';
            
            try {
                const parts = cmd.split(' ');
                const action = parts[0].toLowerCase();
                
                if (action === 'spawn' && parts[1]) {
                    const task = parts.slice(2).join(' ') || null;
                    const result = await api('/agents/spawn', {
                        method: 'POST',
                        body: JSON.stringify({ project: parts[1], task }),
                    });
                    output.textContent = result.success ? `Spawned agent for ${parts[1]}` : 'Failed';
                } else if (action === 'stop' && parts[1]) {
                    await api(`/agents/${parts[1]}/stop`, { method: 'POST' });
                    output.textContent = `Stopped ${parts[1]}`;
                } else if (action === 'add' && parts[1] === 'task' && parts[2]) {
                    const result = await api('/tasks', {
                        method: 'POST',
                        body: JSON.stringify({ 
                            project: parts[2], 
                            description: parts.slice(3).join(' '),
                            priority: 'normal',
                        }),
                    });
                    output.textContent = result.success ? `Created task ${result.task.id}` : 'Failed';
                } else if (action === 'status') {
                    const status = await api('/status');
                    output.textContent = JSON.stringify(status, null, 2);
                } else {
                    output.textContent = 'Unknown command. Try: spawn <project>, stop <project>, add task <project> <description>, status';
                }
            } catch (e) {
                output.textContent = `Error: ${e.message}`;
            }
            
            input.value = '';
            loadAgents();
            loadTasks();
        }

        // Modals
        function openSpawnModal() {
            document.getElementById('spawn-modal').classList.remove('hidden');
            document.getElementById('spawn-modal').classList.add('flex');
            document.getElementById('spawn-task').value = '';
        }

        function openSpawnModalFor(project) {
            openSpawnModal();
            document.getElementById('spawn-project').value = project;
        }

        function closeSpawnModal() {
            document.getElementById('spawn-modal').classList.add('hidden');
            document.getElementById('spawn-modal').classList.remove('flex');
        }

        function openTaskModal() {
            document.getElementById('task-modal').classList.remove('hidden');
            document.getElementById('task-modal').classList.add('flex');
            document.getElementById('task-description').value = '';
        }

        function closeTaskModal() {
            document.getElementById('task-modal').classList.add('hidden');
            document.getElementById('task-modal').classList.remove('flex');
        }

        function clearEvents() {
            document.getElementById('events-list').innerHTML = '<div class="text-gray-500 text-sm">Waiting for events...</div>';
        }

        // Retry functions
        async function retryAgent(project) {
            const result = await api(`/agents/${project}/retry`, { method: 'POST' });
            if (result.success) {
                loadAgents();
            }
        }

        function openRetryModalFor(project, task, error) {
            document.getElementById('retry-project').value = project;
            document.getElementById('retry-task').value = task || '';
            document.getElementById('retry-error').textContent = error || 'Unknown error';
            document.getElementById('retry-modal').classList.remove('hidden');
            document.getElementById('retry-modal').classList.add('flex');
        }

        function closeRetryModal() {
            document.getElementById('retry-modal').classList.add('hidden');
            document.getElementById('retry-modal').classList.remove('flex');
        }

        async function submitRetry() {
            const project = document.getElementById('retry-project').value;
            const task = document.getElementById('retry-task').value;
            
            const result = await api(`/agents/${project}/retry`, {
                method: 'POST',
                body: JSON.stringify({ task: task || null }),
            });
            
            if (result.success) {
                closeRetryModal();
                loadAgents();
            }
        }

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            loadStatus();
            loadProjects();
            loadAgents();
            loadTasks();
            connectWebSocket();
            
            // Auto-refresh every 10 seconds
            setInterval(() => {
                loadStatus();
                loadAgents();
                loadTasks();
            }, 10000);
        });
    </script>
</body>
</html>
'''
