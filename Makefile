# Makefile for ER MCP Review project
#
# Core workflow:
#   make install    — Install dependencies
#   make test       — Unit tests (fast, no GCP)
#   make test-all   — All tests (needs GCP + Vertex AI)
#   make lint       — Format check + compile check
#   make format     — Auto-format with black
#   make clean      — Remove build artifacts
#
# Run locally:
#   make mcp-sse        — MCP server (SSE, port 8080)
#   make agent-web      — ADK agent web UI
#   make agent-chat     — ADK agent CLI
#   make agui-server    — AG-UI backend (port 8000)
#   make agui-frontend  — CopilotKit frontend (port 3000)
#
# Deploy:
#   make deploy-mcp-server-cloudrun — Build + deploy MCP to Cloud Run
#   make deploy-adk-agent-engine    — Deploy ADK agent to Agent Engine
#   make deploy-a2a-agent-engine    — Deploy A2A agent to Agent Engine
#
# A2A local dev:
#   Terminal 1: make a2a-server
#   Terminal 2: make test-a2a-client-local

.PHONY: install test test-all lint format clean \
        mcp-sse test-mcp \
        agent-web agent-chat \
        agui-server agui-frontend agui-install \
        a2a-server test-a2a test-a2a-client-local \
        deploy-mcp-server-cloudrun deploy-adk-agent-engine deploy-a2a-agent-engine \
        test-a2a-remote test-a2a-client-remote test-cloud

# ---------- Configuration ----------
ifneq (,$(wildcard adk_agent/.env))
  PROJECT_ID  ?= $(shell grep '^GOOGLE_CLOUD_PROJECT=' adk_agent/.env | cut -d= -f2-)
  REGION      ?= $(shell grep '^GOOGLE_CLOUD_LOCATION=' adk_agent/.env | cut -d= -f2-)
  DATABASE_ID ?= $(shell grep '^DATABASE_ID=' adk_agent/.env | cut -d= -f2-)
  COLLECTION  ?= $(shell grep '^COLLECTION=' adk_agent/.env | cut -d= -f2-)
endif
PROJECT_ID   ?= hello-world-418507
REGION       ?= us-central1
DATABASE_ID  ?= ikigai-dev
COLLECTION   ?= expert_requests_dev
SERVICE_NAME ?= er-mcp-server
IMAGE_NAME   ?= gcr.io/$(PROJECT_ID)/$(SERVICE_NAME)

# ---------- Setup ----------

install:
	uv sync --extra dev

# ---------- Test ----------

test:
	uv run pytest tests/test_er_query.py tests/test_mcp_server.py tests/test_long_running_tool.py -v

test-all:
	uv run pytest -v -s

test-mcp:
	uv run python tests/test_mcp_sse.py

test-a2a:
	uv run pytest tests/test_a2a_unit.py -v

test-cloud:
	uv run python tests/test_cloud_mcp.py

# ---------- Run ----------

mcp-sse:
	MCP_TRANSPORT=sse PORT=8080 uv run python -m mcp_server

agent-web:
	uv run adk web .

agent-chat:
	uv run adk run adk_agent

agui-server:
	uv run python agui_server.py

agui-frontend:
	cd frontend && npm run dev

agui-install:
	cd frontend && npm install

# ---------- A2A ----------

a2a-server:
	uv run python -m a2a_app.server

test-a2a-client-local:
	uv run python -m a2a_app.test_client_agent --local

test-a2a-remote:
	uv run python -m a2a_app.test_remote --resource-id $(RESOURCE_ID)

test-a2a-client-remote:
	uv run python -m a2a_app.test_client_agent --resource-id $(RESOURCE_ID)

# ---------- Deploy ----------

deploy-mcp-server-cloudrun:
	gcloud builds submit --tag $(IMAGE_NAME) --project $(PROJECT_ID) --region $(REGION)
	gcloud run deploy $(SERVICE_NAME) \
		--project $(PROJECT_ID) \
		--region $(REGION) \
		--image $(IMAGE_NAME) \
		--set-env-vars="MCP_TRANSPORT=sse,GOOGLE_CLOUD_PROJECT=$(PROJECT_ID),DATABASE_ID=$(DATABASE_ID),COLLECTION=$(COLLECTION)" \
		--port 8080 \
		--memory 512Mi \
		--timeout 300

deploy-adk-agent-engine:
	uv run python ae_deploy.py

deploy-a2a-agent-engine:
	uv run python -m a2a_app.deploy

# ---------- Utilities ----------

lint:
	uv run python -c "import py_compile, glob; [py_compile.compile(f, doraise=True) for f in glob.glob('**/*.py', recursive=True) if '.venv' not in f]"

clean:
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name '*.egg-info' \) -exec rm -rf {} + 2>/dev/null; true
