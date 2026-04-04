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

.PHONY: install test test-integration test-agent test-all \
        mcp-local mcp-sse agent-web agent-run chat \
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
	uv run adk web

agent-run chat:
	@echo "🤖 Starting ADK agent CLI chat..."
	@echo "Type your questions about Expert Requests. Press Ctrl+C to exit."
	uv run adk run adk_agent

# ============================================================
# Deployment
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
	@echo "✅ All files compile successfully"

clean:
	@echo "🧹 Cleaning build artifacts..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache
	@echo "✅ Clean complete"
