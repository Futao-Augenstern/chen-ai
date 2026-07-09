from __future__ import annotations

import json
import concurrent.futures
import logging
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Generator, List, Optional, Tuple

from tools import ToolRegistry
from memory import MemorySystem
from cache_optimizer import CacheFirstLoop, CostTracker
from prompt_compressor import PromptOptimizer
from resilience import ResilientAPIClient, CircuitBreakerOpenError
from context_manager import ContextWindowManager, ConversationSummarizer, count_tokens
from telemetry import get_tracer, get_metrics


class AgentConfig:
    """AgentLoop 全局配置常量。"""
    # 循环控制
    MAX_ITERATIONS = 5
    MAX_PARALLEL_TOOLS = 3
    MAX_FALLBACK_RETRIES = 3
    COMPLEXITY_THRESHOLD = 3

    # 断路器
    CIRCUIT_FAILURE_THRESHOLD = 5
    CIRCUIT_RECOVERY_TIMEOUT = 30.0

    # Token 限制
    PLAN_MAX_TOKENS = 1000
    VERIFY_MAX_TOKENS = 200
    THINK_MAX_TOKENS = 500
    REFLECT_MAX_TOKENS = 400

    # 复杂度检测阈值
    COMPLEXITY_MIN_CHARS = 200
    COMPLEXITY_HIGH_CHARS = 500

    # 结果截断
    RESULT_TRUNCATE_LENGTH = 2000
    SPAN_MESSAGE_TRUNCATE = 100


class ExecutionMode(Enum):
    """Defines the execution mode for the agent loop.

    Values:
        SIMPLE: Standard single-pass execution (original behavior).
        PLAN:   Plan-Execute-Verify mode for complex, multi-step tasks.
        TEAM:   Multi-agent collaboration mode with role-based delegation.
        AUTO:   Automatically select the best mode based on task complexity.
    """
    SIMPLE = "simple"
    PLAN = "plan"
    TEAM = "team"
    AUTO = "auto"


@dataclass
class ToolCallPlan:
    """Represents a plan for tool calls generated during the think phase.

    Attributes:
        tools: List of tool invocations, each with a 'name' and 'params' dict.
        reasoning: Explanation of why these tools were selected.
    """
    tools: List[Dict[str, Any]] = field(default_factory=list)
    reasoning: str = ""


@dataclass
class ReflectionResult:
    """Result of the self-reflection phase that evaluates tool output sufficiency.

    Attributes:
        is_sufficient: Whether the current results adequately answer the query.
        missing_info: Description of what information is still needed.
        next_steps: Additional tool calls to gather missing information.
    """
    is_sufficient: bool = True
    missing_info: str = ""
    next_steps: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class AgentRole:
    """Represents a role in the multi-agent collaboration system.

    Each role encapsulates a distinct perspective, expertise, and set of
    available tools that guide how the agent responds when acting in that role.

    Attributes:
        name: Unique identifier for the role (e.g., 'planner', 'reviewer').
        expertise: Natural-language description of what this role specializes in.
        system_prompt: The system prompt assigned when the agent adopts this role.
        tools: List of tool names available to this role. An empty list means
               all registered tools are available.
    """
    name: str
    expertise: str = ""
    system_prompt: str = ""
    tools: List[str] = field(default_factory=list)


@dataclass
class TaskRecord:
    """Internal record for tracking a single (sub)task's lifecycle.

    Attributes:
        task_id: Unique identifier for the task.
        description: Human-readable description of what the task does.
        status: Current status -- one of pending, running, completed, failed, cancelled.
        start_time: Unix timestamp when execution began (None if not started).
        end_time: Unix timestamp when execution ended (None if still running).
        result: The result produced by the task (None if not completed).
        error: Error message if the task failed.
        retries: Number of retry attempts so far.
        max_retries: Maximum allowed retry attempts.
        parent_id: ID of the parent task, if this is a subtask.
        dependencies: List of task IDs that must complete before this task can run.
    """
    task_id: str
    description: str
    status: str = "pending"
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    result: Any = None
    error: Optional[str] = None
    retries: int = 0
    max_retries: int = 3
    parent_id: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)


