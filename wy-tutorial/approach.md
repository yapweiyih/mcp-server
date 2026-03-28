# ER MCP Review — Approach & Architecture

## Overview

This project implements a full-stack solution for querying Expert Request (ER) data from Firestore, exposed through an MCP (Model Context Protocol) server and consumed by an ADK (Agent Development Kit) agent.

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌──────────────┐
│   ADK Agent     │────▶│   MCP Server    │────▶│   Firestore  │
│ (Gemini 2.0)    │ MCP │ (FastMCP/SSE)   │     │  (ER Data)   │
│                 │◀────│                 │◀────│              │
└─────────────────┘     └─────────────────┘     └──────────────┘
     ▲                       ▲
     │                       │
  User Query            Cloud Run
  (natural language)    (deployed)
```

## Key Design Decisions

### 1. Why Firestore instead of BigQuery?

Although the README mentioned "bq client", the `.env_dev` configuration contains Firestore-specific parameters:
- `DATABASE_ID="ikigai-dev"` — a Firestore named database
- `COLLECTION="expert_requests_dev"` — a Firestore collection name

The data structure (nested JSON with arrays, embeddings) also fits Firestore's document model better than BigQuery's tabular format. Additionally, Firestore provides **millisecond read latency**, which is ideal for MCP tool responses where an agent is waiting synchronously.

### 2. Why MCP over direct function calls?

Using MCP decouples the data layer from the agent:
- **Reusability**: The same MCP server serves ADK agents, Claude, VSCode, or any MCP-compatible client
- **Independent scaling**: The MCP server can be deployed and scaled on Cloud Run independently
- **Standardization**: MCP is becoming the standard protocol for LLM tool communication
- **Testing**: Each layer can be tested independently (Firestore functions → MCP tools → Agent)

### 3. Why FastMCP?

FastMCP (from the `mcp` Python package) provides:
- Decorator-based tool registration (`@mcp.tool()`)
- Automatic JSON schema generation from type hints
- Built-in stdio and SSE transport support
- Input validation and error handling

This is the recommended approach per the MCP specification and requires minimal boilerplate.

### 4. Query Function Design for MCP Extensibility

The query functions were designed with simple, typed parameters that map directly to MCP tool parameters:

```python
def query_er_by_email(assigned_ce_email: str) -> list[dict]
def query_er_by_date(year: int, month: int | None = None) -> list[dict]
```

Key design choices:
- **Flat parameters**: No complex objects — just `str`, `int`, and `Optional[int]`
- **Dependency injection**: Optional `client` parameter for testing without mocking internals
- **Consistent return type**: Always `list[dict]` with the same 5 fields
- **Field projection**: Only return needed fields to keep MCP payloads lightweight

### 5. Date Query: Firestore Timestamp vs String

**Problem discovered during integration testing**: The `created_at` field is stored as a native Firestore Timestamp (`DatetimeWithNanoseconds`), not as an ISO 8601 string.

**Initial approach** (failed): Compare ISO string ranges
```python
# ❌ Returns 0 results because Firestore compares types
query.where("created_at", ">=", "2025-01-01T00:00:00+00:00")
```

**Fixed approach**: Compare with `datetime` objects directly
```python
# ✅ Works because Firestore Timestamps compare with datetime
start_dt = datetime(2025, 1, 1, tzinfo=timezone.utc)
query.where("created_at", ">=", start_dt)
```

**Lesson**: Always verify the actual data type in Firestore before writing queries. The JSON export may show strings, but Firestore stores native types.

## Project Structure

```
2026-mcp-review/
├── er_query/                 # Core Firestore query functions
│   ├── __init__.py
│   ├── client.py             # query_er_by_email, query_er_by_date
│   └── models.py             # ERRecord Pydantic model
├── mcp_server/               # MCP server (FastMCP)
│   ├── __init__.py
│   ├── __main__.py           # Entry point: python -m mcp_server
│   └── server.py             # MCP tool definitions
├── adk_agent/                # ADK agent (Gemini 2.0)
│   ├── __init__.py
│   ├── .env                  # Vertex AI config
│   └── agent.py              # root_agent definition
├── tests/
│   ├── test_er_query.py      # 16 unit tests (mocked Firestore)
│   ├── test_mcp_server.py    # 9 unit tests (mocked queries)
│   ├── test_integration.py   # 6 integration tests (real Firestore)
│   └── test_adk_agent.py     # 6 agent tests (real Vertex AI + Firestore)
├── Dockerfile                # Cloud Run deployment
├── Makefile                  # Test/deploy/run commands
├── pyproject.toml            # Dependencies and config
└── .env_dev                  # Firestore connection config
```

## Testing Strategy

### Layer 1: Unit Tests (no GCP needed)
- **test_er_query.py** (16 tests): Tests `_doc_to_er_record`, `query_er_by_email`, `query_er_by_date` with mocked Firestore
- **test_mcp_server.py** (9 tests): Tests MCP tool wrappers with mocked query functions

### Layer 2: Integration Tests (requires GCP credentials)
- **test_integration.py** (6 tests): Tests actual Firestore queries
- Validates email queries, date queries, empty results

### Layer 3: Agent Tests (requires GCP + Vertex AI)
- **test_adk_agent.py** (6 tests): End-to-end tests from natural language prompt to agent response
- Tests email queries, date queries, no-result handling, ambiguous queries, greetings

### Running Tests

```bash
make test              # Unit tests only (fast, no GCP)
make test-integration  # Integration tests (requires GCP)
make test-agent        # Agent tests (requires GCP + Vertex AI)
make test-all          # Everything
```

## Deployment

### Local Development
```bash
make mcp-local    # MCP server via stdio
make mcp-sse      # MCP server via SSE (port 8080)
make agent-web    # ADK web UI
make agent-run    # ADK CLI
```

### Cloud Run
```bash
make deploy       # Deploy MCP server to Cloud Run
```

The Dockerfile uses `uv` for fast dependency resolution and runs the MCP server in SSE mode. Cloud Run automatically sets the `PORT` environment variable.

## Firestore Index Requirements

The date query uses a compound range filter on `created_at`:
```python
.where("created_at", ">=", start_dt)
.where("created_at", "<", end_dt)
```

This requires a Firestore composite index on `created_at` (ascending). Firestore may auto-create this index on the first query, or you can create it manually in the Firebase Console.
