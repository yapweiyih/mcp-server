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
#   make mcp-http       — MCP server (Streamable HTTP, port 8080)
#   make agent-web      — ADK agent web UI
#   make agent-chat     — ADK agent CLI
#   make agui-server    — AG-UI backend (port 8000)
#   make agui-frontend  — CopilotKit frontend (port 3000)
#
# Deploy:
#   make deploy-mcp-server-cloudrun — Build + deploy MCP to Cloud Run
#   make deploy-adk-agent-engine    — Deploy ADK agent to Agent Engine
#   make deploy-a2a-agent-engine    — Deploy A2A agent to Agent Engine
#   make deploy-adk-gemini-enterprise — Register ADK agent to Gemini Enterprise
#   make deploy-a2a-gemini-enterprise — Register A2A agent to Gemini Enterprise
#   make list-gemini-enterprise       — List all registered agents
#   make test-gemini-enterprise       — Test ADK agent on Gemini Enterprise
#
# A2A local dev:
#   make test-a2a-local — Start server, run client test, stop server (single command)
#   Or manually: Terminal 1: make a2a-server / Terminal 2: make test-a2a-client-local

.PHONY: install test test-all lint format clean \
        mcp-http mcp-sse test-mcp \
        agent-web agent-chat \
        agui-server agui-frontend agui-install \
        a2a-server test-a2a test-a2a-client-local test-a2a-local \
        deploy-mcp-server-cloudrun deploy-adk-agent-engine deploy-a2a-agent-engine \
        deploy-adk-gemini-enterprise deploy-adk-gemini-enterprise-auth \
        deploy-a2a-gemini-enterprise deploy-a2a-gemini-enterprise-auth \
        list-gemini-enterprise get-a2a-agent-card-from-ae \
        delete-gemini-enterprise delete-a2a-gemini-enterprise test-gemini-enterprise \
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

# Start local MCP Server, the test MCP decatored function.
test-mcp:
	uv run python tests/test_mcp_http.py

test-a2a:
	uv run pytest tests/test_a2a_unit.py -v

# Test MCP Server on cloud
test-cloud:
	uv run python tests/test_cloud_mcp.py

# ---------- Run ----------

mcp-http:
	MCP_TRANSPORT=streamable-http PORT=8080 uv run python -m mcp_server

mcp-sse:
	MCP_TRANSPORT=sse PORT=8080 uv run python -m mcp_server

agent-web:
	uv run adk web .

agent-chat:
	uv run adk run adk_agent


# ---------- AGUI ----------

agui-server:
	uv run python agui_server.py

agui-frontend:
	cd frontend && npm run dev

agui-install:
	cd frontend && npm install

# ---------- A2A ----------

a2a-server:
	MCP_SERVER_URL= uv run python -m a2a_app.server

test-a2a-client-local:
	uv run python -m a2a_app.test_client_agent --local

test-a2a-local:
	@echo "Starting A2A server in background..."
	@MCP_SERVER_URL= uv run python -m a2a_app.server & A2A_PID=$$!; \
	sleep 3; \
	echo "Running A2A client test..."; \
	uv run python -m a2a_app.test_client_agent --local; \
	EXIT_CODE=$$?; \
	echo "Stopping A2A server (PID $$A2A_PID)..."; \
	kill $$A2A_PID 2>/dev/null; \
	exit $$EXIT_CODE

test-a2a-remote:
	uv run python -m a2a_app.test_remote $(if $(RESOURCE_ID),--resource-id $(RESOURCE_ID))

test-a2a-client-remote:
	uv run python -m a2a_app.test_client_agent $(if $(RESOURCE_ID),--resource-id $(RESOURCE_ID))

# ---------- Deploy ----------

deploy-mcp-server-cloudrun:
	gcloud builds submit --tag $(IMAGE_NAME) --project $(PROJECT_ID) --region $(REGION)
	gcloud run deploy $(SERVICE_NAME) \
		--project $(PROJECT_ID) \
		--region $(REGION) \
		--image $(IMAGE_NAME) \
		--set-env-vars="MCP_TRANSPORT=streamable-http,GOOGLE_CLOUD_PROJECT=$(PROJECT_ID),DATABASE_ID=$(DATABASE_ID),COLLECTION=$(COLLECTION)" \
		--port 8080 \
		--memory 512Mi \
		--timeout 300

deploy-adk-agent-engine:
	uv run python ae_deploy.py

deploy-a2a-agent-engine:
	uv run python -m a2a_app.deploy

deploy-adk-gemini-enterprise:
	bash ge_register.sh register

deploy-adk-gemini-enterprise-auth:
	bash ge_register.sh register-auth

deploy-a2a-gemini-enterprise:
	bash a2a_ge_register.sh register

deploy-a2a-gemini-enterprise-auth:
	bash a2a_ge_register.sh register-auth

list-gemini-enterprise:
	bash ge_register.sh list

get-a2a-agent-card-from-ae:
	uv run python ae_get_agent_card.py

delete-gemini-enterprise:
	@if [ -z "$(ID)" ]; then echo "Usage: make delete-gemini-enterprise ID=<AGENT_ID>"; exit 1; fi
	bash ge_register.sh delete $(ID)

delete-a2a-gemini-enterprise:
	@if [ -z "$(ID)" ]; then echo "Usage: make delete-a2a-gemini-enterprise ID=<AGENT_ID>"; exit 1; fi
	bash a2a_ge_register.sh delete $(ID)

test-gemini-enterprise:
	uv run python ge_stream_assist_sharepoint.py

# ---------- Utilities ----------

lint:
	uv run python -c "import py_compile, glob; [py_compile.compile(f, doraise=True) for f in glob.glob('**/*.py', recursive=True) if '.venv' not in f]"

clean:
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name '*.egg-info' -o -name .adk \) -exec rm -rf {} + 2>/dev/null; true
