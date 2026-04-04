"""Custom tools for the ER Query ADK agent.

This module contains tool functions that are registered directly with the
agent (not via MCP). Includes a non-blocking long-running task pattern.

Non-blocking pattern:
    1. `submit_long_task` — starts a background asyncio.Task, returns
       immediately with status="submitted". The agent can respond to the
       user right away.
    2. The background task runs independently, updating session state
       (via a shared dict) when it completes.
    3. `check_task_status` — lets the agent (or a callback) poll the
       current task state.
    4. A `before_agent_callback` checks whether a background task finished
       between user turns and injects a notification into state so the
       agent can inform the user proactively.
"""

import asyncio
import logging
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)

# In-memory store for background task state.
# In production, this would be a database or session state.
_task_registry: dict[str, dict] = {}


async def _background_work(task_name: str, duration: int = 10) -> None:
    """Simulate a long-running background job.

    Runs in a separate asyncio Task. Updates _task_registry when done.

    Args:
        task_name: The name of the task to run.
        duration: How long to sleep in seconds (default 5).
    """
    logger.info("Background task '%s' started (duration=%ds)", task_name, duration)
    await asyncio.sleep(duration)

    _task_registry[task_name] = {
        "status": "completed",
        "task_name": task_name,
        "duration_seconds": duration,
        "message": f"Task '{task_name}' finished successfully after {duration}s.",
    }
    logger.info("Background task '%s' completed", task_name)


def submit_long_task(task_name: str, duration: int, tool_context: ToolContext) -> dict:
    """Submit a dummy long-running task that runs in the background.

    This tool returns immediately with status 'submitted'. The actual work
    runs asynchronously in the background for the specified duration.
    Use check_task_status to poll for completion, or the agent will be
    notified automatically on the next turn.

    Args:
        task_name: A short name for the task (e.g., 'data_sync').
        duration: How long the task should run in seconds (e.g., 5).

    Returns:
        A dict with 'status', 'task_name', 'duration', and 'message'
        confirming the task was submitted.

    Example return value:
        {
            'status': 'submitted',
            'task_name': 'data_sync',
            'duration': 5,
            'message': "Task 'data_sync' submitted. It will complete in ~5 seconds."
        }
    """
    # Mark as in-progress in registry
    _task_registry[task_name] = {
        "status": "in_progress",
        "task_name": task_name,
    }

    # Update session state
    tool_context.state["task_name"] = task_name
    tool_context.state["task_status"] = "in_progress"

    # Fire-and-forget: schedule the background work
    loop = asyncio.get_event_loop()
    loop.create_task(_background_work(task_name, duration=duration))

    return {
        "status": "submitted",
        "task_name": task_name,
        "duration": duration,
        "message": f"Task '{task_name}' submitted. It will complete in ~{duration} seconds.",
    }


def check_task_status(task_name: str, tool_context: ToolContext) -> dict:
    """Check the current status of a previously submitted background task.

    Use this tool when the user asks about the status of a running task,
    or when you need to verify if a task has completed.

    Args:
        task_name: The name of the task to check (e.g., 'data_sync').

    Returns:
        A dict with the current task status. If the task completed,
        includes 'duration_seconds' and 'message'.

    Example return value:
        {
            'status': 'completed',
            'task_name': 'data_sync',
            'duration_seconds': 5,
            'message': "Task 'data_sync' finished successfully after 5s."
        }
    """
    task_info = _task_registry.get(task_name)

    if task_info is None:
        return {
            "status": "not_found",
            "task_name": task_name,
            "message": f"No task named '{task_name}' has been submitted.",
        }

    # Sync state with session
    tool_context.state["task_status"] = task_info["status"]
    if task_info["status"] == "completed":
        tool_context.state["task_result"] = task_info.get("message", "")

    return task_info


async def check_pending_tasks_callback(callback_context: CallbackContext) -> None:
    """Before-agent callback: notify if a background task completed.

    Runs before each agent turn. If a previously submitted task has
    finished, updates session state so the agent's instruction can
    reference {task_completed_notification} to inform the user.

    Args:
        callback_context: The ADK CallbackContext with session state access.
            Must be named 'callback_context' — ADK passes it as a keyword arg.
    """
    state = callback_context.state
    task_name = state.get("task_name")
    previous_status = state.get("task_status")

    if not task_name or previous_status == "completed":
        # No pending task, or already notified
        state["task_completed_notification"] = ""
        return

    task_info = _task_registry.get(task_name)
    if task_info and task_info["status"] == "completed":
        # Task just completed — inject notification into state
        state["task_status"] = "completed"
        state["task_result"] = task_info.get("message", "")
        state["task_completed_notification"] = (
            f"IMPORTANT: Background task '{task_name}' has just completed! "
            f"Result: {task_info.get('message', '')} "
            f"Please inform the user about this."
        )
        logger.info("Injected completion notification for task '%s'", task_name)
    else:
        state["task_completed_notification"] = ""
