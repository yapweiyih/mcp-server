# Long-Running Task Completion: `append_event` vs In-Memory Registry

## The Problem

When an agent kicks off a background task (e.g., data sync, report generation), it needs
a mechanism to:
1. Return immediately to the user ("task submitted")
2. Track completion asynchronously
3. Notify the user on the next turn that the task finished

## Current Approach: In-Memory Registry + Polling Callback

```
submit_long_task()
  ├─ writes to _task_registry (in-memory dict)
  ├─ writes to tool_context.state (session state)
  └─ spawns asyncio.Task → _background_work()
                              └─ updates _task_registry on completion

check_pending_tasks_callback()  ← runs before each agent turn
  ├─ reads from _task_registry
  └─ if completed: writes notification into session state
```

### Problems with this approach

| Problem | Impact |
|---------|--------|
| **In-memory registry doesn't survive restarts** | If the process crashes after the task completes but before the user's next turn, the completion data is lost. |
| **Doesn't work across multiple workers/pods** | Worker A submits the task. Worker B handles the next request. Worker B's `_task_registry` is empty — notification is lost. |
| **Dual source of truth** | State lives in both `_task_registry` and session state. They can drift apart if either write fails. |
| **Callback only fires on user message** | The user must send another message to trigger the `before_agent_callback`. No way to push notifications. |

## Improved Approach: `session_service.append_event()` with System Events

```
submit_long_task()
  ├─ writes to tool_context.state (session state: in_progress)
  ├─ captures session_service + session references
  └─ spawns asyncio.Task → _background_work()
                              └─ on completion: session_service.append_event(
                                     session, Event(
                                         author="system",
                                         actions=EventActions(state_delta={
                                             "task_status": "completed",
                                             "task_result": "...",
                                             "task_completed_notification": "..."
                                         })
                                     )
                                 )

check_pending_tasks_callback()  ← simpler, just manages notification lifecycle
  ├─ reads task_completed_notification from session state (already set by append_event)
  └─ clears it after delivery so it only shows once
```

### Why this is better

| Improvement | Explanation |
|-------------|-------------|
| **Single source of truth** | Session state (managed by `session_service`) is the only place where task status lives. No in-memory side-channel. |
| **Survives restarts** | `append_event` persists the completion to the session service backend (Firestore, Vertex AI, etc.). Even if the process dies, the next turn loads the updated state. |
| **Works across workers** | Any worker can read the updated session state — it's in the session service, not in local memory. |
| **ADK-native pattern** | Uses the same mechanism ADK itself uses to track state changes (events with `state_delta`). Consistent with how the framework was designed. |
| **Simpler callback** | The callback no longer needs to bridge between a registry and session state. It just manages one-shot notification delivery. |

### How `append_event` updates session state

When `session_service.append_event(session, event)` is called with an event that has
`actions.state_delta`, the session service:

1. Appends the event to the session's event history
2. Merges `state_delta` into the stored session state
3. On the next `get_session()` call (triggered by `runner.run_async()`), the
   updated state is returned

```python
# From InMemorySessionService.append_event():
if event.actions and event.actions.state_delta:
    state_deltas = _session_util.extract_state_delta(event.actions.state_delta)
    if session_state_delta:
        storage_session.state.update(session_state_delta)
```

### Trade-offs

| Trade-off | Details |
|-----------|---------|
| **Within-invocation visibility** | If the user calls `check_task_status` in the _same_ invocation where the task was submitted, they may see "in_progress" even if the task finished (because the invocation uses a cached session copy). The user needs to send a new message to see the update. This is acceptable — the `before_agent_callback` handles proactive notification on the next turn. |
| **Private API usage** | Accessing `tool_context._invocation_context.session_service` uses a private attribute. This is a pragmatic choice — ADK doesn't expose `session_service` publicly on `ToolContext`. Document this as a known coupling point. |
| **Stale session handling** | The session captured at submit time becomes stale because the agent's response events update `last_update_time`. Persistent backends like `SqliteSessionService` reject `append_event` on stale sessions. The fix: pass session **identifiers** (not the object) to the background worker, and call `get_session()` to fetch a fresh copy before `append_event`. |

### When to use which approach

| Scenario | Recommended approach |
|----------|---------------------|
| Local dev / single process | Either works, but `append_event` is still cleaner |
| Multi-worker production deployment | **Must** use `append_event` — in-memory registry fails |
| Persistent session service (Firestore, Vertex AI) | **Must** use `append_event` — data must survive restarts |
| Need real-time polling within same turn | Keep a lightweight in-memory tracker alongside `append_event` |
