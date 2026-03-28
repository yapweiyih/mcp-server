# Dockerfile for deploying the MCP server to Cloud Run
#
# The MCP server runs in SSE transport mode on Cloud Run, allowing
# remote MCP clients (ADK agents, etc.) to connect over HTTP.
#
# Build: docker build -t er-mcp-server .
# Run locally: docker run -p 8080:8080 -e MCP_TRANSPORT=sse er-mcp-server

FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies (without dev extras)
RUN uv sync --no-dev --no-install-project

# Copy application code
COPY er_query/ er_query/
COPY mcp_server/ mcp_server/
COPY .env_dev .env_dev

# Install the project itself
RUN uv sync --no-dev

# Cloud Run sets PORT env var (default 8080)
ENV PORT=8080
ENV MCP_TRANSPORT=sse

# Run the MCP server
CMD ["uv", "run", "python", "-m", "mcp_server"]
