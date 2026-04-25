# ER MCP Review

Expert Request (ER) query system built with Firestore, MCP (Model Context Protocol), and ADK (Agent Development Kit). Supports multiple agent interaction patterns: MCP tools, AG-UI (CopilotKit), A2A (Agent-to-Agent), Agent Engine, and Gemini Enterprise.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Interaction Layers                           │
│                                                                     │
│  ADK Web/CLI ─────┐                                                 │
│  CopilotKit UI ───┤──→ ADK Agent (Gemini 2.5 Flash) ──→ MCP Tools  │
│  A2A Protocol ────┘           │                             │       │
│                               │                             ▼       │
│                          Long-running              MCP Server       │
│                          tool (async)         (Streamable HTTP)     │
│                                                     │               │
│                                                     ▼               │
│                                                 Firestore           │
└─────────────────────────────────────────────────────────────────────┘

Deployment targets:
  MCP Server  → Cloud Run (Streamable HTTP on port 8080)
  ADK Agent   → Vertex AI Agent Engine / Gemini Enterprise
  A2A Agent   → Vertex AI Agent Engine
```

## Project Structure

```
├── er_query/                    # Firestore query functions
│   ├── client.py                #   query_er_by_email, query_er_by_date, query_er_by_name
│   └── models.py                #   ERRecord Pydantic model
├── mcp_server/                  # MCP server (FastMCP)
│   ├── server.py                #   Tools: search_er_by_email, search_er_by_date, get_er_fields
│   └── __main__.py              #   Entry point: python -m mcp_server
├── adk_agent/                   # ADK agent (Gemini 2.5 Flash)
│   ├── agent.py                 #   Root agent with MCP toolset (stdio/HTTP/SSE)
│   ├── tools.py                 #   Long-running tool (async background tasks)
│   └── .env_example             #   Env var template (GCP project, Firestore, MCP URL)
├── a2a_app/                     # A2A (Agent-to-Agent) protocol
│   ├── server.py                #   Local A2A server wrapping ADK agent
│   ├── deploy.py                #   Deploy A2A agent to Agent Engine
│   ├── test_client_agent.py     #   Test A2A via ADK client agent
│   └── test_remote.py           #   Test remote A2A endpoint
├── frontend/                    # CopilotKit chat UI (Next.js + React)
│   ├── src/app/page.tsx         #   Chat interface for ER queries
│   └── src/app/api/copilotkit/  #   API route → AG-UI → ADK agent
├── agui_server.py               # AG-UI backend server (CopilotKit ↔ ADK bridge)
├── ae_deploy.py                 # Deploy ADK agent to Vertex AI Agent Engine
├── ge_register.sh               # Register Agent Engine ID to Gemini Enterprise
├── ge_delete_agent.sh           # Delete Gemini Enterprise agent registration
├── ge_stream_assist_sharepoint.py # Test agent on Gemini Enterprise
├── tests/
│   ├── test_er_query.py         # Unit tests — Firestore queries (mocked)
│   ├── test_mcp_server.py       # Unit tests — MCP tool wrappers (mocked)
│   ├── test_long_running_tool.py# Unit tests — async long-running tool
│   ├── test_integration.py      # Integration tests — real Firestore
│   ├── test_adk_agent.py        # Agent tests — local MCP + Vertex AI
│   ├── test_mcp_http.py         # MCP Streamable HTTP endpoint tests
│   ├── test_mcp_sse.py          # MCP SSE endpoint tests
│   ├── test_cloud_mcp.py        # Cloud Run MCP + ADK agent tests
│   ├── test_a2a_unit.py         # A2A protocol unit tests
│   └── test_agui_server.py      # AG-UI server tests
├── skills/
│   └── er-query/SKILL.md        # Agent skill definition
├── Dockerfile                   # Cloud Run container (MCP server)
├── Makefile                     # All commands
├── pyproject.toml               # Dependencies (uv)
└── er_431059.json               # Sample ER data (schema reference)
```

## Quick Start

```bash
# Install dependencies
make install

# Run unit tests (no GCP needed)
make test

# Run all tests (requires GCP + Vertex AI)
make test-all
```

## MCP Server

Three transport modes controlled by `MCP_TRANSPORT` env var:

| Mode | Use Case | Endpoint |
|------|----------|----------|
| `streamable-http` | Cloud Run / Gemini Enterprise | `/mcp` |
| `sse` | Legacy SSE transport | `/sse` |
| `stdio` | Local dev (default) | — |

```bash
# Run MCP server locally (Streamable HTTP, port 8080)
make mcp-http

