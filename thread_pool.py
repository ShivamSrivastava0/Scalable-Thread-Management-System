from flask import Flask, request, redirect, url_for, render_template_string, jsonify
import threading
import queue
import time
import random
from concurrent.futures import Future
import uuid
import json
import psutil
import os
from enum import Enum
from datetime import datetime
from collections import defaultdict, deque

# ============================================================================
# ADVANCED THREAD POOL WITH PROFESSIONAL FEATURES
# ============================================================================

class TaskState(Enum):
    """Task execution states"""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TaskPriority(Enum):
    """Task priority levels"""
    LOW = 3
    NORMAL = 2
    HIGH = 1
    CRITICAL = 0

class AdvancedWorker(threading.Thread):
    """Enhanced worker thread with load balancing and work stealing"""
    
    def __init__(self, worker_id, pool):
        super().__init__(daemon=True, name=f"PoolWorker-{worker_id}")
        self.worker_id = worker_id
        self.pool = pool
        self.task_queue = queue.PriorityQueue()  # Priority-based queue
        self.current_task = None
        self.current_task_start = None
        self.completed_count = 0
        self.failed_count = 0
        self.total_execution_time = 0
        self.stop_flag = threading.Event()
        self.idle_time = 0
        self.last_idle_start = None
        
    def submit_task(self, task_id, fn, priority=TaskPriority.NORMAL):
        """Submit task to worker's queue"""
        self.task_queue.put((priority.value, time.time(), task_id, fn))
    
    def work_steal(self):
        """Attempt to steal work from idle workers"""
        workers = self.pool.workers
        candidates = []
        for w in workers:
            if w.worker_id != self.worker_id and not w.task_queue.empty():
                candidates.append(w)
        
        if candidates:
            victim = random.choice(candidates)
            try:
                item = victim.task_queue.get_nowait()
                return item
            except queue.Empty:
                pass
        return None
    
    def run(self):
        """Main worker loop with advanced task handling"""
        while not self.stop_flag.is_set():
            task_item = None
            
            try:
                # Try to get task with timeout
                task_item = self.task_queue.get(timeout=0.1)
            except queue.Empty:
                # Try work stealing if idle
                task_item = self.work_steal()
                if task_item is None:
                    if self.last_idle_start is None:
                        self.last_idle_start = time.time()
                    continue
            
            if task_item and self.last_idle_start:
                self.idle_time += time.time() - self.last_idle_start
                self.last_idle_start = None
            
            if task_item:
                _, _, task_id, fn = task_item
                self.current_task = task_id
                self.current_task_start = time.time()
                self.pool._set_task_state(task_id, TaskState.RUNNING, self.worker_id)
                
                try:
                    result = fn()
                    self.pool._set_task_result(task_id, result)
                    self.completed_count += 1
                except Exception as e:
                    self.pool._set_task_exception(task_id, e)
                    self.failed_count += 1
                finally:
                    exec_time = time.time() - self.current_task_start
                    self.total_execution_time += exec_time
                    self.current_task = None
                    self.current_task_start = None
        
        # Drain remaining tasks on shutdown
        self._drain_queue()
    
    def _drain_queue(self):
        """Complete all remaining tasks during shutdown"""
        while True:
            try:
                _, _, task_id, fn = self.task_queue.get_nowait()
                self.pool._set_task_state(task_id, TaskState.RUNNING, self.worker_id)
                try:
                    result = fn()
                    self.pool._set_task_result(task_id, result)
                    self.completed_count += 1
                except Exception as e:
                    self.pool._set_task_exception(task_id, e)
                    self.failed_count += 1
            except queue.Empty:
                break

