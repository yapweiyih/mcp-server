# Makefile for ER MCP Review project
#
# Usage:
#   make install       - Install all dependencies
#   make test          - Run unit tests only
#   make test-integration - Run integration tests (requires GCP credentials)
#   make test-agent    - Run ADK agent tests (requires GCP + Vertex AI)
#   make test-all      - Run all tests
#   make mcp-local     - Start MCP server locally (stdio mode)
#   make mcp-sse       - Start MCP server in SSE mode (for Cloud Run testing)
#   make agent-web     - Start ADK agent web UI
#   make agent-run     - Start ADK agent CLI
#   make chat          - Start ADK agent CLI (alias for agent-run)
#   make deploy        - Deploy MCP server to Cloud Run
#   make lint          - Run linting checks
#   make clean         - Clean build artifacts

.PHONY: install test test-integration test-agent test-a2a test-all \
        mcp-local mcp-sse agent-web agent-run chat \
        agui-server agui-frontend agui-dev \
        a2a-server deploy-agent-engine deploy-agent-engine-local \
        test-a2a-remote test-a2a-client \
        deploy docker-build docker-push deploy-run lint clean

# Configuration
PROJECT_ID ?= ikigai-dev-376122
REGION ?= us-central1
SERVICE_NAME ?= er-mcp-server
IMAGE_NAME ?= gcr.io/$(PROJECT_ID)/$(SERVICE_NAME)

# ============================================================
# Setup
# ============================================================

install:
	@echo "📦 Installing dependencies..."
	uv sync --extra dev

# ============================================================
# Testing
# ============================================================

test:
	@echo "🧪 Running unit tests..."
	uv run pytest tests/test_er_query.py tests/test_mcp_server.py tests/test_long_running_tool.py -v

test-integration:
	@echo "🔗 Running integration tests (requires GCP credentials)..."
	uv run pytest tests/test_integration.py -v -s

test-agent:
	@echo "🤖 Running ADK agent tests (requires GCP + Vertex AI)..."
	uv run pytest tests/test_adk_agent.py -v -s

test-all:
	@echo "🧪 Running all tests..."
	uv run pytest -v -s

# ============================================================
# MCP Server
# ============================================================

mcp-local:
	@echo "🔌 Starting MCP server (stdio mode)..."
	@echo "Send JSON-RPC messages via stdin. Press Ctrl+C to stop."
	uv run python -m mcp_server

mcp-sse:
	@echo "🌐 Starting MCP server (SSE mode on port 8080)..."
	MCP_TRANSPORT=sse PORT=8080 uv run python -m mcp_server

