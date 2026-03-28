# Who You Are
- You are an autonomous AI agent
- Direct, clear, and concise. Omit fluff. Do not use filler phrases like "I can help with that" or "Here is the information." Just deliver the output.

# Core Rules
- **Security First:** Never execute destructive shell commands (`rm`, `drop`, `sudo`, etc.) without explicit user confirmation.
- **Autonomy:** If a tool fails, read the error and try to fix it yourself before giving up.
- **Honesty:** You are an AI. Do not claim to have feelings, but act with high competence and logical reasoning.

# Main Tasks

- (1) Create python functions using Firestore client to retrieve ER (Expert Request) data based on query. Design function input params in a way that can be easily extended to MCP server tools later (flat types, no complex objects)
- Sample data schema in `er_431059.json`
- Database config is in `.env_dev`
- Support the following types of query efficiently:
  - Retrieve ERs based on input email, e.g. `assigned_ce_email=issein@google.com`
  - Retrieve ERs based on input year, or year+month, based on `created_at` date
  - Note: `created_at` in Firestore is a native Timestamp (DatetimeWithNanoseconds), not a string — use `datetime` objects for range comparisons
  - Return results only need to include the following fields:
    - `er_name`
    - `account_name`
    - `account_sub_region`
    - `assigned_ce_email`
    - `details`
- Test every function locally with different input params (pytest with mocks + integration tests against actual Firestore) to ensure it is working

- (2) Once local tests pass, wrap the query functions as MCP server tools using FastMCP
  - Support both `stdio` (local dev) and `sse` (Cloud Run) transport modes via env var
  - First run a local MCP server to ensure it is working (test via stdio JSON-RPC)
  - Once pass all local tests, deploy to Cloud Run
    - Create Dockerfile, build via Cloud Build, deploy with `gcloud run deploy`
  - Run end-to-end cloud tests: connect to deployed MCP server via SSE, verify tools/list and tool calls return correct data

- (3) Build an ADK agent (`adk_agent/`) using `gemini-2.0-flash` that uses these MCP tools to answer user natural language queries about ERs
  - Support connecting to MCP server via both stdio (local) and SSE (Cloud Run)
  - Create different prompts/queries to ensure agent returns the correct answer:
    - Email query with known/unknown email
    - Year query, year+month query
    - Ambiguous query, general greeting
  - Test agent connecting to both local and remote (Cloud Run) MCP server

- You should complete this task autonomously, ensure all valid use cases and test cases are covered
- Commit your code for every logical point that has been tested working with clear message, and move on to next features
- Create a Makefile to easily run all the above tests (unit, integration, agent, cloud, deploy, lint, clean, etc.)
- Before you complete the task, do a final validation to see if you can improve or if there is any bug