class ScalableThreadPool:
    """Professional-grade scalable thread pool for high-performance computing"""
    
    def __init__(self, num_workers=None, enable_metrics=True):
        # Auto-detect optimal worker count
        if num_workers is None:
            num_workers = min(32, (os.cpu_count() or 4) * 2)
        
        self.num_workers = max(1, min(1000, num_workers))  # Cap at 1000
        self.enable_metrics = enable_metrics
        self.workers = [AdvancedWorker(i, self) for i in range(self.num_workers)]
        
        # Task management
        self.tasks = {}
        self.tasks_lock = threading.RLock()
        
        # Round-robin task distribution
        self.rr_counter = 0
        self.rr_lock = threading.Lock()
        
        # Metrics
        self.metrics = {
            "total_submitted": 0,
            "total_completed": 0,
            "total_failed": 0,
            "start_time": time.time(),
            "task_history": deque(maxlen=10000)
        }
        self.metrics_lock = threading.Lock()
        
        # Start all workers
        for worker in self.workers:
            worker.start()
    
    def submit(self, fn, priority=TaskPriority.NORMAL, timeout=None, meta=None):
        """Submit task to pool with advanced options"""
        task_id = str(uuid.uuid4())
        fut = Future()
        
        task_record = {
            "id": task_id,
            "future": fut,
            "state": TaskState.QUEUED,
            "result": None,
            "exception": None,
            "meta": meta or {},
            "worker_id": None,
            "submitted_time": time.time(),
            "start_time": None,
            "end_time": None,
            "execution_time": 0,
            "timeout": timeout
        }
        
        with self.tasks_lock:
            self.tasks[task_id] = task_record
        
        # Distribute to worker using round-robin
        with self.rr_lock:
            worker_idx = self.rr_counter % self.num_workers
            self.rr_counter += 1
        
        worker = self.workers[worker_idx]
        worker.submit_task(task_id, lambda: fn(), priority)
        
        with self.metrics_lock:
            self.metrics["total_submitted"] += 1
            self.metrics["task_history"].append({
                "id": task_id,
                "type": "submitted",
                "timestamp": time.time()
            })
        
        return task_id
    
    def _set_task_state(self, task_id, state, worker_id=None):
        """Update task state"""
        with self.tasks_lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                task["state"] = state
                task["worker_id"] = worker_id
                
                if state == TaskState.RUNNING:
                    task["start_time"] = time.time()
                elif state in [TaskState.COMPLETED, TaskState.FAILED]:
                    task["end_time"] = time.time()
                    if task["start_time"]:
                        task["execution_time"] = task["end_time"] - task["start_time"]
    
    def _set_task_result(self, task_id, result):
        """Set successful task result"""
        with self.tasks_lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                task["future"].set_result(result)
                task["state"] = TaskState.COMPLETED
                task["result"] = result
        
        with self.metrics_lock:
            self.metrics["total_completed"] += 1
    
    def _set_task_exception(self, task_id, exception):
        """Set task exception"""
        with self.tasks_lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                task["future"].set_exception(exception)
                task["state"] = TaskState.FAILED
                task["exception"] = str(exception)
        
        with self.metrics_lock:
            self.metrics["total_failed"] += 1
    
    def get_task_result(self, task_id, timeout=None):
        """Get task result with timeout"""
        with self.tasks_lock:
            if task_id not in self.tasks:
                raise ValueError(f"Task {task_id} not found")
            task = self.tasks[task_id]
        
        try:
            return task["future"].result(timeout=timeout)
        except Exception as e:
            raise
    
    def cancel_task(self, task_id):
        """Cancel a queued task"""
        with self.tasks_lock:
            if task_id in self.tasks:
                task = self.tasks[task_id]
                if task["state"] == TaskState.QUEUED:
                    task["state"] = TaskState.CANCELLED
                    return True
        return False
    
    def get_pool_stats(self):
        """Get comprehensive pool statistics"""
        workers_stats = []
        total_queue_size = 0
        
        for worker in self.workers:
            queue_size = worker.task_queue.qsize()
            total_queue_size += queue_size
            
            workers_stats.append({
                "id": worker.worker_id,
                "name": worker.name,
                "queue_size": queue_size,
                "current_task": worker.current_task,
                "completed": worker.completed_count,
                "failed": worker.failed_count,
                "total_time": round(worker.total_execution_time, 3),
                "idle_time": round(worker.idle_time, 3),
                "is_alive": worker.is_alive()
            })
        
        with self.metrics_lock:
            uptime = time.time() - self.metrics["start_time"]
        
        with self.tasks_lock:
            task_states = defaultdict(int)
            for task in self.tasks.values():
                task_states[task["state"].value] += 1
        
        return {
            "pool_config": {
                "total_workers": self.num_workers,
                "metrics_enabled": self.enable_metrics
            },
            "workers": workers_stats,
            "queue": {
                "total_pending": total_queue_size
            },
            "tasks": dict(task_states),
            "metrics": {
                "total_submitted": self.metrics["total_submitted"],
                "total_completed": self.metrics["total_completed"],
                "total_failed": self.metrics["total_failed"],
                "uptime_seconds": round(uptime, 3),
                "success_rate": round(
                    self.metrics["total_completed"] / max(1, self.metrics["total_submitted"]) * 100, 2
                )
            }
        }
    
    def get_all_tasks(self, limit=100, state_filter=None):
        """Get task details with optional filtering"""
        with self.tasks_lock:
            tasks_list = list(self.tasks.values())
        
        if state_filter:
            tasks_list = [t for t in tasks_list if t["state"] == state_filter]
        
        # Sort by submission time, newest first
        tasks_list.sort(key=lambda x: x["submitted_time"], reverse=True)
        
        result = []
        for task in tasks_list[:limit]:
            result.append({
                "id": task["id"],
                "state": task["state"].value,
                "worker_id": task["worker_id"],
                "meta": task["meta"],
                "result": str(task["result"])[:200] if task["result"] else None,
                "exception": task["exception"],
                "submitted_time": task["submitted_time"],
                "execution_time": round(task["execution_time"], 4),
                "wait_time": round((task["start_time"] or time.time()) - task["submitted_time"], 4)
            })
        
        return result
    
    def shutdown(self, wait=True, timeout=30):
        """Graceful shutdown with timeout"""
        print("[ThreadPool] Initiating graceful shutdown...")
        
        for worker in self.workers:
            worker.stop_flag.set()
        
        if wait:
            start = time.time()
            for worker in self.workers:
                remaining = max(0, timeout - (time.time() - start))
                if remaining > 0:
                    worker.join(timeout=remaining)
        
        print("[ThreadPool] Shutdown complete")
    
    def get_system_health(self):
        """Get system health metrics"""
        try:
            process = psutil.Process()
            cpu_percent = process.cpu_percent(interval=0.1)
            memory_info = process.memory_info()
            memory_percent = process.memory_percent()
            
            return {
                "cpu_percent": cpu_percent,
                "memory_mb": round(memory_info.rss / 1024 / 1024, 2),
                "memory_percent": memory_percent,
                "num_threads": process.num_threads()
            }
        except:
            return {"status": "unavailable"}


