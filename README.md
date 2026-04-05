# ER MCP Review

Expert Request (ER) query system built with Firestore, MCP (Model Context Protocol), and ADK (Agent Development Kit).

## Architecture

```
User Query → ADK Agent (Gemini 2.0) → MCP Server (SSE) → Firestore
                                         ↑
                                    Cloud Run
```

## Project Structure

```
├── er_query/              # Firestore query functions
│   ├── client.py          # query_er_by_email, query_er_by_date, query_er_by_name
│   └── models.py          # ERRecord Pydantic model (schema reference)
├── mcp_server/            # MCP server (FastMCP)
│   ├── server.py          # MCP tools: search_er_by_email, search_er_by_date, get_er_fields
│   └── __main__.py        # Entry point: python -m mcp_server
├── adk_agent/             # ADK agent (Gemini 2.0 Flash)
│   ├── agent.py           # root_agent with MCP toolset (stdio/SSE)
│   └── .env               # Vertex AI config
├── tests/
│   ├── test_er_query.py   # Unit tests (mocked Firestore)
│   ├── test_mcp_server.py # Unit tests (mocked queries)
│   ├── test_integration.py# Integration tests (real Firestore)
│   ├── test_adk_agent.py  # Agent tests (local MCP + Vertex AI)
│   └── test_cloud_mcp.py  # Cloud tests (Cloud Run MCP + ADK agent)
├── skills/
│   └── er-query/SKILL.md  # Agent skill definition
├── Dockerfile             # Cloud Run container
├── Makefile               # All commands
├── adk_agent/.env          # All env config (GCP + Firestore)
└── pyproject.toml         # Dependencies
```

## Quick Start

```bash
# Install dependencies
make install

# Run unit tests (no GCP needed)
make test

# Run integration tests (requires GCP credentials)
make test-integration

# Run ADK agent tests (requires GCP + Vertex AI)
make test-agent

# Test deployed Cloud Run MCP server + ADK agent via SSE
make test-cloud

# Run all tests
make test-all
```

## MCP Server

```bash
# Run MCP server locally (stdio mode)
make mcp-local

# Run MCP server in SSE mode (port 8080)
make mcp-sse

# Test MCP tools listing
make mcp-test-tools
```

## ADK Agent

```bash
# Launch ADK web UI
make agent-web

# Launch ADK CLI chat
make agent-run
```

## Deployment

```bash
# Build Docker image via Cloud Build + deploy to Cloud Run
make deploy

# Or run each step separately:
make docker-build   # Build and push image to GCR
make deploy-run     # Deploy GCR image to Cloud Run

# Test the deployed server
make test-cloud
```

**Deployed URL**: `https://er-mcp-server-462396196470.us-central1.run.app`

## Tasks

### (1) Firestore Query Functions ✅
- Created `er_query/client.py` with Firestore client functions
- Sample data schema in `er_431059.json`, database config in `adk_agent/.env`
- Function params designed for easy MCP tool extension (flat types, dependency injection)
- Supported queries:
  - `query_er_by_email(assigned_ce_email)` — retrieve ERs by assigned CE email
  - `query_er_by_date(year, month=None)` — retrieve ERs by created_at date (year or year/month)
  - `query_er_by_name(er_name, fields=None)` — retrieve specific fields from an ER by name
- Returns only required fields: `er_name`, `account_name`, `account_sub_region`, `assigned_ce_email`, `details`

### (2) MCP Server + Cloud Run Deployment ✅
- `mcp_server/server.py` using FastMCP with `search_er_by_email`, `search_er_by_date`, and `get_er_fields` tools
- Local testing via stdio mode (`make mcp-local`)
- SSE mode for Cloud Run (`make mcp-sse`)
- Deployed to Cloud Run via container build (`make deploy`)

### (3) ADK Agent ✅
- `adk_agent/agent.py` with Gemini 2.0 Flash model
- Connects to MCP server via stdio (local) or SSE (Cloud Run)
- Tested with multiple prompts:
  - Email queries (known/unknown emails)
  - Date queries (year only, year+month)
  - Edge cases (ambiguous queries, greetings)
  - ADK agent via Cloud Run MCP server (SSE)

### (4) Makefile ✅
- `make test` — unit tests
- `make test-integration` — Firestore integration tests
- `make test-agent` — ADK agent tests (local MCP)
- `make test-cloud` — Cloud Run MCP server + ADK agent via SSE
- `make deploy` — build + deploy to Cloud Run
- `make agent-web` / `make agent-run` — launch agent UI/CLI

### (5) Git Commits ✅
- Code committed at every logical point with clear messages
- 10 commits tracking development progression