class TaskTracker:
    """Tracks the execution status of all (sub)tasks throughout their lifecycle.

    Provides capabilities for task creation, status updates, retries,
    cancellation, and aggregate reporting.  Tasks transition through states:
    pending -> running -> completed / failed / cancelled.

    Usage::

        tracker = TaskTracker()
        tid = tracker.create_task("Fetch data from API")
        tracker.start_task(tid)
        # ... do work ...
        tracker.complete_task(tid, result_data)
        print(tracker.export_report())
    """

    def __init__(self) -> None:
        self._tasks: Dict[str, TaskRecord] = {}
        self._history: List[TaskRecord] = []

    # ------------------------------------------------------------------
    # Lifecycle methods
    # ------------------------------------------------------------------

    def create_task(
        self,
        description: str,
        dependencies: Optional[List[str]] = None,
        max_retries: int = 3,
        parent_id: Optional[str] = None,
    ) -> str:
        """Create a new task and return its unique ID.

        Args:
            description: Human-readable description of the task.
            dependencies: List of task IDs that must complete first.
            max_retries: Maximum number of retry attempts.
            parent_id: ID of the parent task (for subtask hierarchies).

        Returns:
            A short unique task ID string.
        """
        task_id = str(uuid.uuid4())[:8]
        record = TaskRecord(
            task_id=task_id,
            description=description,
            status="pending",
            dependencies=dependencies or [],
            max_retries=max_retries,
            parent_id=parent_id,
        )
        self._tasks[task_id] = record
        return task_id

    def start_task(self, task_id: str) -> None:
        """Mark a task as running and record its start time."""
        if task_id in self._tasks:
            self._tasks[task_id].status = "running"
            self._tasks[task_id].start_time = time.time()

    def complete_task(self, task_id: str, result: Any) -> None:
        """Mark a task as completed, store its result, and archive it."""
        if task_id in self._tasks:
            record = self._tasks[task_id]
            record.status = "completed"
            record.end_time = time.time()
            record.result = result
            self._history.append(record)
            del self._tasks[task_id]

    def fail_task(self, task_id: str, error: str) -> None:
        """Mark a task as failed with the given error message."""
        if task_id in self._tasks:
            record = self._tasks[task_id]
            record.status = "failed"
            record.end_time = time.time()
            record.error = error

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task.  Returns True if the task existed and was cancelled."""
        if task_id in self._tasks:
            record = self._tasks[task_id]
            record.status = "cancelled"
            record.end_time = time.time()
            self._history.append(record)
            del self._tasks[task_id]
            return True
        return False

    def retry_task(self, task_id: str) -> bool:
        """Reset a failed task to pending if retries remain.  Returns True on success."""
        if task_id in self._tasks:
            record = self._tasks[task_id]
            if record.retries < record.max_retries:
                record.retries += 1
                record.status = "pending"
                record.error = None
                return True
        return False

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """Return the TaskRecord for a given task ID, or None."""
        return self._tasks.get(task_id)

    def get_pending_tasks(self) -> List[TaskRecord]:
        """Return all tasks currently in 'pending' status."""
        return [t for t in self._tasks.values() if t.status == "pending"]

    def get_running_tasks(self) -> List[TaskRecord]:
        """Return all tasks currently in 'running' status."""
        return [t for t in self._tasks.values() if t.status == "running"]

    def all_dependencies_met(self, task_id: str) -> bool:
        """Check whether all dependencies of a task have been completed."""
        record = self._tasks.get(task_id)
        if not record or not record.dependencies:
            return True
        for dep_id in record.dependencies:
            dep_record = self._tasks.get(dep_id)
            if dep_record is None:
                # Dependency may have already been archived to history
                dep_in_history = any(
                    h.task_id == dep_id and h.status == "completed"
                    for h in self._history
                )
                if not dep_in_history:
                    return False
            elif dep_record.status != "completed":
                return False
        return True

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def export_report(self) -> Dict[str, Any]:
        """Generate a comprehensive report of all task execution statistics.

        Returns a dict with aggregate counts, total duration, and per-task details.
        """
        all_tasks = list(self._tasks.values()) + self._history
        completed = [t for t in all_tasks if t.status == "completed"]
        failed = [t for t in all_tasks if t.status == "failed"]
        cancelled = [t for t in all_tasks if t.status == "cancelled"]
        running = [t for t in all_tasks if t.status == "running"]
        pending = [t for t in all_tasks if t.status == "pending"]

        total_duration = 0.0
        for t in completed:
            if t.start_time and t.end_time:
                total_duration += t.end_time - t.start_time

        return {
            "total": len(all_tasks),
            "completed": len(completed),
            "failed": len(failed),
            "cancelled": len(cancelled),
            "running": len(running),
            "pending": len(pending),
            "total_duration_seconds": round(total_duration, 2),
            "tasks": [
                {
                    "id": t.task_id,
                    "description": t.description[:100],
                    "status": t.status,
                    "retries": t.retries,
                    "error": t.error,
                }
                for t in all_tasks
            ],
        }


class PlanExecutor:
    """Implements the Plan -> Execute -> Verify cycle for complex task handling.

    When a task is too complex for a single-pass execution, the PlanExecutor
    decomposes it into subtasks with dependency tracking, executes them (with
    parallel execution of independent subtasks), and verifies each step's result
    before proceeding to dependent steps.

    Usage::

        executor = PlanExecutor(agent)
        result = executor.run_plan("Build a web scraper that collects and analyzes data")
        print(executor.visualize_plan())
    """

    def __init__(self, agent: AgentLoop) -> None:
        """Initialize the PlanExecutor with a reference to the parent AgentLoop.

        Args:
            agent: The AgentLoop instance that provides AI, tools, and resilience.
        """
        self.agent = agent
        self._plan: List[Dict[str, Any]] = []
        self._results: Dict[str, Any] = {}
        self._status: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Plan
    # ------------------------------------------------------------------

    def plan(self, task: str) -> List[Dict[str, Any]]:
        """Decompose a complex task into an ordered list of subtasks.

        Uses the LLM to analyze the task and produce a structured plan where
        each step includes an ID, description, dependencies, and suggested tools.

        Each step dict contains:
            - id:           unique step identifier (string)
            - description:  what this step accomplishes (string)
            - dependencies: list of step IDs that must complete first (list of strings)
            - tools:        suggested tool names to use (list of strings)
            - status:       tracked as pending/running/completed/failed

        Args:
            task: The complex task description to decompose.

        Returns:
            A list of step dicts representing the execution plan.
        """
        prompt = (
            "You are a task planner. Break down the following complex task into "
            "manageable subtasks. Each subtask should be a focused unit of work.\n\n"
            "Task: {0}\n\n"
            "Return a JSON object with a 'steps' array. Each step must have:\n"
            '  "id": unique step identifier (string),\n'
            '  "description": what this step accomplishes (string),\n'
            '  "dependencies": list of step IDs that must complete first (array of strings),\n'
            '  "tools": suggested tool names to use (array of strings)\n\n'
            "Ensure the plan is logically ordered and dependencies are correct.\n"
            "Return ONLY valid JSON, no other text."
        ).format(task)

        if self.agent.ai.client is None:
            return [{"id": "1", "description": task, "dependencies": [], "tools": [], "status": "pending"}]

        try:
            response = self.agent.resilience.call(
                lambda: self.agent.ai.client.chat.completions.create(
                    model=self.agent.ai.model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a precise task planning assistant. "
                                "Always return valid JSON."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0,
                    max_tokens=AgentConfig.PLAN_MAX_TOKENS,
                    response_format={"type": "json_object"},
                )
            )
            content = response.choices[0].message.content or "{}"
            data = json.loads(content)
            steps = data.get("steps", [])

            for step in steps:
                step.setdefault("status", "pending")
                step.setdefault("dependencies", [])
                step.setdefault("tools", [])

            self._plan = steps
            self._results = {}
            self._status = {s["id"]: "pending" for s in steps}
            return steps
        except Exception as e:
            logging.getLogger(__name__).warning(f"PlanExecutor.plan LLM调用失败，使用fallback: {e}")
            # Fallback: simple linear decomposition by chunking the task text
            words = task.split()
            chunk_size = max(1, len(words) // 3)
            steps = []
            for i in range(0, len(words), chunk_size):
                chunk = " ".join(words[i:i + chunk_size])
                step_id = f"step_{i // chunk_size + 1}"
                steps.append({
                    "id": step_id,
                    "description": chunk,
                    "dependencies": [f"step_{i // chunk_size}"] if i > 0 else [],
                    "tools": [],
                    "status": "pending",
                })
            self._plan = steps
            self._results = {}
            self._status = {s["id"]: "pending" for s in steps}
            return steps

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def execute_step(self, step: Dict[str, Any]) -> Any:
        """Execute a single subtask and return its result.

        Uses the agent's think phase to determine which tools to invoke,
        then executes them.  Falls back to a direct LLM call for reasoning-only steps.

        Args:
            step: A step dict with at least 'id' and 'description' keys.

        Returns:
            The result of executing the step (tool result, LLM response, etc.).
        """
        self._status[step["id"]] = "running"
        description = step["description"]

        try:
            plan_result = self.agent._think_llm_structured(description)
            tools = plan_result.tools

            if tools:
                result = self.agent._execute_tools_parallel(tools)
            else:
                result = self.agent.ai.chat(description)

            self._results[step["id"]] = result
            self._status[step["id"]] = "completed"
            return result
        except Exception as e:
            logging.getLogger(__name__).warning(f"PlanExecutor.execute_step失败 (step={step['id']}): {e}")
            self._status[step["id"]] = "failed"
            self._results[step["id"]] = str(e)
            raise

    # ------------------------------------------------------------------
    # Verify
    # ------------------------------------------------------------------

    def verify_step(self, step: Dict[str, Any], result: Any) -> bool:
        """Verify that a subtask's result satisfies the requirements.

        Uses the LLM to evaluate whether the result adequately addresses
        the step's description.

        Args:
            step: The step dict that was executed.
            result: The result produced by execute_step.

        Returns:
            True if the result is satisfactory, False otherwise.
        """
        prompt = (
            "You are a quality verifier. Determine if the following result "
            "satisfactorily completes the given task step.\n\n"
            "Step: {0}\n"
            "Result: {1}\n\n"
            'Return JSON: {{"satisfactory": true/false, "reason": "explanation"}}'
        ).format(step["description"], str(result)[:500])

        if self.agent.ai.client is None:
            return True

        try:
            response = self.agent.resilience.call(
                lambda: self.agent.ai.client.chat.completions.create(
                    model=self.agent.ai.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    max_tokens=AgentConfig.VERIFY_MAX_TOKENS,
                    response_format={"type": "json_object"},
                )
            )
            content = response.choices[0].message.content or '{"satisfactory": true}'
            data = json.loads(content)
            return data.get("satisfactory", True)
        except Exception as e:
            logging.getLogger(__name__).warning(f"PlanExecutor.verify_step验证失败: {e}")
            return True  # Default to satisfactory on verification error

    # ------------------------------------------------------------------
    # Run full plan
    # ------------------------------------------------------------------

    def _topological_sort(self) -> List[List[str]]:
        """Group step IDs into dependency levels for parallel execution.

        Each level contains steps whose dependencies are all satisfied by
        steps in previous levels.  Steps within the same level can be
        executed in parallel.

        Returns:
            A list of lists, where each inner list contains step IDs that
            can run in parallel at that level.
        """
        if not self._plan:
            return []

        step_ids = set(s["id"] for s in self._plan)
        dep_map = {s["id"]: set(s.get("dependencies", [])) for s in self._plan}

        levels: List[List[str]] = []
        remaining = set(step_ids)

        while remaining:
            current_level: List[str] = []
            for sid in list(remaining):
                deps = dep_map.get(sid, set())
                if deps.issubset(step_ids - remaining):
                    current_level.append(sid)

            if not current_level:
                # Circular dependency or error -- add remaining linearly
                levels.append(list(remaining))
                break

            levels.append(current_level)
            remaining -= set(current_level)

        return levels

    def run_plan(self, task: str) -> Dict[str, Any]:
        """Execute the full Plan -> Execute -> Verify cycle.

        Steps:
        1. Call plan() to decompose the task.
        2. Topologically sort steps into dependency levels.
        3. Execute each level in parallel, verify each step's result.
        4. Return a summary of all results.

        Args:
            task: The complex task description.

        Returns:
            A dict with keys:
                - status:       'success', 'partial', or 'no_plan'
                - results:      dict mapping step_id -> result
                - step_statuses: dict mapping step_id -> status string
                - summary:      human-readable execution summary
        """
        steps = self.plan(task)
        if not steps:
            return {"status": "no_plan", "results": {}, "summary": "No steps planned."}

        levels = self._topological_sort()

        for level in levels:
            level_steps = [s for s in steps if s["id"] in level]

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(len(level_steps), self.agent.max_parallel_tools)
            ) as executor:
                futures = {}
                for step in level_steps:
                    futures[executor.submit(self.execute_step, step)] = step

                for future in concurrent.futures.as_completed(futures):
                    step = futures[future]
                    try:
                        result = future.result()
                        verified = self.verify_step(step, result)
                        if not verified:
                            self._status[step["id"]] = "needs_review"
                    except Exception as e:
                        logging.getLogger(__name__).warning(f"PlanExecutor.run_plan步骤执行失败 (step={step['id']}): {e}")
                        self._status[step["id"]] = "failed"

        all_completed = all(
            self._status.get(s["id"]) in ("completed", "needs_review")
            for s in steps
        )

        return {
            "status": "success" if all_completed else "partial",
            "results": dict(self._results),
            "step_statuses": dict(self._status),
            "summary": (
                f"Executed {len(steps)} steps: "
                f"{sum(1 for s in steps if self._status.get(s['id']) == 'completed')} completed, "
                f"{sum(1 for s in steps if self._status.get(s['id']) == 'failed')} failed."
            ),
        }

    # ------------------------------------------------------------------
    # Visualization
    # ------------------------------------------------------------------

    def visualize_plan(self) -> str:
        """Generate an ASCII representation of the execution plan.

        Shows each dependency level, per-step status icons, and a legend.

        Returns:
            A multi-line string with the formatted plan diagram.
        """
        if not self._plan:
            return "No plan available."

        lines: List[str] = []
        lines.append("=" * 60)
        lines.append("  EXECUTION PLAN")
        lines.append("=" * 60)

        levels = self._topological_sort()
        for i, level in enumerate(levels):
            lines.append(f"\n  Level {i + 1} (parallel):")
            lines.append("  " + "-" * 40)
            for sid in level:
                step = next((s for s in self._plan if s["id"] == sid), None)
                if step:
                    status_icon = {
                        "pending": "[ ]",
                        "running": "[>]",
                        "completed": "[x]",
                        "failed": "[!]",
                        "needs_review": "[?]",
                    }.get(self._status.get(sid, "pending"), "[ ]")

                    deps = step.get("dependencies", [])
                    dep_str = f" (depends on: {', '.join(deps)})" if deps else ""
                    lines.append(
                        f"    {status_icon} {sid}: "
                        f"{step['description'][:50]}{dep_str}"
                    )

        lines.append("\n" + "=" * 60)
        lines.append(
            "  Legend: [ ] pending  [>] running  [x] completed  "
            "[!] failed  [?] needs review"
        )
        lines.append("=" * 60)

        return "\n".join(lines)


class MultiAgentCoordinator:
    """Coordinates multiple AI agents with different roles for collaborative task solving.

    Supports role-based delegation, broadcast to all roles, and multi-round
    roundtable discussions where agents build on each other's outputs.

    Four preset roles are available out of the box:
        - planner:    Strategically decomposes tasks.
        - executor:   Carries out tasks precisely.
        - reviewer:   Critically examines outputs for quality.
        - researcher: Gathers and analyzes information.

    Usage::

        coordinator = MultiAgentCoordinator(agent)
        result = coordinator.delegate("researcher", "What is the latest in AI?")
        results = coordinator.broadcast("Analyze this code for bugs")
        debate = coordinator.roundtable("Should we use microservices?", rounds=3)
    """

    # ------------------------------------------------------------------
    # Preset role templates
    # ------------------------------------------------------------------

    PRESET_ROLES: Dict[str, AgentRole] = {
        "planner": AgentRole(
            name="planner",
            expertise="Breaking down complex tasks into structured plans",
            system_prompt=(
                "You are a strategic planner. Your role is to analyze tasks, "
                "identify key components, and create structured execution plans. "
                "Think step by step and identify dependencies between subtasks."
            ),
            tools=[],
        ),
        "executor": AgentRole(
            name="executor",
            expertise="Executing tasks precisely and efficiently",
            system_prompt=(
                "You are a precise executor. Your role is to carry out tasks "
                "accurately and efficiently. Use available tools when needed, "
                "and provide clear, actionable results."
            ),
            tools=[],
        ),
        "reviewer": AgentRole(
            name="reviewer",
            expertise="Reviewing outputs for quality, correctness, and completeness",
            system_prompt=(
                "You are a critical reviewer. Your role is to examine outputs "
                "for errors, inconsistencies, and areas of improvement. "
                "Provide constructive feedback and identify missing elements."
            ),
            tools=[],
        ),
        "researcher": AgentRole(
            name="researcher",
            expertise="Gathering information, searching, and analyzing data",
            system_prompt=(
                "You are a thorough researcher. Your role is to gather relevant "
                "information, search for data, and provide comprehensive analysis. "
                "Always cite sources and verify information accuracy."
            ),
            tools=["web_search"],
        ),
    }

    def __init__(self, agent: AgentLoop) -> None:
        """Initialize the coordinator with a reference to the parent AgentLoop.

        Preset roles (planner, executor, reviewer, researcher) are loaded
        automatically.

        Args:
            agent: The AgentLoop instance providing AI, tools, and resilience.
        """
        self.agent = agent
        self._roles: Dict[str, AgentRole] = {}
        self._usage_stats: Dict[str, int] = defaultdict(int)

        # Load preset roles
        for name, role in self.PRESET_ROLES.items():
            self._roles[name] = role

    # ------------------------------------------------------------------
    # Role management
    # ------------------------------------------------------------------

    def add_role(self, role: AgentRole) -> None:
        """Add a custom role to the coordinator.

        If a role with the same name already exists, it is replaced.

        Args:
            role: An AgentRole instance to register.
        """
        self._roles[role.name] = role

    def remove_role(self, name: str) -> bool:
        """Remove a role by name.

        Args:
            name: The name of the role to remove.

        Returns:
            True if the role was found and removed, False otherwise.
        """
        if name in self._roles:
            del self._roles[name]
            return True
        return False

    def get_role(self, name: str) -> Optional[AgentRole]:
        """Get a role by name.

        Args:
            name: The role name to look up.

        Returns:
            The AgentRole, or None if not found.
        """
        return self._roles.get(name)

    def list_roles(self) -> List[str]:
        """List all registered role names.

        Returns:
            A list of role name strings.
        """
        return list(self._roles.keys())

    # ------------------------------------------------------------------
    # Delegation
    # ------------------------------------------------------------------

    def delegate(self, role_name: str, task: str) -> str:
        """Delegate a task to a specific role for execution.

        The role's system prompt is temporarily applied, the task is executed
        via the agent's run() method, and the original system prompt is restored.

        Args:
            role_name: The name of the role to delegate to.
            task: The task description to execute.

        Returns:
            The result string from the agent's execution.

        Raises:
            ValueError: If the role_name is not registered.
        """
        role = self._roles.get(role_name)
        if not role:
            raise ValueError(
                f"Role '{role_name}' not found. "
                f"Available roles: {list(self._roles.keys())}"
            )

        self._usage_stats[role_name] += 1
        return self._execute_as_role(role, task)

    def broadcast(self, task: str) -> Dict[str, str]:
        """Broadcast a task to all registered roles and execute concurrently.

        Each role receives the same task and responds independently.  Results
        are collected in parallel using a thread pool.

        Args:
            task: The task description to broadcast.

        Returns:
            A dict mapping role_name -> result string.
        """
        results: Dict[str, str] = {}

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(self._roles), self.agent.max_parallel_tools)
        ) as executor:
            futures = {}
            for name, role in self._roles.items():
                self._usage_stats[name] += 1
                futures[executor.submit(self._execute_as_role, role, task)] = name

            for future in concurrent.futures.as_completed(futures):
                name = futures[future]
                try:
                    results[name] = future.result()
                except Exception as e:
                    logging.getLogger(__name__).warning(f"MultiAgentCoordinator.broadcast角色执行失败 (role={name}): {e}")
                    results[name] = f"[Error: {e}]"

        return results

    def roundtable(self, task: str, rounds: int = 3) -> Dict[str, Any]:
        """Conduct a multi-round discussion among all roles.

        Each round, every role responds based on the original task and the
        previous round's outputs.  This simulates a collaborative discussion
        where agents iteratively build on each other's ideas.

        Args:
            task: The discussion topic or task description.
            rounds: Number of discussion rounds (minimum 1).

        Returns:
            A dict with keys:
                - rounds:          number of rounds executed
                - discussion_log:  list of per-round dicts (role_name -> response)
                - final_outputs:   dict of the last round's responses
                - merged_result:   synthesized final answer from all roles
        """
        rounds = max(1, rounds)

        discussion_log: List[Dict[str, str]] = []
        previous_outputs: Dict[str, str] = {}

        for r in range(rounds):
            round_results: Dict[str, str] = {}

            round_context = (
                f"Round {r + 1} of {rounds} discussion.\n\n"
                f"Original task: {task}\n\n"
            )

            if previous_outputs:
                round_context += "Previous round outputs:\n"
                for name, output in previous_outputs.items():
                    round_context += f"--- {name} ---\n{output[:300]}\n\n"
                round_context += (
                    "Based on the above, provide your updated perspective.\n"
                )

            for name, role in self._roles.items():
                self._usage_stats[name] += 1
                round_results[name] = self._execute_as_role(role, round_context)

            discussion_log.append(round_results)
            previous_outputs = round_results

        merged = self.merge_results(previous_outputs)

        return {
            "rounds": rounds,
            "discussion_log": discussion_log,
            "final_outputs": previous_outputs,
            "merged_result": merged,
        }

    def merge_results(self, results: Dict[str, str]) -> str:
        """Merge results from multiple roles into a unified output.

        Uses an LLM call to synthesize the different perspectives into a
        coherent final answer.  Falls back to concatenation on error.

        Args:
            results: Dict mapping role_name -> response string.

        Returns:
            A single synthesized response string.
        """
        if not results:
            return ""

        parts = []
        for name, result in results.items():
            parts.append(f"=== {name} ===\n{result}")

        combined = "\n\n".join(parts)

        merge_prompt = (
            "Synthesize the following outputs from multiple AI roles into "
            "a single coherent response. Identify consensus, resolve conflicts, "
            "and produce a unified answer.\n\n"
            f"{combined}\n\n"
            "Unified response:"
        )

        try:
            original_prompt = self.agent.ai.system_prompt
            self.agent.ai.system_prompt = (
                "You are a synthesis expert. Combine multiple perspectives "
                "into one clear, comprehensive answer."
            )
            result = self.agent.ai.chat(merge_prompt)
            self.agent.ai.system_prompt = original_prompt
            return result
        except Exception as e:
            logging.getLogger(__name__).warning(f"MultiAgentCoordinator.merge_results合并失败: {e}")
            return combined

    def get_role_usage_stats(self) -> Dict[str, Any]:
        """Return usage statistics for each role.

        Returns:
            A dict with total_calls, by_role breakdown, and roles_registered count.
        """
        return {
            "total_calls": sum(self._usage_stats.values()),
            "by_role": dict(self._usage_stats),
            "roles_registered": len(self._roles),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _execute_as_role(self, role: AgentRole, task: str) -> str:
        """Execute a task as a specific role, restoring the original prompt after."""
        original_prompt = self.agent.ai.system_prompt
        try:
            self.agent.ai.system_prompt = role.system_prompt
            return self.agent.run(task)
        finally:
            self.agent.ai.system_prompt = original_prompt


class AgentLoop:
    """Core agent loop that orchestrates think-act-observe-reflection cycles.

    Enhanced with Plan-Execute-Verify, multi-agent collaboration, task tracking,
    and robust error recovery capabilities.

    New capabilities (backward compatible):
        - PlanExecutor:    Decompose complex tasks into subtasks with dependency management.
        - MultiAgentCoordinator: Role-based agent collaboration.
        - TaskTracker:     Lifecycle tracking for all (sub)tasks.
        - Execution modes: SIMPLE, PLAN, TEAM, AUTO (auto-detection).
        - Error recovery:  Classification-based recovery with fallback strategies.
    """

    def __init__(
        self,
        ai_chat: Any,
        memory_system: Optional[MemorySystem] = None,
        tool_registry: Optional[ToolRegistry] = None,
    ):
        self.ai = ai_chat
        self.memory = memory_system or MemorySystem()
        self.tools = tool_registry or ToolRegistry()
        self.cache_loop = CacheFirstLoop()
        self.cost_tracker = CostTracker()
        self.prompt_optimizer = PromptOptimizer()
        self.max_iterations: int = AgentConfig.MAX_ITERATIONS
        self.max_parallel_tools: int = AgentConfig.MAX_PARALLEL_TOOLS
        self.active_skill: Optional[Any] = None
        self.use_cache: bool = True
        self.use_compression: bool = False
        self.use_function_calling: bool = True
        self.use_self_reflection: bool = True
        self.resilience = ResilientAPIClient(
            max_retries=AgentConfig.MAX_FALLBACK_RETRIES,
            base_delay=1.0,
            circuit_threshold=AgentConfig.CIRCUIT_FAILURE_THRESHOLD,
            circuit_recovery=AgentConfig.CIRCUIT_RECOVERY_TIMEOUT,
        )
        self.context_manager = ContextWindowManager(
            model=self.ai.model,
            reserve_output_tokens=self.ai.max_tokens,
        )
        self.summarizer = ConversationSummarizer(self.ai)
        self._cached_tool_funcs: Optional[List[Dict[str, Any]]] = None
        self._tool_cache_version: int = 0

        # --- New: Plan-Execute and Multi-Agent components ---
        self.plan_executor = PlanExecutor(self)
        self.coordinator = MultiAgentCoordinator(self)
        self.task_tracker = TaskTracker()
        self.execution_mode = ExecutionMode.AUTO
        self.max_fallback_retries: int = AgentConfig.MAX_FALLBACK_RETRIES
        self.complexity_threshold: int = AgentConfig.COMPLEXITY_THRESHOLD

    # ------------------------------------------------------------------
    # Execution mode control
    # ------------------------------------------------------------------

    def set_execution_mode(self, mode: str | ExecutionMode) -> None:
        """Set the execution mode for the agent loop.

        Args:
            mode: One of 'simple', 'plan', 'team', 'auto', or an ExecutionMode enum value.

        Raises:
            ValueError: If the mode string is not a valid ExecutionMode value.
        """
        if isinstance(mode, str):
            mode = ExecutionMode(mode)
        self.execution_mode = mode

    def _detect_complexity(self, message: str) -> int:
        """Detect the complexity of a user message on a 0-10 scale.

        Higher scores indicate tasks that may benefit from Plan-Execute or
        Team execution modes.  The score is based on multiple heuristics:

        Heuristics:
            - Message length (200+ chars: +1, 500+ chars: +2)
            - Sentence count (3+: +1, 6+: +2)
            - Multi-step indicators (first/then/next/步骤/首先 etc.)
            - Conjunction count (and/also/同时/并且 etc.)
            - Tool diversity (references to search, analyze, create, compare, etc.)

        Args:
            message: The user's input message.

        Returns:
            An integer complexity score from 0 to 10.
        """
        score = 0

        # Length-based
        if len(message) > AgentConfig.COMPLEXITY_MIN_CHARS:
            score += 1
        if len(message) > AgentConfig.COMPLEXITY_HIGH_CHARS:
            score += 2

        # Sentence count
        sentences = re.split(r'[.!?。！？\n]+', message)
        sentences = [s.strip() for s in sentences if s.strip()]
        if len(sentences) > 3:
            score += 1
        if len(sentences) > 6:
            score += 2

        # Multi-step indicators
        multi_step_patterns = [
            r'\b(?:first|then|next|after|finally|lastly|second|third)\b',
            r'\b(?:首先|然后|接着|最后|其次|第一步|第二步|第三步)\b',
            r'\b(?:step\s*\d|步骤\s*\d)\b',
        ]
        for pattern in multi_step_patterns:
            if re.search(pattern, message, re.IGNORECASE):
                score += 1
                break

        # Conjunction indicators (multiple tasks joined)
        conjunction_count = len(re.findall(
            r'\b(?:and|also|additionally|furthermore|meanwhile|simultaneously'
            r'|同时|并且|另外|还有|以及)\b',
            message, re.IGNORECASE,
        ))
        if conjunction_count > 2:
            score += 1

        # Tool diversity indicators
        tool_indicators = [
            r'\b(?:search|搜索|查|find|look\s*up)\b',
            r'\b(?:analyze|分析|examine|investigate)\b',
            r'\b(?:create|make|build|generate|创建|生成|构建)\b',
            r'\b(?:compare|比较|contrast|versus|vs)\b',
            r'\b(?:file|文件|read|write|读取|写入)\b',
            r'\b(?:code|代码|run|execute|运行|执行)\b',
        ]
        tool_count = sum(
            1 for p in tool_indicators if re.search(p, message, re.IGNORECASE)
        )
        if tool_count >= 2:
            score += 1
        if tool_count >= 4:
            score += 2

        return min(score, 10)

    # ------------------------------------------------------------------
    # Advanced execution methods
    # ------------------------------------------------------------------

    def run_auto(self, message: str) -> str:
        """Automatically select the best execution mode based on task complexity.

        If execution_mode is explicitly set to SIMPLE/PLAN/TEAM, that mode is
        used directly.  In AUTO mode, complexity detection determines whether
        to use simple or plan execution.

        Args:
            message: The user's input message.

        Returns:
            The AI's response string.
        """
        if self.execution_mode == ExecutionMode.SIMPLE:
            return self.run(message)
        elif self.execution_mode == ExecutionMode.PLAN:
            return self.run_with_plan(message)
        elif self.execution_mode == ExecutionMode.TEAM:
            return self.run_with_team(message)

        # AUTO mode: detect complexity and choose accordingly
        complexity = self._detect_complexity(message)
        if complexity >= self.complexity_threshold:
            return self.run_with_plan(message)
        return self.run(message)

    def run_with_plan(self, task: str) -> str:
        """Execute a task using the Plan-Execute-Verify pattern.

        The task is decomposed into subtasks by the PlanExecutor, executed
        with dependency-aware parallelism, and results are synthesized into
        a final answer.

        Args:
            task: The complex task description.

        Returns:
            A synthesized response string combining all plan results.
        """
        plan_result = self.plan_executor.run_plan(task)

        if plan_result["status"] == "no_plan":
            return "No plan could be generated for this task."

        results_text = json.dumps(
            plan_result["results"], default=str, ensure_ascii=False
        )[:AgentConfig.RESULT_TRUNCATE_LENGTH]

        synthesis_prompt = (
            "Based on the following plan execution results, provide a "
            "comprehensive answer to the original task.\n\n"
            f"Task: {task}\n\n"
            f"Plan:\n{self.plan_executor.visualize_plan()}\n\n"
            f"Results: {results_text}\n\n"
            f"Summary: {plan_result['summary']}\n\n"
            "Synthesized answer:"
        )

        return self.ai.chat(synthesis_prompt)

    def run_with_team(
        self, task: str, roles: Optional[List[str]] = None
    ) -> str:
        """Execute a task using multi-agent collaboration (broadcast mode).

        All registered roles (or a subset if specified) process the task in
        parallel, and their responses are merged into a unified answer.

        Args:
            task: The task description.
            roles: Optional list of role names to use. If None, all roles participate.

        Returns:
            A merged response string from all participating roles.
        """
        original_roles: Optional[Dict[str, AgentRole]] = None
        if roles:
            original_roles = dict(self.coordinator._roles)
            self.coordinator._roles = {
                name: self.coordinator.PRESET_ROLES[name]
                for name in roles
                if name in self.coordinator.PRESET_ROLES
            }

        try:
            results = self.coordinator.broadcast(task)
            merged = self.coordinator.merge_results(results)
            return merged
        finally:
            if original_roles is not None:
                self.coordinator._roles = original_roles

    def run_with_debate(
        self, task: str, roles: Optional[List[str]] = None, rounds: int = 3
    ) -> str:
        """Execute a task using multi-agent debate mode (roundtable).

        All roles (or a subset) participate in multiple rounds of discussion,
        with each round building on the previous.  The final merged result
        represents the consensus view.

        Args:
            task: The discussion topic or task description.
            roles: Optional list of role names. If None, all roles participate.
            rounds: Number of discussion rounds (default 3, minimum 1).

        Returns:
            The merged consensus response string.
        """
        original_roles: Optional[Dict[str, AgentRole]] = None
        if roles:
            original_roles = dict(self.coordinator._roles)
            self.coordinator._roles = {
                name: self.coordinator.PRESET_ROLES[name]
                for name in roles
                if name in self.coordinator.PRESET_ROLES
            }

        try:
            debate_result = self.coordinator.roundtable(task, rounds=rounds)
            return debate_result["merged_result"]
        finally:
            if original_roles is not None:
                self.coordinator._roles = original_roles

    # ------------------------------------------------------------------
    # Error recovery
    # ------------------------------------------------------------------

    def _handle_execution_error(
        self, error: Exception, context: str = ""
    ) -> Dict[str, Any]:
        """Analyze an execution error and determine the recovery strategy.

        Classifies errors into types and selects an appropriate strategy:

        Error types:
            - network:  Connection/timeout issues -> retry with backoff
            - api:      API-level errors (429, 500, etc.) -> retry
            - tool:     Tool execution failures -> degrade to fallback chat
            - timeout:  Operation timeout -> retry with increased timeout
            - unknown:  Unrecognized errors -> ask user for guidance

        Args:
            error: The exception that occurred.
            context: Optional context about what was being attempted.

        Returns:
            A dict with keys:
                - error_type:  classified error type string
                - strategy:    'retry', 'degrade', 'skip', or 'ask_user'
                - message:     human-readable diagnostic message
        """
        error_str = str(error).lower()

        # Network errors
        if any(kw in error_str for kw in [
            'timeout', 'connection', 'network', 'socket', 'timed out',
        ]):
            return {
                "error_type": "network",
                "strategy": "retry",
                "message": f"Network error during '{context}': {error}. "
                           f"Will retry with backoff.",
            }

        # API errors
        if any(kw in error_str for kw in [
            'api', 'rate limit', '429', '503', '500', 'unauthorized', '401',
        ]):
            return {
                "error_type": "api",
                "strategy": "retry",
                "message": f"API error during '{context}': {error}. Will retry.",
            }

        # Tool errors
        if any(kw in error_str for kw in [
            'tool', 'not found', 'no such', 'file not found',
        ]):
            return {
                "error_type": "tool",
                "strategy": "degrade",
                "message": f"Tool error during '{context}': {error}. "
                           f"Falling back to direct chat.",
            }

        # Timeout errors (more specific after network check)
        if any(kw in error_str for kw in ['timeout', 'timed out']):
            return {
                "error_type": "timeout",
                "strategy": "retry",
                "message": f"Timeout during '{context}': {error}. "
                           f"Will retry with increased timeout.",
            }

        # Unknown
        return {
            "error_type": "unknown",
            "strategy": "ask_user",
            "message": f"Unexpected error during '{context}': {error}.",
        }

    def fallback_chat(self, message: str) -> str:
        """Fallback chat mode that bypasses tools and uses direct LLM response.

        Used when tool execution fails repeatedly and the recovery strategy
        is 'degrade'.  Attempts up to max_fallback_retries times with
        exponential backoff.

        Args:
            message: The message to send to the LLM.

        Returns:
            The LLM's response string, or an error message if all retries fail.
        """
        last_error = None
        for attempt in range(self.max_fallback_retries):
            try:
                return self.ai.chat(message)
            except Exception as e:
                logging.getLogger(__name__).warning(f"AgentLoop.fallback_chat重试失败 (attempt={attempt+1}): {e}")
                last_error = e
                if attempt < self.max_fallback_retries - 1:
                    time.sleep(1.0 * (attempt + 1))

        return (
            f"[Fallback chat failed after {self.max_fallback_retries} "
            f"attempts: {last_error}]"
        )

    # ------------------------------------------------------------------
    # Skill management (unchanged)
    # ------------------------------------------------------------------

    def set_skill(self, skill_name: str, skill_manager: Any) -> bool:
        skill = skill_manager.get_skill(skill_name)
        if skill:
            self.active_skill = skill
            self.ai.system_prompt = skill.prompt
            skill_manager.use_skill(skill_name)
            self._cached_tool_funcs = None
            return True
        return False

    def clear_skill(self, default_prompt: str) -> None:
        self.active_skill = None
        self.ai.system_prompt = default_prompt
        self._cached_tool_funcs = None

    # ------------------------------------------------------------------
    # Tool function building (unchanged)
    # ------------------------------------------------------------------

    def _build_tool_functions(self) -> List[Dict[str, Any]]:
        tool_count = len(self.tools.list_tools())
        if self._cached_tool_funcs is not None and self._tool_cache_version == tool_count:
            return self._cached_tool_funcs

        funcs: List[Dict[str, Any]] = []
        for tool_info in self.tools.list_tools():
            tool = self.tools.get(tool_info["name"])
            if tool is None:
                continue
            props: Dict[str, Any] = {}
            required: List[str] = []
            for param_name, param_desc in tool.parameters.items():
                desc = str(param_desc)
                props[param_name] = {
                    "type": "string",
                    "description": desc,
                }
                if "可选" not in desc and "optional" not in desc.lower():
                    required.append(param_name)

            func_def: Dict[str, Any] = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": required,
                    },
                },
            }
            funcs.append(func_def)
        self._cached_tool_funcs = funcs
        self._tool_cache_version = tool_count
        return funcs

    # ------------------------------------------------------------------
    # Tool execution (unchanged)
    # ------------------------------------------------------------------

    def _execute_single_tool(self, tool_info: Dict[str, Any]) -> Any:
        return self.tools.execute(tool_info["name"], **tool_info["params"])

    def _execute_tools_parallel(self, tools: List[Dict[str, Any]]) -> List[Any]:
        """并行执行多个无依赖工具 - 参考 smolagents/CrewAI 最佳实践"""
        if len(tools) <= 1:
            return self._act(tools)

        results: List[Any] = []
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(tools), self.max_parallel_tools)
        ) as executor:
            futures = [
                executor.submit(self._execute_single_tool, tool)
                for tool in tools[:self.max_parallel_tools]
            ]
            for future in concurrent.futures.as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as e:
                    logging.getLogger(__name__).warning(f"AgentLoop._execute_tools_parallel工具执行失败: {e}")
                    results.append(None)

        for tool in tools[self.max_parallel_tools:]:
            results.append(self._execute_single_tool(tool))

        return [r for r in results if r is not None]

    # ------------------------------------------------------------------
    # Think phase (unchanged)
    # ------------------------------------------------------------------

    def _think_llm_structured(self, message: str) -> ToolCallPlan:
        tool_funcs = self._build_tool_functions()
        if not tool_funcs:
            return ToolCallPlan(tools=[], reasoning="no tools available")

        system_prompt = (
            "You are a tool call planner. Based on the user message, decide if tools are needed.\n"
            "Return a JSON object:\n"
            "{\n"
            '  "reasoning": "your reasoning",\n'
            '  "tools": [{"name": "tool_name", "params": {"param": "value"}}]\n'
            "}\n\n"
            "If no tools are needed, return an empty tools array."
        )

        if self.ai.client is None:
            return ToolCallPlan(tools=[], reasoning="openai not available")

        try:
            response = self.resilience.call(
                lambda: self.ai.client.chat.completions.create(
                    model=self.ai.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message},
                    ],
                    tools=tool_funcs,
                    tool_choice="auto",
                    temperature=0,
                    max_tokens=AgentConfig.THINK_MAX_TOKENS,
                    response_format={"type": "json_object"},
                )
            )
            msg = response.choices[0].message
            content = msg.content or "{}"

            try:
                data = json.loads(content)
                plan = ToolCallPlan(
                    tools=data.get("tools", []),
                    reasoning=data.get("reasoning", "JSON parsed"),
                )
                return plan
            except (json.JSONDecodeError, TypeError):
                pass

            if msg.tool_calls:
                tools: List[Dict[str, Any]] = []
                for tc in msg.tool_calls:
                    try:
                        tools.append({
                            "name": tc.function.name,
                            "params": json.loads(tc.function.arguments),
                        })
                    except json.JSONDecodeError:
                        pass
                return ToolCallPlan(
                    tools=tools,
                    reasoning="native function calling",
                )

            return ToolCallPlan(tools=[], reasoning="no tool calls needed")

        except Exception as e:
            logging.getLogger(__name__).warning(f"AgentLoop._think_llm_structured结构化思考失败，降级到关键词匹配: {e}")
            plan = self._think_keyword(message)
            return ToolCallPlan(
                tools=plan["tools"],
                reasoning="fallback to keyword matching",
            )

    def _think_llm(self, message: str) -> Dict[str, Any]:
        """兼容旧接口，返回 dict"""
        plan = self._think_llm_structured(message)
        return {"tools": plan.tools, "reasoning": plan.reasoning}

    def _think_keyword(self, message: str) -> Dict[str, Any]:
        plan: Dict[str, Any] = {"tools": []}

        keyword_rules = [
            (r"(?:搜索|查一下|帮我查|搜)\s*[:：]?\s*(.+)", "web_search", "query", False),
            (r"(?:算|计算)\s*[:：]?\s*(.+)", "calculator", "expression", False),
            (r"(?:运行|执行).*?代码\s*[:：]?\s*```(\w*)\n(.*?)```", "execute_code", "code", True),
            (r"(?:运行|执行).*?代码\s*[:：]?\s*(.+)", "execute_code", "code", False),
            (r"(?:读取|读|打开).*?文件\s*[:：]?\s*(.+)", "file_operations", "operation", False),
            (r"(?:json|JSON).*?(?:解析|处理|查询)\s*[:：]?\s*(.+)", "json_processor", "json_data", False),
            (r"(?:时间|日期|今天|现在).*?(?:几点|几号|是什么时候)", "time_utils", "operation", False),
            (r"(?:统计|计数|提取).*?(?:文本|文字)\s*[:：]?\s*(.+)", "text_processor", "text", False),
        ]

        for pattern, tool_name, param_name, dotall in keyword_rules:
            flags = re.IGNORECASE | (re.DOTALL if dotall else 0)
            m = re.search(pattern, message, flags)
            if m:
                if tool_name == "execute_code" and dotall:
                    code = m.group(2).strip()
                    plan["tools"].append({"name": tool_name, "params": {"code": code}})
                elif tool_name == "file_operations":
                    plan["tools"].append({
                        "name": tool_name,
                        "params": {"operation": "read", "path": m.group(1).strip()},
                    })
                elif tool_name == "time_utils":
                    plan["tools"].append({
                        "name": tool_name,
                        "params": {"operation": "now"},
                    })
                else:
                    plan["tools"].append({
                        "name": tool_name,
                        "params": {param_name: m.group(1).strip()},
                    })
                break

        return plan

    # ------------------------------------------------------------------
    # Reflection (unchanged)
    # ------------------------------------------------------------------

    def _reflect_on_result(
        self,
        original_message: str,
        tool_results: List[Any]
    ) -> ReflectionResult:
        if not self.use_self_reflection:
            return ReflectionResult(
                is_sufficient=True,
                missing_info="",
                next_steps=[]
            )

        result_text = "\n".join([
            f"Tool {i+1}: " + (r.content if r.success else f"Failed: {r.error}")
            for i, r in enumerate(tool_results)
        ])

        prompt = (
            "User question: {0}\n\n"
            "Tool results:\n{1}\n\n"
            "Are the current results sufficient to answer the user's question?\n"
            "If yes, return is_sufficient = true.\n"
            "If no, explain what's missing and what tools to call next.\n\n"
            'Return JSON: {{"is_sufficient": true/false, "missing_info": "", "next_steps": []}}'
        ).format(original_message, result_text)

        if self.ai.client is None:
            return ReflectionResult(is_sufficient=True, missing_info="", next_steps=[])

        try:
            response = self.resilience.call(
                lambda: self.ai.client.chat.completions.create(
                    model=self.ai.model,
                    messages=[
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0,
                    max_tokens=AgentConfig.REFLECT_MAX_TOKENS,
                    response_format={"type": "json_object"},
                )
            )
            content = response.choices[0].message.content or "{}"
            data = json.loads(content)
            return ReflectionResult(
                is_sufficient=data.get("is_sufficient", True),
                missing_info=data.get("missing_info", ""),
                next_steps=data.get("next_steps", []),
            )
        except Exception as e:
            logging.getLogger(__name__).warning(f"AgentLoop._reflect_on_result反思失败，默认认定结果充分: {e}")
            return ReflectionResult(
                is_sufficient=True,
                missing_info="",
                next_steps=[]
            )

    # ------------------------------------------------------------------
    # Act and context building (unchanged)
    # ------------------------------------------------------------------

    def _act(self, tools: List[Dict[str, Any]]) -> List[Any]:
        results: List[Any] = []
        for tool_info in tools:
            result = self.tools.execute(tool_info["name"], **tool_info["params"])
            results.append(result)
        return results

    def _build_context(
        self, original_message: str, tool_results: List[Any]
    ) -> str:
        parts: List[str] = [original_message]
        for i, result in enumerate(tool_results):
            if result is None:
                parts.append(f"\n[工具 {i+1} 执行失败]\n未知错误")
            elif result.success:
                parts.append(f"\n[工具 {i+1} 返回结果]\n{result.content}")
            else:
                parts.append(f"\n[工具 {i+1} 执行失败]\n{result.error}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Learning and message preparation (unchanged)
    # ------------------------------------------------------------------

    def _learn(self, user_message: str, ai_reply: str) -> None:
        self.memory.learn_patterns(user_message)

    def _prepare_message(self, user_message: str, span_name: str
                         ) -> Tuple[str, str, Any, Any, Any]:
        tracer = get_tracer()
        metrics = get_metrics()
        trace_id = f"req-{int(time.time() * 1000)}"
        tracer.start_trace(trace_id)
        span = tracer.start_span(span_name, message=user_message[:AgentConfig.SPAN_MESSAGE_TRUNCATE])
        metrics.counter("total_requests").add()

        if self.use_compression:
            memory_ctx = self.memory.get_memory_context()
            user_message = self.prompt_optimizer.optimize(user_message, memory_ctx)

        if self.use_function_calling:
            plan_struct = self._think_llm_structured(user_message)
            plan = {"tools": plan_struct.tools, "reasoning": plan_struct.reasoning}
        else:
            plan = self._think_keyword(user_message)

        current_message = user_message
        iterations = 0

        while plan.get("tools") and iterations < self.max_iterations:
            tool_results = self._execute_tools_parallel(plan["tools"])

            if self.use_self_reflection:
                reflection = self._reflect_on_result(current_message, tool_results)
                if not reflection.is_sufficient and reflection.next_steps:
                    plan = {"tools": reflection.next_steps}
                    current_message = self._build_context(current_message, tool_results)
                    iterations += 1
                    continue
                else:
                    current_message = self._build_context(current_message, tool_results)
                    break
            else:
                current_message = self._build_context(current_message, tool_results)
                if self.use_function_calling:
                    follow_up_struct = self._think_llm_structured(current_message)
                    follow_up = {"tools": follow_up_struct.tools, "reasoning": follow_up_struct.reasoning}
                    if not follow_up.get("tools"):
                        break
                    plan = follow_up
                iterations += 1

        enhanced_message = current_message

        memory_ctx = self.memory.get_memory_context()
        if memory_ctx:
            enhanced_message = (
                f"[相关记忆]\n{memory_ctx}\n\n[当前消息]\n{enhanced_message}"
            )

        if self.context_manager.is_overflow(self.ai.history):
            enhanced_message = self.summarizer.rolling_summary(
                self.ai.history, enhanced_message
            )
            self.ai.history = self.context_manager.truncate_messages(
                self.ai.history, preserve_system=True
            )

        return enhanced_message, user_message, tracer, metrics, span

    # ------------------------------------------------------------------
    # Finalization (unchanged)
    # ------------------------------------------------------------------

    def _finalize(self, user_message: str, reply: str, enhanced_message: str,
                  metrics: Any, tracer: Any, span: Any) -> None:
        self.memory.record_interaction(user_message, reply)
        if self.use_cache:
            self.cache_loop.update_cache(self.ai.history, {"result": reply})
        self.cost_tracker.record_request(self.ai.model, enhanced_message, reply)
        self._learn(user_message, reply)
        tracer.end_span(span, success=True)
        metrics.histogram("request_duration_ms").record(span.duration_ms)
        tracer.export()

    # ------------------------------------------------------------------
    # Core run methods (unchanged)
    # ------------------------------------------------------------------

    def run(self, user_message: str) -> str:
        enhanced_message, original_msg, tracer, metrics, span = self._prepare_message(
            user_message, "agent_loop.run")

        if self.use_cache:
            cached = self.cache_loop.check_cache(self.ai.history)
            if cached:
                self.cost_tracker.record_request(
                    self.ai.model, enhanced_message,
                    cached["result"],
                    cache_hit_tokens=count_tokens(enhanced_message) // 3,
                )
                metrics.counter("cache_hits").add()
                reply = cached["result"]
                self._finalize(original_msg, reply, enhanced_message, metrics, tracer, span)
                return reply

        reply = self.ai.chat(enhanced_message)
        self._finalize(original_msg, reply, enhanced_message, metrics, tracer, span)
        return reply

    def run_stream(self, user_message: str) -> Generator[str, None, None]:
        enhanced_message, original_msg, tracer, metrics, span = self._prepare_message(
            user_message, "agent_loop.run_stream")

        if self.use_cache:
            cached = self.cache_loop.check_cache(self.ai.history)
            if cached:
                self.cost_tracker.record_request(
                    self.ai.model, enhanced_message,
                    cached["result"],
                    cache_hit_tokens=count_tokens(enhanced_message) // 3,
                )
                metrics.counter("cache_hits").add()
                reply = cached["result"]
                self._finalize(original_msg, reply, enhanced_message, metrics, tracer, span)
                yield reply
                return

        full_reply = ""
        try:
            for chunk in self.ai.chat_stream(enhanced_message):
                full_reply += chunk
                yield chunk
        except Exception as e:
            logging.getLogger(__name__).warning(f"AgentLoop.run_stream流式响应出错: {e}")
            metrics.counter("stream_errors").add()
            tracer.add_event("stream_error", error=str(e))
            yield f"\n[流式响应出错] {e}\n"
            if full_reply:
                yield full_reply
            return

        self._finalize(original_msg, full_reply, enhanced_message, metrics, tracer, span)

    # ------------------------------------------------------------------
    # Stats and toggles (unchanged)
    # ------------------------------------------------------------------

    def get_cache_stats(self) -> Dict[str, Any]:
        return self.cache_loop.get_cache_stats()

    def get_cost_stats(self) -> Dict[str, Any]:
        return self.cost_tracker.get_stats()

    def get_compression_stats(self) -> Dict[str, Any]:
        return self.prompt_optimizer.get_stats()

    def get_resilience_stats(self) -> Dict[str, Any]:
        cb = self.resilience.circuit_breaker
        return {
            "circuit_state": cb.state,
            "failure_count": cb.failure_count,
            "failure_threshold": cb.failure_threshold,
            "recovery_timeout": cb.recovery_timeout,
        }

    def toggle_cache(self, enabled: Optional[bool] = None) -> bool:
        if enabled is not None:
            self.use_cache = enabled
        else:
            self.use_cache = not self.use_cache
        return self.use_cache

    def toggle_compression(self, enabled: Optional[bool] = None) -> bool:
        if enabled is not None:
            self.use_compression = enabled
        else:
            self.use_compression = not self.use_compression
        return self.use_compression

    def toggle_function_calling(self, enabled: Optional[bool] = None) -> bool:
        if enabled is not None:
            self.use_function_calling = enabled
        else:
            self.use_function_calling = not self.use_function_calling
        return self.use_function_calling

    def toggle_self_reflection(self, enabled: Optional[bool] = None) -> bool:
        if enabled is not None:
            self.use_self_reflection = enabled
        else:
            self.use_self_reflection = not self.use_self_reflection
        return self.use_self_reflection