# Run MCP server locally (SSE, port 8080)
make mcp-sse

# Test MCP HTTP endpoint
make test-mcp
```

## ADK Agent

Agent uses **Gemini 2.5 Flash** with MCP toolset. Connects to MCP server via stdio (local) or HTTP/SSE (remote).

```bash
# Launch ADK web UI
make agent-web

# Launch ADK CLI chat
make agent-chat
```

## AG-UI (CopilotKit Frontend)

Full chat UI powered by CopilotKit (React/Next.js) connecting to the ADK agent via AG-UI protocol.

```bash
# Install frontend dependencies (first time)
make agui-install

# Terminal 1: Start AG-UI backend server (port 8000)
make agui-server

# Terminal 2: Start CopilotKit frontend (port 3000)
make agui-frontend
```

## A2A (Agent-to-Agent)

Exposes the ADK agent via the A2A protocol for agent-to-agent communication.

```bash
# Terminal 1: Start A2A server locally
make a2a-server

# Terminal 2: Test with A2A client agent
make test-a2a-client-local

# Run A2A unit tests
make test-a2a
```

## Deployment

### MCP Server → Cloud Run

```bash
# Build Docker image via Cloud Build + deploy to Cloud Run
make deploy-mcp-server-cloudrun

# Test the deployed server
make test-cloud
```

### ADK Agent → Vertex AI Agent Engine

```bash
# Deploy ADK agent to Agent Engine
make deploy-adk-agent-engine

# Deploy A2A agent to Agent Engine
make deploy-a2a-agent-engine
```

### Agent Engine → Gemini Enterprise

```bash
# Register Agent Engine ID to Gemini Enterprise
make deploy-adk-gemini-enterprise

# Test agent on Gemini Enterprise
make test-gemini-enterprise

# Delete Gemini Enterprise registration
make delete-gemini-enterprise
```

## Environment Configuration

Copy `adk_agent/.env_example` to `adk_agent/.env` and fill in:

| Variable | Description |
|----------|-------------|
| `GOOGLE_CLOUD_PROJECT` | GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | GCP region (e.g., `us-central1`) |
| `DATABASE_ID` | Firestore database ID |
| `COLLECTION` | Firestore collection name |
| `MCP_SERVER_URL` | Remote MCP server URL (for SSE/HTTP mode) |

## MCP Tools

| Tool | Description |
|------|-------------|
| `search_er_by_email` | Find ERs assigned to a CE email |
| `search_er_by_date` | Find ERs created in a given year or year/month |
| `get_er_fields` | Get specific fields from an ER by name (e.g., ER-431059) |

## Make Targets Reference

| Target | Description |
|--------|-------------|
| `install` | Install dependencies (`uv sync --extra dev`) |
| `test` | Unit tests — fast, no GCP needed |
| `test-all` | All tests — requires GCP + Vertex AI |
| `test-mcp` | Test MCP HTTP endpoint |
| `test-a2a` | A2A unit tests |
| `test-cloud` | Test Cloud Run MCP server |
| `mcp-http` | MCP server (Streamable HTTP, port 8080) |
| `mcp-sse` | MCP server (SSE, port 8080) |
| `agent-web` | ADK agent web UI |
| `agent-chat` | ADK agent CLI |
| `agui-server` | AG-UI backend (port 8000) |
| `agui-frontend` | CopilotKit frontend (port 3000) |
| `agui-install` | Install frontend npm dependencies |
| `a2a-server` | A2A server locally |
| `test-a2a-local` | A2A end-to-end: start server, run client, stop (single command) |
| `test-a2a-client-local` | Test A2A client (requires separate `make a2a-server`) |
| `test-a2a-remote` | Test remote A2A server |
| `test-a2a-client-remote` | Test A2A client (remote) |
| `deploy-mcp-server-cloudrun` | Build + deploy MCP to Cloud Run |
| `deploy-adk-agent-engine` | Deploy ADK agent to Agent Engine |
| `deploy-a2a-agent-engine` | Deploy A2A agent to Agent Engine |
| `deploy-adk-gemini-enterprise` | Register to Gemini Enterprise |
| `delete-gemini-enterprise` | Delete Gemini Enterprise registration |
| `test-gemini-enterprise` | Test on Gemini Enterprise |
| `lint` | Syntax check all Python files |
| `clean` | Remove build artifacts |
