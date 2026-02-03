"""Embedded web dashboard for ADT Command Center."""

DASHBOARD_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ADT Command Center</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .status-working, .status-in_progress { color: #22c55e; }
        .status-idle { color: #6b7280; }
        .status-error, .status-failed { color: #ef4444; }
        .status-stopped { color: #9ca3af; }
        .status-pending { color: #f59e0b; }
        .status-blocked, .status-awaiting_review { color: #eab308; }
        .status-completed { color: #22c55e; }
        .log-container { font-family: monospace; font-size: 12px; }
        .fade-in { animation: fadeIn 0.3s ease-in; }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        .tab-active { border-bottom: 2px solid #3b82f6; color: white; }
        .tab-inactive { color: #9ca3af; }
        .task-card:hover { background: #374151; }
    </style>
</head>
<body class="bg-gray-900 text-gray-100 min-h-screen">
    <div class="container mx-auto px-4 py-6 max-w-7xl">
        <!-- Header -->
        <div class="flex justify-between items-center mb-4">
            <h1 class="text-2xl font-bold">ADT Command Center</h1>
            <div class="flex items-center gap-4">
                <div id="connection-status" class="flex items-center gap-2">
                    <span class="w-2 h-2 rounded-full bg-gray-500" id="ws-indicator"></span>
                    <span class="text-sm text-gray-400" id="ws-status">Connecting...</span>
                </div>
                <button onclick="logout()" class="text-sm text-gray-400 hover:text-white">Logout</button>
            </div>
        </div>

        <!-- Project Selector Bar -->
        <div class="bg-gray-800 rounded-lg p-3 mb-4">
            <div class="flex items-center gap-4">
                <span class="text-gray-400 text-sm">Project:</span>
                <div id="project-tabs" class="flex gap-2 flex-wrap">
                    <button onclick="selectProject('all')" class="px-3 py-1 rounded text-sm bg-blue-600" id="project-all">All</button>
                </div>
            </div>
        </div>

        <!-- Main Content Grid -->
        <div class="grid grid-cols-3 gap-6">
            <!-- Left: Task Queue -->
            <div class="col-span-2">
                <!-- Pending Reviews -->
                <div id="review-panel" class="bg-yellow-900 rounded-lg p-4 mb-4 hidden">
                    <h2 class="text-lg font-semibold mb-2">⚠️ Pending Review</h2>
                    <div id="review-list" class="space-y-2"></div>
                </div>

                <!-- Tasks -->
                <div class="bg-gray-800 rounded-lg p-4">
                    <div class="flex justify-between items-center mb-4">
                        <h2 class="text-lg font-semibold">Tasks</h2>
                        <button onclick="openTaskModal()" class="bg-blue-600 hover:bg-blue-700 px-3 py-1 rounded text-sm">
                            + Add Task
                        </button>
                    </div>
                    <div id="tasks-list" class="space-y-2 max-h-96 overflow-y-auto">
                        <div class="text-gray-500 text-sm">Loading...</div>
                    </div>
                </div>

                <!-- Output Panel -->
                <div class="bg-gray-800 rounded-lg p-4 mt-4">
                    <div class="flex justify-between items-center mb-4">
                        <h2 class="text-lg font-semibold">
                            Output
                            <span id="current-task-name" class="text-blue-400 text-sm ml-2"></span>
                        </h2>
                        <button id="live-toggle" onclick="toggleLive()" class="text-xs bg-gray-600 hover:bg-gray-500 px-2 py-1 rounded hidden">
                            ○ Live
                        </button>
                    </div>
                    <div id="output-panel" class="max-h-64 overflow-y-auto log-container bg-gray-900 p-3 rounded">
                        <div class="text-gray-500 text-sm">Click on a task to view output</div>
                    </div>
                </div>
            </div>

            <!-- Right: Stats & Activity -->
            <div class="col-span-1">
                <!-- Stats -->
                <div class="grid grid-cols-2 gap-3 mb-4">
                    <div class="bg-gray-800 rounded-lg p-3 text-center">
                        <div class="text-2xl font-bold text-green-400" id="stat-running">0</div>
                        <div class="text-gray-400 text-xs">Running</div>
                    </div>
                    <div class="bg-gray-800 rounded-lg p-3 text-center">
                        <div class="text-2xl font-bold text-yellow-400" id="stat-pending">0</div>
                        <div class="text-gray-400 text-xs">Pending</div>
                    </div>
                    <div class="bg-gray-800 rounded-lg p-3 text-center">
                        <div class="text-2xl font-bold text-green-500" id="stat-completed">0</div>
                        <div class="text-gray-400 text-xs">Completed</div>
                    </div>
                    <div class="bg-gray-800 rounded-lg p-3 text-center">
                        <div class="text-2xl font-bold text-red-400" id="stat-failed">0</div>
                        <div class="text-gray-400 text-xs">Failed</div>
                    </div>
                </div>

                <!-- Tabs: Activity / Workers -->
                <div class="bg-gray-800 rounded-lg">
                    <div class="flex border-b border-gray-700">
                        <button onclick="showTab('activity')" id="tab-activity" class="px-4 py-2 text-sm tab-active">Activity</button>
                        <button onclick="showTab('workers')" id="tab-workers" class="px-4 py-2 text-sm tab-inactive">Workers</button>
                        <button onclick="showTab('processes')" id="tab-processes" class="px-4 py-2 text-sm tab-inactive">Processes</button>
                    </div>
                    
                    <!-- Activity Tab -->
                    <div id="panel-activity" class="p-4">
                        <div id="events-list" class="space-y-1 max-h-80 overflow-y-auto log-container">
                            <div class="text-gray-500 text-sm">Waiting for events...</div>
                        </div>
                    </div>
                    
                    <!-- Workers Tab -->
                    <div id="panel-workers" class="p-4 hidden">
                        <div id="workers-list" class="space-y-2">
                            <div class="text-gray-500 text-sm">No active workers</div>
                        </div>
                    </div>
                    
                    <!-- Processes Tab -->
                    <div id="panel-processes" class="p-4 hidden">
                        <div class="flex justify-between items-center mb-2">
                            <span class="text-xs text-gray-400">Dev servers & services</span>
                            <div class="flex gap-2">
                                <button onclick="showPortsModal()" class="text-xs bg-gray-600 hover:bg-gray-500 px-2 py-1 rounded">Ports</button>
                                <button onclick="detectProcesses()" class="text-xs bg-blue-600 hover:bg-blue-700 px-2 py-1 rounded">Auto-detect</button>
                            </div>
                        </div>
                        <div id="processes-list" class="space-y-2">
                            <div class="text-gray-500 text-sm">No processes configured</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Add Task Modal -->
        <div id="task-modal" class="fixed inset-0 bg-black bg-opacity-50 hidden items-center justify-center z-50">
            <div class="bg-gray-800 rounded-lg p-6 w-full max-w-md">
                <h3 class="text-lg font-semibold mb-4">Add Task</h3>
                <div class="space-y-4">
                    <div>
                        <label class="block text-sm text-gray-400 mb-1">Project</label>
                        <select id="task-project" class="w-full bg-gray-700 rounded px-3 py-2"></select>
                    </div>
                    <div>
                        <label class="block text-sm text-gray-400 mb-1">Description</label>
                        <textarea id="task-description" rows="3" class="w-full bg-gray-700 rounded px-3 py-2" placeholder="What should the agent do?"></textarea>
                    </div>
                    <div>
                        <label class="block text-sm text-gray-400 mb-1">Priority</label>
                        <select id="task-priority" class="w-full bg-gray-700 rounded px-3 py-2">
                            <option value="normal">Normal</option>
                            <option value="high">High</option>
                            <option value="urgent">Urgent</option>
                            <option value="low">Low</option>
                        </select>
                    </div>
                    <div class="flex items-center gap-2">
                        <input type="checkbox" id="task-review" class="rounded">
                        <label for="task-review" class="text-sm text-gray-400">Require review before running</label>
                    </div>
                </div>
                <div class="flex justify-end gap-2 mt-6">
                    <button onclick="closeTaskModal()" class="px-4 py-2 bg-gray-600 hover:bg-gray-500 rounded">Cancel</button>
                    <button onclick="submitTask()" class="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded">Add Task</button>
                </div>
            </div>
        </div>

        <!-- Retry Modal -->
        <div id="retry-modal" class="fixed inset-0 bg-black bg-opacity-50 hidden items-center justify-center z-50">
            <div class="bg-gray-800 rounded-lg p-6 w-full max-w-md">
                <h3 class="text-lg font-semibold mb-4">Retry Task</h3>
                <div class="space-y-4">
                    <div>
                        <label class="block text-sm text-gray-400 mb-1">Task Description</label>
                        <textarea id="retry-description" rows="3" class="w-full bg-gray-700 rounded px-3 py-2"></textarea>
                    </div>
                    <div id="retry-error" class="text-red-400 text-sm"></div>
                </div>
                <div class="flex justify-end gap-2 mt-6">
                    <button onclick="closeRetryModal()" class="px-4 py-2 bg-gray-600 hover:bg-gray-500 rounded">Cancel</button>
                    <button onclick="submitRetry()" class="px-4 py-2 bg-yellow-600 hover:bg-yellow-700 rounded">Retry</button>
                </div>
            </div>
        </div>

        <!-- Auth Modal -->
        <div id="auth-modal" class="fixed inset-0 bg-black bg-opacity-50 hidden items-center justify-center z-50">
            <div class="bg-gray-800 rounded-lg p-6 w-full max-w-sm">
                <h3 class="text-lg font-semibold mb-4">Authentication Required</h3>
                <div class="space-y-4">
                    <div>
                        <label class="block text-sm text-gray-400 mb-1">API Token</label>
                        <input type="password" id="auth-token" class="w-full bg-gray-700 rounded px-3 py-2" placeholder="adt_...">
                    </div>
                </div>
                <div class="flex justify-end gap-2 mt-6">
                    <button onclick="submitAuth()" class="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded w-full">Login</button>
                </div>
            </div>
        </div>

        <!-- Toast Notification -->
        <div id="toast" class="fixed bottom-4 right-4 bg-gray-800 text-white px-4 py-2 rounded-lg shadow-lg hidden"></div>
    </div>

    <script>
        let ws = null;
        let authToken = localStorage.getItem('adt_token') || '';
        let currentProject = localStorage.getItem('adt_project') || 'all';
        let currentTaskId = null;
        let isLiveStreaming = false;
        let retryTaskId = null;
        let allTasks = [];
        let allWorkers = [];

        function getAuthHeaders() {
            return { 'Authorization': `Bearer ${authToken}`, 'Content-Type': 'application/json' };
        }

        async function api(path, options = {}) {
            try {
                const resp = await fetch(path, {
                    ...options,
                    headers: { ...getAuthHeaders(), ...(options.headers || {}) }
                });
                if (resp.status === 401 || resp.status === 403) {
                    showAuthModal();
                    return null;
                }
                if (!resp.ok) {
                    const text = await resp.text();
                    throw new Error(text);
                }
                return await resp.json();
            } catch (e) {
                console.error('API error:', e);
                return null;
            }
        }

        function showAuthModal() {
            document.getElementById('auth-modal').classList.remove('hidden');
            document.getElementById('auth-modal').classList.add('flex');
        }

        function submitAuth() {
            authToken = document.getElementById('auth-token').value;
            localStorage.setItem('adt_token', authToken);
            document.getElementById('auth-modal').classList.add('hidden');
            loadAll();
            connectWebSocket();
        }

        function logout() {
            localStorage.removeItem('adt_token');
            authToken = '';
            showAuthModal();
        }

        function showTab(tab) {
            ['activity', 'workers', 'processes'].forEach(t => {
                document.getElementById(`tab-${t}`).className = t === tab ? 'px-4 py-2 text-sm tab-active' : 'px-4 py-2 text-sm tab-inactive';
                document.getElementById(`panel-${t}`).classList.toggle('hidden', t !== tab);
            });
            if (tab === 'processes') loadProcesses();
        }

        function selectProject(project) {
            currentProject = project;
            localStorage.setItem('adt_project', project);
            document.querySelectorAll('#project-tabs button').forEach(btn => {
                btn.className = btn.id === `project-${project}` ? 'px-3 py-1 rounded text-sm bg-blue-600' : 'px-3 py-1 rounded text-sm bg-gray-700 hover:bg-gray-600';
            });
            renderTasks();
        }

        async function loadProjects() {
            const projects = await api('/projects');
            if (!projects) return;
            
            const container = document.getElementById('project-tabs');
            const isAllSelected = currentProject === 'all';
            container.innerHTML = `<button onclick="selectProject('all')" class="px-3 py-1 rounded text-sm ${isAllSelected ? 'bg-blue-600' : 'bg-gray-700 hover:bg-gray-600'}" id="project-all">All</button>`;
            
            // If saved project no longer exists, reset to 'all'
            const projectNames = projects.map(p => p.name);
            if (currentProject !== 'all' && !projectNames.includes(currentProject)) {
                currentProject = 'all';
                localStorage.setItem('adt_project', 'all');
            }
            
            projects.forEach(p => {
                const btn = document.createElement('button');
                btn.id = `project-${p.name}`;
                btn.className = `px-3 py-1 rounded text-sm ${currentProject === p.name ? 'bg-blue-600' : 'bg-gray-700 hover:bg-gray-600'}`;
                btn.textContent = p.name;
                btn.onclick = () => selectProject(p.name);
                container.appendChild(btn);
            });
        }

        async function loadTasks() {
            const tasks = await api('/tasks');
            if (!tasks) return;
            
            allTasks = tasks;
            loadPendingReviews();
            renderTasks();
            updateStats();
        }

        function renderTasks() {
            const filtered = currentProject === 'all' ? allTasks : allTasks.filter(t => t.project === currentProject);
            const container = document.getElementById('tasks-list');
            
            if (filtered.length === 0) {
                container.innerHTML = '<div class="text-gray-500 text-sm">No tasks</div>';
                return;
            }

            container.innerHTML = filtered.map(t => {
                const statusIcon = getStatusIcon(t.status);
                const buttons = getTaskButtons(t);
                const isSelected = t.id === currentTaskId;
                
                return `
                    <div class="task-card rounded p-3 cursor-pointer transition-colors ${isSelected ? 'bg-gray-600 ring-2 ring-blue-500' : 'bg-gray-700'}"
                         onclick="selectTask('${t.id}')">
                        <div class="flex justify-between items-start">
                            <div class="flex items-center gap-2">
                                <span class="text-lg">${statusIcon}</span>
                                <div>
                                    <div class="text-sm font-medium">${t.project}</div>
                                    <div class="text-xs text-gray-400 truncate max-w-xs">${t.description}</div>
                                </div>
                            </div>
                            <span class="status-${t.status} text-xs">${t.status}</span>
                        </div>
                        ${t.error ? `<div class="text-red-400 text-xs mt-2 truncate">${t.error}</div>` : ''}
                        <div class="flex gap-2 mt-2" onclick="event.stopPropagation()">
                            ${buttons}
                        </div>
                    </div>
                `;
            }).join('');
        }

        function getStatusIcon(status) {
            switch(status) {
                case 'completed': return '✓';
                case 'failed': return '✗';
                case 'in_progress': return '⟳';
                case 'pending': return '○';
                case 'blocked': return '⏸';
                case 'awaiting_review': return '⚠';
                default: return '•';
            }
        }

        function getTaskButtons(task) {
            switch(task.status) {
                case 'pending':
                    return `
                        <button onclick="runTask('${task.id}')" class="text-xs bg-green-600 hover:bg-green-700 px-2 py-1 rounded">Run</button>
                        <button onclick="cancelTask('${task.id}')" class="text-xs bg-gray-600 hover:bg-gray-500 px-2 py-1 rounded">Cancel</button>
                    `;
                case 'in_progress':
                    return `
                        <button onclick="stopTask('${task.id}')" class="text-xs bg-red-600 hover:bg-red-700 px-2 py-1 rounded">Stop</button>
                    `;
                case 'completed':
                    return `
                        <button onclick="viewOutput('${task.id}')" class="text-xs bg-gray-600 hover:bg-gray-500 px-2 py-1 rounded">View Output</button>
                    `;
                case 'failed':
                    return `
                        <button onclick="retryTask('${task.id}')" class="text-xs bg-yellow-600 hover:bg-yellow-700 px-2 py-1 rounded">Retry</button>
                        <button onclick="openRetryModal('${task.id}')" class="text-xs bg-blue-600 hover:bg-blue-700 px-2 py-1 rounded">Edit & Retry</button>
                    `;
                case 'blocked':
                    return `<span class="text-xs text-gray-500">Waiting on dependencies</span>`;
                default:
                    return '';
            }
        }

        async function runTask(taskId) {
            const result = await api(`/tasks/${taskId}/run`, { method: 'POST' });
            if (result?.success) {
                showNotification('Task started');
                loadTasks();
                loadWorkers();
            }
        }

        async function stopTask(taskId) {
            const task = allTasks.find(t => t.id === taskId);
            if (task?.assigned_to) {
                await api(`/agents/${task.assigned_to}/stop`, { method: 'POST' });
                showNotification('Task stopped');
                loadTasks();
                loadWorkers();
            }
        }

        async function cancelTask(taskId) {
            await api(`/tasks/${taskId}/cancel`, { method: 'POST' });
            showNotification('Task cancelled');
            loadTasks();
        }

        async function retryTask(taskId) {
            const result = await api(`/tasks/${taskId}/retry`, { method: 'POST' });
            if (result?.success) {
                showNotification('Task retrying');
                loadTasks();
            }
        }

        function openRetryModal(taskId) {
            const task = allTasks.find(t => t.id === taskId);
            if (!task) return;
            
            retryTaskId = taskId;
            document.getElementById('retry-description').value = task.description;
            document.getElementById('retry-error').textContent = task.error || '';
            document.getElementById('retry-modal').classList.remove('hidden');
            document.getElementById('retry-modal').classList.add('flex');
        }

        function closeRetryModal() {
            document.getElementById('retry-modal').classList.add('hidden');
            retryTaskId = null;
        }

        async function submitRetry() {
            if (!retryTaskId) return;
            
            const description = document.getElementById('retry-description').value;
            const result = await api(`/tasks/${retryTaskId}/retry`, {
                method: 'POST',
                body: JSON.stringify({ description })
            });
            
            if (result?.success) {
                showNotification('Task retrying');
                closeRetryModal();
                loadTasks();
            }
        }

        async function selectTask(taskId) {
            currentTaskId = taskId;
            renderTasks();
            
            const task = allTasks.find(t => t.id === taskId);
            if (!task) return;
            
            document.getElementById('current-task-name').textContent = `${task.project}: ${task.description.slice(0, 30)}...`;
            
            // If running, enable live streaming
            if (task.status === 'in_progress' && task.assigned_to) {
                document.getElementById('live-toggle').classList.remove('hidden');
                if (!isLiveStreaming) {
                    toggleLive();
                }
                // Subscribe to agent output
                ws?.send(JSON.stringify({ command: 'subscribe', project: task.assigned_to }));
            } else {
                // Load completed output
                viewOutput(taskId);
            }
        }

        async function viewOutput(taskId) {
            const result = await api(`/tasks/${taskId}/output`);
            const panel = document.getElementById('output-panel');
            
            if (result?.output) {
                panel.innerHTML = `<pre class="text-xs text-gray-300 whitespace-pre-wrap">${result.output}</pre>`;
            } else {
                panel.innerHTML = '<div class="text-gray-500 text-sm">No output captured</div>';
            }
        }

        function toggleLive() {
            const btn = document.getElementById('live-toggle');
            isLiveStreaming = !isLiveStreaming;
            
            if (isLiveStreaming) {
                btn.className = 'text-xs bg-green-600 hover:bg-green-700 px-2 py-1 rounded';
                btn.textContent = '● Live';
            } else {
                btn.className = 'text-xs bg-gray-600 hover:bg-gray-500 px-2 py-1 rounded';
                btn.textContent = '○ Live';
            }
        }

        async function loadWorkers() {
            const agents = await api('/agents');
            if (!agents) return;
            
            allWorkers = agents;
            renderWorkers();
            document.getElementById('stat-running').textContent = agents.filter(a => a.status === 'working').length;
        }

        function renderWorkers() {
            const container = document.getElementById('workers-list');
            const active = allWorkers.filter(w => w.status === 'working');
            
            if (active.length === 0) {
                container.innerHTML = '<div class="text-gray-500 text-sm">No active workers</div>';
                return;
            }

            container.innerHTML = active.map(w => `
                <div class="bg-gray-700 rounded p-2">
                    <div class="flex justify-between items-center">
                        <span class="font-medium text-sm">${w.project}</span>
                        <span class="text-green-400 text-xs">PID: ${w.pid}</span>
                    </div>
                    <div class="text-gray-400 text-xs truncate mt-1">${w.task || 'No task'}</div>
                    <button onclick="stopWorker('${w.project}')" class="text-xs bg-red-600 hover:bg-red-700 px-2 py-1 rounded mt-2">Stop</button>
                </div>
            `).join('');
        }

        async function stopWorker(project) {
            await api(`/agents/${project}/stop`, { method: 'POST' });
            showNotification('Worker stopped');
            loadWorkers();
            loadTasks();
        }

        // Process management
        let allProcesses = [];

        async function loadProcesses() {
            // Always load ALL processes so we can show running ones from other projects
            const processes = await api('/processes');
            if (!processes) return;
            
            allProcesses = processes;
            renderProcesses();
        }

        function renderProcesses() {
            const container = document.getElementById('processes-list');
            
            // Filter by project but always show running processes from any project
            let filtered = allProcesses;
            if (currentProject !== 'all') {
                filtered = allProcesses.filter(p => 
                    p.project === currentProject || p.status === 'running'
                );
            }
            
            if (filtered.length === 0) {
                container.innerHTML = '<div class="text-gray-500 text-sm">No processes configured. Click "Auto-detect" to find dev servers.</div>';
                return;
            }
            
            // Sort: running first, then by project
            filtered.sort((a, b) => {
                if (a.status === 'running' && b.status !== 'running') return -1;
                if (b.status === 'running' && a.status !== 'running') return 1;
                return a.project.localeCompare(b.project);
            });

            container.innerHTML = filtered.map(p => {
                const isRunning = p.status === 'running';
                const isFailed = p.status === 'failed';
                const isIdle = p.status === 'idle';
                const statusColor = isRunning ? 'text-green-400' : isFailed ? 'text-red-400' : isIdle ? 'text-blue-400' : 'text-gray-400';
                const borderClass = isFailed ? 'border border-red-500' : '';
                const statusText = isIdle ? 'ready' : p.status;
                
                return `
                    <div class="bg-gray-700 rounded p-2 ${borderClass}">
                        <div class="flex justify-between items-center">
                            <div>
                                <span class="font-medium text-sm">${p.project}/${p.name}</span>
                                ${p.port ? `<span class="text-blue-400 text-xs ml-2">:${p.port}</span>` : ''}
                            </div>
                            <span class="${statusColor} text-xs">${statusText}${p.pid ? ` (${p.pid})` : ''}</span>
                        </div>
                        <div class="text-gray-400 text-xs truncate mt-1" title="${p.command}">${p.command}</div>
                        ${isFailed && p.error ? `<div class="text-red-400 text-xs mt-1 truncate" title="${p.error}">${p.error.split('\\n')[0]}</div>` : ''}
                        <div class="flex gap-2 mt-2 flex-wrap">
                            ${isRunning ? `
                                <button onclick="stopProcess('${p.id}')" class="text-xs bg-red-600 hover:bg-red-700 px-2 py-1 rounded">Stop</button>
                                <button onclick="restartProcess('${p.id}')" class="text-xs bg-yellow-600 hover:bg-yellow-700 px-2 py-1 rounded">Restart</button>
                            ` : `
                                <button onclick="startProcess('${p.id}')" class="text-xs bg-green-600 hover:bg-green-700 px-2 py-1 rounded">Start</button>
                            `}
                            <button onclick="viewProcessLogs('${p.id}')" class="text-xs bg-gray-600 hover:bg-gray-500 px-2 py-1 rounded">Logs</button>
                            ${p.port && isRunning ? `<a href="http://localhost:${p.port}" target="_blank" class="text-xs bg-blue-600 hover:bg-blue-700 px-2 py-1 rounded">Open</a>` : ''}
                            ${isFailed ? `<button onclick="createFixTask('${p.id}')" class="text-xs bg-purple-600 hover:bg-purple-700 px-2 py-1 rounded">Fix with AI</button>` : ''}
                        </div>
                    </div>
                `;
            }).join('');
        }

        async function startProcess(processId) {
            const result = await api(`/processes/${processId}/start`, { method: 'POST' });
            if (result?.success) {
                showNotification('Process started');
                loadProcesses();
            }
        }

        async function stopProcess(processId) {
            const result = await api(`/processes/${processId}/stop`, { method: 'POST' });
            if (result?.success) {
                showNotification('Process stopped');
                loadProcesses();
            }
        }

        async function restartProcess(processId) {
            const result = await api(`/processes/${processId}/restart`, { method: 'POST' });
            if (result?.success) {
                showNotification('Process restarted');
                loadProcesses();
            }
        }

        async function viewProcessLogs(processId) {
            const result = await api(`/processes/${processId}/logs?lines=50`);
            if (result) {
                document.getElementById('current-task-name').textContent = `Process: ${processId}`;
                document.getElementById('output-panel').innerHTML = `<pre class="text-xs text-gray-300 whitespace-pre-wrap">${result.logs || 'No logs yet'}</pre>`;
            }
        }

        async function detectProcesses() {
            const project = currentProject === 'all' ? null : currentProject;
            if (!project) {
                showNotification('Select a project first');
                return;
            }
            
            const result = await api(`/projects/${project}/detect-processes`, { method: 'POST' });
            if (result?.success) {
                showNotification(`Detected ${result.detected.length} process(es)`);
                loadProcesses();
            }
        }

        async function createFixTask(processId) {
            const result = await api(`/processes/${processId}/create-fix-task`, { method: 'POST' });
            if (result?.success) {
                showNotification(`Created fix task: ${result.task.id}`);
                loadTasks();
            }
        }

        async function showPortsModal() {
            const ports = await api('/ports');
            if (!ports) return;
            
            let html = '<div class="space-y-2 max-h-64 overflow-y-auto">';
            
            if (ports.length === 0) {
                html += '<div class="text-gray-400 text-sm">No port assignments yet. Auto-detect processes first.</div>';
            } else {
                html += ports.map(p => `
                    <div class="flex justify-between items-center bg-gray-700 rounded p-2">
                        <div>
                            <span class="text-sm">${p.project}/${p.service}</span>
                        </div>
                        <div class="flex items-center gap-2">
                            <input type="number" value="${p.port}" 
                                   class="w-20 bg-gray-600 rounded px-2 py-1 text-sm text-center"
                                   onchange="updatePort('${p.project}', '${p.service}', this.value)">
                            <span class="${p.in_use ? 'text-green-400' : 'text-gray-400'} text-xs">${p.in_use ? '● in use' : '○ free'}</span>
                        </div>
                    </div>
                `).join('');
            }
            
            html += '</div>';
            
            // Simple modal using output panel for now
            document.getElementById('current-task-name').textContent = 'Port Assignments';
            document.getElementById('output-panel').innerHTML = html;
        }

        async function updatePort(project, service, port) {
            const result = await api('/ports/set', {
                method: 'POST',
                body: JSON.stringify({ project, service, port: parseInt(port) })
            });
            
            if (result?.success) {
                showNotification(`Port updated to ${port}`);
            } else {
                showNotification('Failed to update port - may be in use');
                showPortsModal(); // Refresh to show correct value
            }
        }

        function updateStats() {
            const stats = {
                pending: allTasks.filter(t => t.status === 'pending').length,
                running: allTasks.filter(t => t.status === 'in_progress').length,
                completed: allTasks.filter(t => t.status === 'completed').length,
                failed: allTasks.filter(t => t.status === 'failed').length,
            };
            
            document.getElementById('stat-pending').textContent = stats.pending;
            document.getElementById('stat-running').textContent = stats.running;
            document.getElementById('stat-completed').textContent = stats.completed;
            document.getElementById('stat-failed').textContent = stats.failed;
        }

        async function loadPendingReviews() {
            const reviews = await api('/tasks/pending-review');
            const panel = document.getElementById('review-panel');
            const list = document.getElementById('review-list');
            
            if (!reviews || reviews.length === 0) {
                panel.classList.add('hidden');
                return;
            }
            
            panel.classList.remove('hidden');
            list.innerHTML = reviews.map(t => `
                <div class="bg-yellow-800 rounded p-2">
                    <div class="text-sm font-medium">${t.project}</div>
                    <div class="text-xs text-yellow-200 mt-1">${t.review_prompt || t.description}</div>
                    <div class="flex gap-2 mt-2">
                        <button onclick="approveTask('${t.id}')" class="text-xs bg-green-600 hover:bg-green-700 px-2 py-1 rounded">Approve</button>
                        <button onclick="rejectTask('${t.id}')" class="text-xs bg-red-600 hover:bg-red-700 px-2 py-1 rounded">Reject</button>
                    </div>
                </div>
            `).join('');
        }

        async function approveTask(taskId) {
            await api(`/tasks/${taskId}/review`, {
                method: 'POST',
                body: JSON.stringify({ approved: true })
            });
            showNotification('Task approved');
            loadTasks();
        }

        async function rejectTask(taskId) {
            const comment = prompt('Reason for rejection (optional):');
            await api(`/tasks/${taskId}/review`, {
                method: 'POST',
                body: JSON.stringify({ approved: false, comment })
            });
            showNotification('Task rejected');
            loadTasks();
        }

        function openTaskModal() {
            document.getElementById('task-modal').classList.remove('hidden');
            document.getElementById('task-modal').classList.add('flex');
            
            // Populate project dropdown
            const select = document.getElementById('task-project');
            select.innerHTML = '';
            
            const projects = [...new Set(allTasks.map(t => t.project))];
            projects.forEach(p => {
                const opt = document.createElement('option');
                opt.value = p;
                opt.textContent = p;
                select.appendChild(opt);
            });
            
            if (currentProject !== 'all') {
                select.value = currentProject;
            }
        }

        function closeTaskModal() {
            document.getElementById('task-modal').classList.add('hidden');
        }

        async function submitTask() {
            const project = document.getElementById('task-project').value;
            const description = document.getElementById('task-description').value;
            const priority = document.getElementById('task-priority').value;
            const requiresReview = document.getElementById('task-review').checked;
            
            if (!project || !description) {
                showNotification('Please fill in all fields');
                return;
            }

            const result = await api('/tasks', {
                method: 'POST',
                body: JSON.stringify({ project, description, priority, requires_review: requiresReview })
            });

            if (result?.success) {
                showNotification('Task added');
                closeTaskModal();
                document.getElementById('task-description').value = '';
                loadTasks();
            }
        }

        function connectWebSocket() {
            const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${wsProtocol}//${window.location.host}/ws`);
            
            ws.onopen = () => {
                document.getElementById('ws-indicator').className = 'w-2 h-2 rounded-full bg-green-500';
                document.getElementById('ws-status').textContent = 'Connected';
            };
            
            ws.onclose = () => {
                document.getElementById('ws-indicator').className = 'w-2 h-2 rounded-full bg-red-500';
                document.getElementById('ws-status').textContent = 'Disconnected';
                setTimeout(connectWebSocket, 3000);
            };
            
            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                handleEvent(data);
            };
        }

        function handleEvent(event) {
            // Handle agent output streaming
            if (event.type === 'agent.output') {
                if (isLiveStreaming) {
                    appendOutput(event.content);
                }
                return;
            }
            
            // Add to activity log
            if (event.type && event.type !== 'ping' && event.type !== 'pong') {
                addActivity(event);
            }
            
            // Refresh data on relevant events
            if (event.type?.startsWith('task.') || event.type?.startsWith('agent.')) {
                loadTasks();
                loadWorkers();
            }
            
            // Refresh processes on process events
            if (event.type?.startsWith('process.')) {
                loadProcesses();
                // Show notification for failures
                if (event.type === 'process.exited' && event.status === 'failed') {
                    showNotification(`Process failed: ${event.project}/${event.process_id}`);
                }
            }
        }

        function appendOutput(content) {
            const panel = document.getElementById('output-panel');
            let pre = panel.querySelector('pre');
            
            if (!pre) {
                panel.innerHTML = '<pre class="text-xs text-gray-300 whitespace-pre-wrap"></pre>';
                pre = panel.querySelector('pre');
            }
            
            pre.textContent += content;
            panel.scrollTop = panel.scrollHeight;
        }

        function addActivity(event) {
            const container = document.getElementById('events-list');
            
            // Remove placeholder
            if (container.querySelector('.text-gray-500')) {
                container.innerHTML = '';
            }
            
            const div = document.createElement('div');
            div.className = 'text-xs py-1 border-b border-gray-700';
            
            const time = new Date().toLocaleTimeString();
            div.innerHTML = `<span class="text-gray-500">${time}</span> <span class="text-gray-300">${event.type || 'event'}</span>`;
            
            container.insertBefore(div, container.firstChild);
            
            // Limit to 50 items
            while (container.children.length > 50) {
                container.removeChild(container.lastChild);
            }
        }

        function showNotification(message) {
            const toast = document.getElementById('toast');
            toast.textContent = message;
            toast.classList.remove('hidden');
            setTimeout(() => toast.classList.add('hidden'), 3000);
        }

        async function loadAll() {
            const results = await Promise.all([loadProjects(), loadTasks(), loadWorkers()]);
            // If all returned null/empty, token might be invalid
            if (!results.some(r => r !== null)) {
                console.log('All API calls failed, showing auth');
            }
        }

        // Initialize
        (async function init() {
            console.log('Dashboard initializing, token:', authToken ? 'present' : 'missing');
            
            if (!authToken) {
                showAuthModal();
                return;
            }
            
            // Test if token is valid
            try {
                const authResp = await fetch('/status', { headers: getAuthHeaders() });
                console.log('Auth test response:', authResp.status);
                if (authResp.status === 401 || authResp.status === 403) {
                    showAuthModal();
                    return;
                }
            } catch (e) {
                console.error('Auth test failed:', e);
            }
            
            console.log('Loading data and connecting WebSocket');
            loadAll();
            connectWebSocket();
            
            // Auto-refresh every 10 seconds
            setInterval(loadAll, 10000);
        })();
    </script>
</body>
</html>
'''