# ============================================================================
# FLASK WEB APPLICATION WITH PROFESSIONAL UI
# ============================================================================

app = Flask(__name__)
pool = ScalableThreadPool(num_workers=12)

MODERN_UI = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Thread Management System</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        :root {
            --primary: #2c3e50;
            --secondary: #3498db;
            --success: #27ae60;
            --warning: #f39c12;
            --danger: #e74c3c;
            --light: #ecf0f1;
            --lighter: #f8f9fa;
            --border: #bdc3c7;
            --card-bg: #ffffff;
            --text-dark: #2c3e50;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f5f6f7;
            color: var(--text-dark);
            line-height: 1.6;
            overflow-x: hidden;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }
        
        header {
            background: #ffffff;
            border-bottom: 3px solid var(--secondary);
            padding: 30px 20px;
            margin-bottom: 30px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }
        
        h1 {
            font-size: 2.2em;
            color: var(--primary);
            margin-bottom: 10px;
            letter-spacing: 0px;
            font-weight: 600;
        }
        
        .subtitle {
            color: #7f8c8d;
            font-size: 1.1em;
            opacity: 1;
        }
        
        .grid-2 {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 25px;
            margin-bottom: 30px;
        }
        
        .grid-3 {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 20px;
            margin-bottom: 30px;
        }
        
        @media (max-width: 768px) {
            .grid-2, .grid-3 { grid-template-columns: 1fr; }
        }
        
        .card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.08);
            transition: box-shadow 0.2s ease;
        }
        
        .card:hover {
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.12);
        }
        
        .card-title {
            font-size: 1.3em;
            color: var(--primary);
            margin-bottom: 15px;
            font-weight: 600;
            border-bottom: 2px solid var(--secondary);
            padding-bottom: 10px;
        }
        
        .form-group {
            margin-bottom: 15px;
        }
        
        label {
            display: block;
            margin-bottom: 6px;
            color: var(--primary);
            font-weight: 500;
        }
        
        input, select, textarea {
            width: 100%;
            padding: 10px;
            background: #f9f9f9;
            border: 1px solid var(--border);
            border-radius: 4px;
            color: var(--text-dark);
            font-size: 1em;
            transition: border-color 0.2s ease;
            font-family: inherit;
        }
        
        input:focus, select:focus, textarea:focus {
            outline: none;
            border-color: var(--secondary);
            box-shadow: 0 0 0 3px rgba(52, 152, 219, 0.1);
        }
        
        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 4px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            font-size: 1em;
            display: inline-block;
            text-decoration: none;
            text-align: center;
            margin-right: 10px;
            margin-top: 10px;
        }
        
        .btn-primary {
            background: var(--secondary);
            color: white;
        }
        
        .btn-primary:hover {
            background: #2980b9;
        }
        
        .btn-success {
            background: var(--success);
            color: white;
        }
        
        .btn-success:hover {
            background: #229954;
        }
        
        .btn-danger {
            background: var(--danger);
            color: white;
        }
        
        .btn-danger:hover {
            background: #c0392b;
        }
        
        .btn-warning {
            background: var(--warning);
            color: white;
        }
        
        .btn-warning:hover {
            background: #e67e22;
        }
        
        .btn-small {
            padding: 6px 12px;
            font-size: 0.85em;
            margin: 3px;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            margin-bottom: 20px;
        }
        
        .stat-box {
            background: var(--card-bg);
            border-left: 4px solid var(--secondary);
            border-radius: 4px;
            padding: 20px;
            text-align: center;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.08);
        }
        
        .stat-value {
            font-size: 2.2em;
            font-weight: 700;
            color: var(--secondary);
            margin-bottom: 5px;
        }
        
        .stat-label {
            font-size: 0.9em;
            color: #7f8c8d;
        }
        
        @media (max-width: 900px) {
            .stats-grid { grid-template-columns: repeat(2, 1fr); }
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }
        
        thead {
            background: #f8f9fa;
            border-bottom: 2px solid var(--border);
        }
        
        th {
            padding: 12px;
            text-align: left;
            color: var(--primary);
            font-weight: 600;
        }
        
        td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ecf0f1;
        }
        
        tbody tr:hover {
            background: #f8f9fa;
        }
        
        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85em;
            font-weight: 600;
            white-space: nowrap;
        }
        
        .status-queued {
            background: #fff3cd;
            color: #856404;
            border: 1px solid #ffc107;
        }
        
        .status-running {
            background: #d4edda;
            color: #155724;
            border: 1px solid #28a745;
        }
        
        .status-completed {
            background: #d1ecf1;
            color: #0c5460;
            border: 1px solid #17a2b8;
        }
        
        .status-failed {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        
        .status-cancelled {
            background: #e2e3e5;
            color: #383d41;
            border: 1px solid #d6d8db;
        }
        
        .code-block {
            background: #f4f4f4;
            border: 1px solid #ddd;
            border-radius: 4px;
            padding: 8px 12px;
            font-family: 'Courier New', monospace;
            font-size: 0.85em;
            overflow-x: auto;
            margin: 5px 0;
            color: #d63384;
        }
        
        .metric-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid var(--border);
        }
        
        .metric-label {
            color: #7f8c8d;
        }
        
        .metric-value {
            color: var(--secondary);
            font-weight: 600;
        }
        
        .alert {
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 15px;
            border-left: 4px solid;
        }
        
        .alert-info {
            background: #d1ecf1;
            border-color: #17a2b8;
            color: #0c5460;
        }
        
        .alert-success {
            background: #d4edda;
            border-color: #28a745;
            color: #155724;
        }
        
        .loading {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: var(--secondary);
            margin-left: 5px;
        }
        
        .worker-status {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .status-indicator {
            width: 10px;
            height: 10px;
            border-radius: 50%;
        }
        
        .status-indicator.alive {
            background: var(--success);
        }
        
        .status-indicator.dead {
            background: #bdc3c7;
        }
        
        .refresh-indicator {
            text-align: center;
            margin-top: 20px;
            font-size: 0.9em;
            color: #7f8c8d;
            opacity: 1;
        }
        
        .action-buttons {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Scalable Thread Management System</h1>
            <p class="subtitle">Professional High-Performance Thread Pool Management</p>
        </header>
        
        <!-- Task Statistics -->
        <div class="stats-grid">
            <div class="stat-box">
                <div class="stat-value" id="total-submitted">{{ stats.metrics.total_submitted }}</div>
                <div class="stat-label">Total Submitted</div>
            </div>
            <div class="stat-box">
                <div class="stat-value" id="total-completed">{{ stats.metrics.total_completed }}</div>
                <div class="stat-label">Completed</div>
            </div>
            <div class="stat-box">
                <div class="stat-value" id="total-failed">{{ stats.metrics.total_failed }}</div>
                <div class="stat-label">Failed</div>
            </div>
            <div class="stat-box">
                <div class="stat-value" id="success-rate">{{ stats.metrics.success_rate }}%</div>
                <div class="stat-label">Success Rate</div>
            </div>
        </div>
        
        <div class="grid-2">
            <!-- Submit Task Panel -->
            <div class="card">
                <div class="card-title">Submit New Task</div>
                <form id="taskForm" onsubmit="submitTask(event)">
                    <div class="form-group">
                        <label for="taskType">Task Type</label>
                        <select id="taskType" name="type" required>
                            <option value="compute">Compute (CPU-Intensive)</option>
                            <option value="io">I/O Simulation (Sleep)</option>
                            <option value="expression">Expression Evaluation</option>
                            <option value="heavy">Heavy Computation</option>
                        </select>
                    </div>
                    
                    <div class="form-group">
                        <label for="taskParam">Parameter</label>
                        <input type="text" id="taskParam" name="param" value="1000000" 
                               placeholder="Parameter value">
                    </div>
                    
                    <div class="form-group">
                        <label for="taskPriority">Priority</label>
                        <select id="taskPriority" name="priority">
                            <option value="0">CRITICAL</option>
                            <option value="1">HIGH</option>
                            <option value="2" selected>NORMAL</option>
                            <option value="3">LOW</option>
                        </select>
                    </div>
                    
                    <div class="form-group">
                        <label for="taskLabel">Label/Description</label>
                        <input type="text" id="taskLabel" name="label" 
                               placeholder="Optional task label">
                    </div>
                    
                    <div class="action-buttons">
                        <button type="submit" class="btn btn-primary">Submit Task</button>
                        <button type="button" class="btn btn-success" onclick="submitBatch()">Batch Submit (10)</button>
                    </div>
                </form>
            </div>
            
            <!-- System Health -->
            <div class="card">
                <div class="card-title">System Health</div>
                <div id="systemHealth">
                    <div class="metric-row">
                        <span class="metric-label">CPU Usage</span>
                        <span class="metric-value" id="cpu-usage">--</span>
                    </div>
                    <div class="metric-row">
                        <span class="metric-label">Memory Usage</span>
                        <span class="metric-value" id="mem-usage">--</span>
                    </div>
                    <div class="metric-row">
                        <span class="metric-label">Thread Count</span>
                        <span class="metric-value" id="thread-count">--</span>
                    </div>
                    <div class="metric-row">
                        <span class="metric-label">Pool Uptime</span>
                        <span class="metric-value" id="uptime">--</span>
                    </div>
                    <div class="metric-row">
                        <span class="metric-label">Pending Tasks</span>
                        <span class="metric-value" id="pending-tasks">--</span>
                    </div>
                </div>
                
                <div class="action-buttons" style="margin-top: 20px;">
                    <button class="btn btn-danger" onclick="shutdownPool()">Shutdown Pool</button>
                    <button class="btn btn-warning" onclick="clearCompletedTasks()">Clear Completed</button>
                </div>
            </div>
        </div>
        
        <!-- Workers Status -->
        <div class="card">
            <div class="card-title">👷 Worker Threads Status</div>
            <table>
                <thead>
                    <tr>
                        <th>Worker ID</th>
                        <th>Status</th>
                        <th>Queue Size</th>
                        <th>Current Task</th>
                        <th>Completed</th>
                        <th>Failed</th>
                        <th>Execution Time</th>
                    </tr>
                </thead>
                <tbody id="workersTable">
                    {% for worker in stats.workers %}
                    <tr>
                        <td><strong>#{{ worker.id }}</strong></td>
                        <td>
                            <div class="worker-status">
                                <div class="status-indicator {% if worker.is_alive %}alive{% else %}dead{% endif %}"></div>
                                <span>{% if worker.is_alive %}ACTIVE{% else %}INACTIVE{% endif %}</span>
                            </div>
                        </td>
                        <td><strong>{{ worker.queue_size }}</strong></td>
                        <td>
                            {% if worker.current_task %}
                                <span class="code-block" style="display:inline-block;margin:0;padding:4px 8px;font-size:0.8em;">{{ worker.current_task[:20] }}...</span>
                            {% else %}
                                <span style="color:#888;">-</span>
                            {% endif %}
                        </td>
                        <td>{{ worker.completed }}</td>
                        <td>{{ worker.failed }}</td>
                        <td>{{ worker.total_time }}s</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        
        <!-- Recent Tasks -->
        <div class="card" style="margin-top: 25px;">
            <div class="card-title">📋 Recent Tasks (Latest 50)</div>
            <table>
                <thead>
                    <tr>
                        <th>Task ID</th>
                        <th>State</th>
                        <th>Worker</th>
                        <th>Execution Time</th>
                        <th>Wait Time</th>
                        <th>Result/Error</th>
                    </tr>
                </thead>
                <tbody id="tasksTable">
                    {% for task in recent_tasks %}
                    <tr>
                        <td>
                            <span class="code-block" style="display:inline-block;margin:0;padding:4px 8px;font-size:0.75em;">{{ task.id[:12] }}</span>
                        </td>
                        <td>
                            <span class="status-badge status-{{ task.state.lower() }}">
                                {{ task.state.upper() }}
                            </span>
                        </td>
                        <td>
                            {% if task.worker_id is not none %}
                                <strong>#{{ task.worker_id }}</strong>
                            {% else %}
                                <span style="color:#888;">-</span>
                            {% endif %}
                        </td>
                        <td>{{ task.execution_time }}s</td>
                        <td>{{ task.wait_time }}s</td>
                        <td>
                            {% if task.state == 'completed' %}
                                <span style="color:var(--success);">{{ task.result }}</span>
                            {% elif task.state == 'failed' %}
                                <span style="color:var(--danger);">{{ task.exception }}</span>
                            {% else %}
                                <span style="color:#888;">-</span>
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            <div class="refresh-indicator">
                Auto-refreshing every 2 seconds
            </div>
        </div>
    </div>
    
    <script>
        // Auto-refresh every 2 seconds
        setInterval(refreshDashboard, 2000);
        
        function refreshDashboard() {
            fetch('/api/stats')
                .then(r => r.json())
                .then(data => updateUI(data))
                .catch(e => console.error('Refresh error:', e));
        }
        
        function updateUI(data) {
            // Update stats
            document.getElementById('total-submitted').textContent = data.metrics.total_submitted;
            document.getElementById('total-completed').textContent = data.metrics.total_completed;
            document.getElementById('total-failed').textContent = data.metrics.total_failed;
            document.getElementById('success-rate').textContent = data.metrics.success_rate + '%';
            
            // Update system health
            if (data.system_health.cpu_percent !== undefined) {
                document.getElementById('cpu-usage').textContent = data.system_health.cpu_percent.toFixed(2) + '%';
            }
            if (data.system_health.memory_mb !== undefined) {
                document.getElementById('mem-usage').textContent = data.system_health.memory_mb + ' MB';
            }
            if (data.system_health.num_threads !== undefined) {
                document.getElementById('thread-count').textContent = data.system_health.num_threads;
            }
            
            document.getElementById('uptime').textContent = data.metrics.uptime_seconds.toFixed(2) + 's';
            document.getElementById('pending-tasks').textContent = data.queue.total_pending;
        }
        
        function submitTask(event) {
            event.preventDefault();
            const formData = new FormData(document.getElementById('taskForm'));
            
            fetch('/api/submit', {
                method: 'POST',
                body: formData
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    alert('✅ Task submitted: ' + data.task_id);
                    refreshDashboard();
                } else {
                    alert('❌ Error: ' + data.error);
                }
            })
            .catch(e => alert('Error: ' + e));
        }
        
        function submitBatch() {
            const type = document.getElementById('taskType').value;
            const priority = document.getElementById('taskPriority').value;
            
            for (let i = 0; i < 10; i++) {
                const form = new FormData();
                form.append('type', type);
                form.append('param', Math.random() * 5000000 | 0);
                form.append('priority', priority);
                form.append('label', 'Batch #' + i);
                
                fetch('/api/submit', {
                    method: 'POST',
                    body: form
                });
            }
            alert('✅ Submitted 10 batch tasks');
            refreshDashboard();
        }
        
        function shutdownPool() {
            if (confirm('⚠️ Shutdown the entire thread pool? This will stop all operations.')) {
                fetch('/api/shutdown', {method: 'POST'})
                    .then(() => alert('Pool shutdown initiated'))
                    .catch(e => alert('Error: ' + e));
            }
        }
        
        function clearCompletedTasks() {
            fetch('/api/clear-completed', {method: 'POST'})
                .then(r => r.json())
                .then(data => alert('Cleared ' + data.cleared + ' completed tasks'))
                .catch(e => alert('Error: ' + e));
        }
        
        // Initial refresh
        refreshDashboard();
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    """Main dashboard"""
    stats = pool.get_pool_stats()
    recent_tasks = pool.get_all_tasks(limit=50)
    return render_template_string(MODERN_UI, stats=stats, recent_tasks=recent_tasks)

@app.route("/api/stats")
def api_stats():
    """Get pool statistics"""
    stats = pool.get_pool_stats()
    health = pool.get_system_health()
    return jsonify({
        **stats,
        "system_health": health
    })

@app.route("/api/submit", methods=["POST"])
def api_submit():
    """Submit a new task"""
    try:
        task_type = request.form.get("type", "compute")
        param = request.form.get("param", "1000000")
        priority = int(request.form.get("priority", "2"))
        label = request.form.get("label", "")
        
        # Convert priority to enum
        try:
            priority_enum = list(TaskPriority)[priority]
        except:
            priority_enum = TaskPriority.NORMAL
        
        # Define task functions
        if task_type == "compute":
            n = int(param) if param.isdigit() else 1000000
            def compute_task():
                result = 0
                for i in range(n):
                    result += (i * 31) ^ (i >> 3)
                return result
            fn = compute_task
        
        elif task_type == "io":
            secs = float(param) if param else 1.0
            def io_task():
                time.sleep(secs)
                return f"I/O operation completed in {secs}s"
            fn = io_task
        
        elif task_type == "expression":
            expr = param
            def expr_task():
                return eval(expr)
            fn = expr_task
        
        elif task_type == "heavy":
            iterations = int(param) if param.isdigit() else 10000000
            def heavy_task():
                result = 0
                for i in range(iterations):
                    result += sum(j for j in range(100) if j % 2 == 0)
                return result
            fn = heavy_task
        
        else:
            fn = lambda: "default"
        
        meta = {
            "type": task_type,
            "label": label,
            "param": param,
            "submitted_by": request.remote_addr
        }
        
        task_id = pool.submit(fn, priority=priority_enum, meta=meta)
        return jsonify({"success": True, "task_id": task_id})
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400

@app.route("/api/task/<task_id>")
def api_get_task(task_id):
    """Get specific task details"""
    try:
        with pool.tasks_lock:
            if task_id not in pool.tasks:
                return jsonify({"error": "Task not found"}), 404
            task = pool.tasks[task_id]
        
        return jsonify({
            "id": task["id"],
            "state": task["state"].value,
            "result": str(task["result"])[:1000] if task["result"] else None,
            "exception": task["exception"],
            "execution_time": task["execution_time"],
            "meta": task["meta"]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/clear-completed", methods=["POST"])
def api_clear_completed():
    """Clear completed tasks"""
    try:
        count = 0
        with pool.tasks_lock:
            tasks_to_remove = [
                tid for tid, task in pool.tasks.items()
                if task["state"] == TaskState.COMPLETED
            ]
            for tid in tasks_to_remove:
                del pool.tasks[tid]
                count += 1
        
        return jsonify({"cleared": count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/shutdown", methods=["POST"])
def api_shutdown():
    """Shutdown the pool"""
    def shutdown_async():
        time.sleep(1)
        pool.shutdown(wait=True)
    
    threading.Thread(target=shutdown_async, daemon=True).start()
    return jsonify({"status": "shutting down"})

if __name__ == "__main__":
    print("\n" + "="*80)
    print(" SCALABLE THREAD MANAGEMENT SYSTEM".center(80))
    print("="*80)
    print(f"\n✅ Thread Pool initialized with {pool.num_workers} worker threads")
    print(f"📊 Dashboard: http://127.0.0.1:5000")
    print(f"🔗 API Endpoint: http://127.0.0.1:5000/api/stats")
    print("\n" + "="*80 + "\n")
    
    try:
        app.run(debug=False, host="127.0.0.1", port=5000, threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down gracefully...")
        pool.shutdown()
        print("✅ Shutdown complete")
