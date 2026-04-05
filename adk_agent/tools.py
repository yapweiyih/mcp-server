"""Custom tools for the ER Query ADK agent.

This module contains tool functions that are registered directly with the
agent (not via MCP). Implements a non-blocking long-running task pattern
using ADK's session_service.append_event() with system events.

Non-blocking pattern:
    1. ``submit_long_task`` — starts a background asyncio.Task, returns
       immediately with status="submitted". The agent can respond to the
       user right away.
    2. The background task runs independently. On completion it writes
       a system Event (with state_delta) to the session via
       ``session_service.append_event()``. This persists the result
       directly into session state — no in-memory side-channel needed.
    3. ``check_task_status`` — reads task status from session state.
    4. A ``before_agent_callback`` manages one-shot notification delivery
       so the agent informs the user exactly once.

Why append_event over an in-memory registry?
    - Single source of truth: session state is the only place task status lives.
    - Survives restarts: persisted to the session service backend.
    - Works across workers: any process can read the updated session.
    - ADK-native: uses the same mechanism ADK itself uses for state changes.
    See temp/long_running_task_approach.md for a detailed comparison.
"""

import asyncio
import logging
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.sessions.base_session_service import BaseSessionService
from google.adk.sessions.session import Session
from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)


async def _background_work(
    task_name: str,
    duration: int,
    session_service: BaseSessionService,
    session: Session,
) -> None:
    """Run a long-running background job and persist the result via append_event.

    Instead of updating an in-memory dict, this function writes a system
    Event with state_delta directly to the session service. The next time
    the runner loads the session, the updated state (including the
    completion notification) is automatically available.

    Args:
        task_name: The name of the task to run.
        duration: How long to sleep in seconds (simulates actual work).
        session_service: The ADK session service for persisting state.
        session: The session to append the completion event to.
    """
    logger.info("Background task '%s' started (duration=%ds)", task_name, duration)

    try:
        await asyncio.sleep(duration)

        result_message = f"Task '{task_name}' finished successfully after {duration}s."

        # Write completion directly to session state via a system event.
        # This is the key difference from the in-memory registry approach:
        # the state update is persisted through the session service backend
        # (InMemory, Firestore, Vertex AI, etc.) and survives process restarts.
        completion_event = Event(
            invocation_id=f"bg_{task_name}",
            author="system",
            actions=EventActions(
                state_delta={
                    "task_status": "completed",
                    "task_result": result_message,
                    "task_completed_notification": (
                        f"IMPORTANT: Background task '{task_name}' has just completed! "
                        f"Result: {result_message} "
                        f"Please inform the user about this."
                    ),
                }
            ),
        )
        await session_service.append_event(session, completion_event)
        logger.info(
            "Background task '%s' completed — event appended to session", task_name
        )

    except Exception:
        logger.exception("Background task '%s' failed", task_name)

        # Persist the failure state so the agent can inform the user
        error_event = Event(
            invocation_id=f"bg_{task_name}",
            author="system",
            actions=EventActions(
                state_delta={
                    "task_status": "failed",
                    "task_result": f"Task '{task_name}' failed unexpectedly.",
                    "task_completed_notification": (
                        f"IMPORTANT: Background task '{task_name}' has FAILED. "
                        f"Please inform the user."
                    ),
                }
            ),
        )
        await session_service.append_event(session, error_event)


def submit_long_task(task_name: str, duration: int, tool_context: ToolContext) -> dict:
    """Submit a dummy long-running task that runs in the background.

    This tool returns immediately with status 'submitted'. The actual work
    runs asynchronously in the background for the specified duration.
    On completion, the background worker writes a system event to the
    session, so the agent is automatically notified on the next turn.

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
    # Update session state to track the pending task
    tool_context.state["task_name"] = task_name
    tool_context.state["task_status"] = "in_progress"

    # Capture session service and session references for the background worker.
    # Note: _invocation_context is a private attribute. ADK doesn't expose
    # session_service publicly on ToolContext. This is a pragmatic choice
    # for the append_event pattern. See temp/long_running_task_approach.md.
    invocation_ctx = tool_context._invocation_context
    session_service = invocation_ctx.session_service
    session = invocation_ctx.session

    # Fire-and-forget: schedule the background work
    loop = asyncio.get_event_loop()
    loop.create_task(_background_work(task_name, duration, session_service, session))

    return {
        "status": "submitted",
        "task_name": task_name,
        "duration": duration,
        "message": f"Task '{task_name}' submitted. It will complete in ~{duration} seconds.",
    }


def check_task_status(task_name: str, tool_context: ToolContext) -> dict:
    """Check the current status of a previously submitted background task.

    Reads task status directly from session state (the single source of
    truth). If the background worker has completed and written its system
    event via append_event, the session state will reflect 'completed'.

    Note: Within the *same* invocation where the task was submitted, this
    may still show 'in_progress' even if the background work finished,
    because the invocation uses a cached session copy. The next turn will
    show the correct status.

    Args:
        task_name: The name of the task to check (e.g., 'data_sync').

    Returns:
        A dict with the current task status.

    Example return value:
        {
            'status': 'completed',
            'task_name': 'data_sync',
            'message': "Task 'data_sync' finished successfully after 5s."
        }
    """
    stored_name = tool_context.state.get("task_name")

    if stored_name != task_name:
        return {
            "status": "not_found",
            "task_name": task_name,
            "message": f"No task named '{task_name}' has been submitted.",
        }

    status = tool_context.state.get("task_status", "unknown")
    result: dict[str, Any] = {
        "status": status,
        "task_name": task_name,
    }

    if status in ("completed", "failed"):
        result["message"] = tool_context.state.get("task_result", "")

    return result


async def check_pending_tasks_callback(callback_context: CallbackContext) -> None:
    """Before-agent callback: manage one-shot notification delivery.

    Runs before each agent turn. The background worker writes the
    notification directly to session state via append_event. This callback
    just manages the lifecycle — ensuring the notification is shown exactly
    once and cleared on the subsequent turn.

    Flow:
        Turn N-1: Background worker calls append_event → sets
                  task_completed_notification in session state.
        Turn N:   This callback sees the notification, marks it as
                  'delivered'. Agent instruction picks it up via
                  {task_completed_notification}.
        Turn N+1: This callback sees 'delivered' flag, clears the
                  notification so the agent doesn't repeat itself.

    Args:
        callback_context: The ADK CallbackContext with session state access.
            Must be named 'callback_context' — ADK passes it as a keyword arg.
    """
    state = callback_context.state

    # Turn N+1: notification was delivered last turn → clear it
    if state.get("_task_notification_delivered"):
        state["task_completed_notification"] = ""
        state["_task_notification_delivered"] = False
        logger.info("Cleared delivered task notification")
        return

    # Turn N: notification exists (set by background worker via append_event)
    notification = state.get("task_completed_notification", "")
    if notification:
        # Mark for cleanup on the next turn
        state["_task_notification_delivered"] = True
        logger.info("Task notification ready for delivery: %s", notification[:80])
    else:
        # No pending task or notification
        state["task_completed_notification"] = ""
