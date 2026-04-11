# Dockerfile for deploying the MCP server to Cloud Run
#
# The MCP server runs in SSE transport mode on Cloud Run, allowing
# remote MCP clients (ADK agents, etc.) to connect over HTTP.
#
# Build: docker build -t er-mcp-server .
# Run locally: docker run -p 8080:8080 -e MCP_TRANSPORT=sse er-mcp-server

FROM python:3.12-slim

WORKDIR /app

# Install only the MCP server dependencies (no google-adk needed)
RUN pip install --no-cache-dir \
    google-cloud-firestore>=2.19.0 \
    python-dotenv>=1.0.0 \
    pydantic>=2.0.0 \
    "mcp[cli]>=1.0.0"

# Copy application code
COPY er_query/ er_query/
COPY mcp_server/ mcp_server/

# Cloud Run sets PORT env var (default 8080)
ENV PORT=8080
ENV MCP_TRANSPORT=sse
ENV PYTHONPATH=/app

# Run the MCP server
CMD ["python", "-m", "mcp_server"]