mcp-test-tools:
	@echo "🔍 Testing MCP tools/list..."
	@echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}\n{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
		| uv run python -m mcp_server 2>/dev/null \
		| python3 -c "import sys,json; [print(json.dumps(json.loads(l),indent=2)) for l in sys.stdin]"

# ============================================================
# ADK Agent
# ============================================================

agent-web:
	@echo "🌐 Starting ADK agent web UI..."
	uv run adk web adk_agent

agent-run chat:
	@echo "🤖 Starting ADK agent CLI chat..."
	@echo "Type your questions about Expert Requests. Press Ctrl+C to exit."
	uv run adk run adk_agent

# ============================================================
# AG-UI + CopilotKit
# ============================================================

agui-server:
	@echo "🤖 Starting AG-UI server (ADK agent on port 8000)..."
	uv run python agui_server.py

agui-frontend:
	@echo "🌐 Starting CopilotKit frontend (Next.js on port 3000)..."
	cd frontend && npm run dev

agui-install:
	@echo "📦 Installing AG-UI frontend dependencies..."
	cd frontend && npm install

agui-dev:
	@echo "🚀 Starting both AG-UI server and frontend..."
	@echo "   Backend:  http://localhost:8000/agui"
	@echo "   Frontend: http://localhost:3000"
	@echo ""
	@echo "Run in two terminals:"
	@echo "  Terminal 1: make agui-server"
	@echo "  Terminal 2: make agui-frontend"

# ============================================================
# A2A (Agent-to-Agent)
#
# Workflow:
#   Step 1: make test-a2a                    — Run unit tests (no GCP needed)
#   Step 2: make deploy-agent-engine-local   — Test A2A agent locally
#   Step 3: make deploy-agent-engine         — Deploy to Agent Engine (returns RESOURCE_ID)
#   Step 4: make test-a2a-remote RESOURCE_ID=<id>  — Call the deployed endpoint
#   Step 5: make test-a2a-client RESOURCE_ID=<id>  — ADK agent calls remote A2A agent
#
# Local dev (no deployment):
#   Terminal 1: make a2a-server              — Start local A2A server
#   Terminal 2: make test-a2a-client-local   — ADK agent calls local A2A server
# ============================================================

a2a-server:
	@echo "🤝 Starting A2A server (ADK agent on port 8001)..."
	uv run python -m a2a_app.server

test-a2a:
	@echo "🧪 Running A2A unit tests..."
	uv run pytest tests/test_a2a_unit.py -v

deploy-agent-engine:
	@echo "🚀 Deploying to Vertex AI Agent Engine (A2A)..."
	uv run python -m a2a_app.deploy

deploy-agent-engine-local:
	@echo "🧪 Testing A2A agent locally before deployment..."
	uv run python -m a2a_app.deploy --test-local

test-a2a-remote:
	@echo "🧪 Testing deployed A2A agent on Agent Engine..."
	@echo "  Usage: make test-a2a-remote RESOURCE_ID=<id>"
	uv run python -m a2a_app.test_remote --resource-id $(RESOURCE_ID)

test-a2a-client:
	@echo "🤖 Testing ADK agent calling remote A2A agent..."
	@echo "  Usage: make test-a2a-client RESOURCE_ID=<id>"
	@echo "     or: make test-a2a-client-local"
	uv run python -m a2a_app.test_client_agent --resource-id $(RESOURCE_ID)

test-a2a-client-local:
	@echo "🤖 Testing ADK agent calling local A2A agent..."
	@echo "  Make sure 'make a2a-server' is running in another terminal."
	uv run python -m a2a_app.test_client_agent --local

# ============================================================
# Deployment (Cloud Run - MCP Server)
# ============================================================

deploy: docker-build deploy-run

docker-build:
	@echo "🐳 Building Docker image via Cloud Build..."
	gcloud builds submit --tag $(IMAGE_NAME) \
		--project $(PROJECT_ID) \
		--region $(REGION)

deploy-run:
	@echo "🚀 Deploying to Cloud Run..."
	@echo "  Project: $(PROJECT_ID)"
	@echo "  Region:  $(REGION)"
	@echo "  Service: $(SERVICE_NAME)"
	@echo "  Image:   $(IMAGE_NAME)"
	gcloud run deploy $(SERVICE_NAME) \
		--project $(PROJECT_ID) \
		--region $(REGION) \
		--image $(IMAGE_NAME) \
		--set-env-vars="MCP_TRANSPORT=sse" \
		--port 8080 \
		--memory 512Mi \
		--timeout 300

test-cloud:
	@echo "☁️  Testing Cloud Run MCP server..."
	@echo "  URL: https://er-mcp-server-462396196470.$(REGION).run.app"
	uv run python tests/test_cloud_mcp.py

# ============================================================
# Utilities
# ============================================================

lint:
	@echo "🔍 Running lint checks..."
	uv run python -m py_compile er_query/client.py
	uv run python -m py_compile er_query/models.py
	uv run python -m py_compile mcp_server/server.py
	uv run python -m py_compile adk_agent/agent.py
	uv run python -m py_compile adk_agent/tools.py
	uv run python -m py_compile a2a_app/server.py
	uv run python -m py_compile a2a_app/deploy.py
	uv run python -m py_compile a2a_app/test_remote.py
	uv run python -m py_compile a2a_app/test_client_agent.py
	@echo "✅ All files compile successfully"

clean:
	@echo "🧹 Cleaning build artifacts..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache
	@echo "✅ Clean complete"
