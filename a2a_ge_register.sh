#!/usr/bin/env bash
# Register and manage an A2A agent in Gemini Enterprise.
#
# This script registers a custom A2A agent (deployed on Agent Engine)
# with Gemini Enterprise using the Discovery Engine REST API.
#
# Unlike ge_register.sh (which uses adk_agent_definition with
# provisioned_reasoning_engine), this uses a2aAgentDefinition with
# jsonAgentCard — the standard A2A registration path.
#
# Ref: https://docs.cloud.google.com/gemini/enterprise/docs/register-and-manage-an-a2a-agent
#
# Usage:
#   bash ge_a2a_register.sh register
#   bash ge_a2a_register.sh register-auth
#   bash ge_a2a_register.sh list
#   bash ge_a2a_register.sh list <name>
#   bash ge_a2a_register.sh get <AGENT_ID>
#   bash ge_a2a_register.sh update <AGENT_ID>
#   bash ge_a2a_register.sh update-auth <AGENT_ID>
#   bash ge_a2a_register.sh delete <AGENT_ID>
#
# Authorization resource management (create-auth, delete-auth) is shared
# across agent types — use ge_register.sh for those commands.

set -euo pipefail

# ─── Load environment ────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "${SCRIPT_DIR}/adk_agent/.env" ]; then
  source "${SCRIPT_DIR}/adk_agent/.env"
  echo "✅ Loaded environment from adk_agent/.env"
else
  echo "❌ Error: adk_agent/.env not found in ${SCRIPT_DIR}"
  exit 1
fi

# ─── Validate required variables ─────────────────────────────────────
: "${GOOGLE_CLOUD_PROJECT:?Missing GOOGLE_CLOUD_PROJECT in .env}"
: "${APP_ID:?Missing APP_ID in .env}"
: "${A2A_ENGINE_ID:?Missing A2A_ENGINE_ID in .env (deploy with 'make deploy-a2a-agent-engine' first)}"

DISPLAY_NAME="${DISPLAY_NAME_A2A:-ER Query Agent (A2A)}"
DESCRIPTION="${DESCRIPTION:-An AI agent that queries Expert Request data from Firestore via A2A protocol}"
LOCATION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
ENDPOINT_LOCATION="${ENDPOINT_LOCATION:-global}"
AGENT_VERSION="${AGENT_VERSION:-1.0.0}"
PROTOCOL_VERSION="${PROTOCOL_VERSION:-0.3.0}"

# Resolve project number
PROJECT_NUMBER=$(gcloud projects describe "$GOOGLE_CLOUD_PROJECT" --format="value(projectNumber)")

# Build the A2A URL (Agent Engine A2A endpoint)
A2A_URL="https://${LOCATION}-aiplatform.googleapis.com/v1beta1/projects/${PROJECT_NUMBER}/locations/${LOCATION}/reasoningEngines/${A2A_ENGINE_ID}"

# Base API URL
BASE_URL="https://${ENDPOINT_LOCATION}-discoveryengine.googleapis.com/v1alpha/projects/${PROJECT_NUMBER}/locations/${ENDPOINT_LOCATION}/collections/default_collection/engines/${APP_ID}/assistants/default_assistant/agents"

# ─── Build Agent Card JSON ───────────────────────────────────────────
# This matches the skills defined in a2a_app/deploy.py
AGENT_CARD_JSON=$(cat <<'CARD_EOF'
{
  "protocolVersion": "PROTOCOL_VERSION_PLACEHOLDER",
  "name": "DISPLAY_NAME_PLACEHOLDER",
  "description": "DESCRIPTION_PLACEHOLDER",
  "url": "A2A_URL_PLACEHOLDER",
  "version": "AGENT_VERSION_PLACEHOLDER",
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"],
  "capabilities": {},
  "skills": [
    {
      "id": "search_expert_requests",
      "name": "Search Expert Requests",
      "description": "Search and retrieve Expert Request (ER) data from Firestore. Can search by assigned CE email, creation date, or specific ER fields.",
      "tags": ["Expert Request", "ER", "Firestore", "Search"],
      "examples": [
        "Find all ERs assigned to user@google.com",
        "How many ERs were created in 2024?",
        "Show me the FSA status of ER-431059"
      ]
    },
    {
      "id": "background_tasks",
      "name": "Background Task Management",
      "description": "Submit and monitor long-running background tasks.",
      "tags": ["Tasks", "Background", "Async"],
      "examples": [
        "Submit a background task called data_sync for 10 seconds",
        "Check the status of my task"
      ]
    }
  ]
}
CARD_EOF
)

# Replace placeholders
AGENT_CARD_JSON=$(echo "$AGENT_CARD_JSON" | \
  sed "s|PROTOCOL_VERSION_PLACEHOLDER|${PROTOCOL_VERSION}|g" | \
  sed "s|DISPLAY_NAME_PLACEHOLDER|${DISPLAY_NAME}|g" | \
  sed "s|DESCRIPTION_PLACEHOLDER|${DESCRIPTION}|g" | \
  sed "s|A2A_URL_PLACEHOLDER|${A2A_URL}|g" | \
  sed "s|AGENT_VERSION_PLACEHOLDER|${AGENT_VERSION}|g")

# Escape for JSON embedding (single-line, escaped quotes)
AGENT_CARD_ESCAPED=$(echo "$AGENT_CARD_JSON" | jq -c '.' | sed 's/"/\\"/g')

# ─── Build JSON payload ──────────────────────────────────────────────
# Builds the request body, optionally including authorizationConfig
build_payload() {
  local include_auth=${1:-false}
  local payload='{
    "name": "'"${DISPLAY_NAME}"'",
    "displayName": "'"${DISPLAY_NAME}"'",
    "description": "'"${DESCRIPTION}"'",
    "a2aAgentDefinition": {
      "jsonAgentCard": "'"${AGENT_CARD_ESCAPED}"'"
    }'

  if [ "$include_auth" = "true" ] && [ -n "${AUTH_ID:-}" ]; then
    payload="${payload}"',
    "authorizationConfig": {
      "agentAuthorization": "projects/'"${PROJECT_NUMBER}"'/locations/'"${ENDPOINT_LOCATION}"'/authorizations/'"${AUTH_ID}"'"
    }'
  fi

  payload="${payload}"'
  }'
  echo "$payload"
}

# ─── Usage ────────────────────────────────────────────────────────────
usage() {
  echo "Usage: $0 <command> [args]"
  echo ""
  echo "Agent commands:"
  echo "  register              Register the A2A agent with Gemini Enterprise"
  echo "  register-auth         Register with OAuth authorizationConfig (needs AUTH_ID)"
  echo "  list [name]           List all agents (optionally filter by name)"
  echo "  get <AGENT_ID>        Get agent details with parsed agent card JSON"
  echo "  update <AGENT_ID>     Update an existing agent's card and config"
  echo "  update-auth <AGENT_ID> Update with OAuth authorizationConfig"
  echo "  delete <AGENT_ID>     Delete an agent registration"
  echo ""
  echo "Note: For authorization resource management (create-auth, delete-auth),"
  echo "      use ge_register.sh — auth resources are shared across agent types."
  echo ""
  echo "Configuration is loaded from adk_agent/.env"
  exit 1
}

if [ $# -lt 1 ]; then
  usage
fi

# ─── Display configuration ───────────────────────────────────────────
show_config() {
  echo ""
  echo "╔═══════════════════════════════════════════════════════════╗"
  echo "║   📋 A2A Agent Registration Configuration                ║"
  echo "╠═══════════════════════════════════════════════════════════╣"
  echo "║                                                           ║"
  echo "  Project:          ${GOOGLE_CLOUD_PROJECT}"
  echo "  Project Number:   ${PROJECT_NUMBER}"
  echo "  Location:         ${LOCATION}"
  echo "  Endpoint:         ${ENDPOINT_LOCATION}"
  echo "  APP_ID:           ${APP_ID}"
  echo "  A2A_ENGINE_ID:    ${A2A_ENGINE_ID}"
  echo "  Display Name:     ${DISPLAY_NAME}"
  echo "  Description:      ${DESCRIPTION}"
  echo "  Protocol Version: ${PROTOCOL_VERSION}"
  echo "  Agent Version:    ${AGENT_VERSION}"
  echo "  A2A URL:          ${A2A_URL}"
  echo "║                                                           ║"
  echo "╚═══════════════════════════════════════════════════════════╝"
  echo ""
}

# ─── Confirm before proceeding ────────────────────────────────────────
confirm() {
  read -r -p "🔍 Proceed? [y/N]: " response
  case "$response" in
    [yY][eE][sS]|[yY]) return 0 ;;
    *) echo "❌ Cancelled."; exit 0 ;;
  esac
}

COMMAND=$1

case $COMMAND in
  register|register-auth)
    show_config
    INCLUDE_AUTH="false"
    if [ "$COMMAND" = "register-auth" ]; then
      : "${AUTH_ID:?Missing AUTH_ID in .env for register-auth}"
      INCLUDE_AUTH="true"
      echo "  Auth ID:          ${AUTH_ID}"
      echo ""
    fi
    echo "📝 Action: REGISTER new A2A agent (auth=${INCLUDE_AUTH})"
    confirm

    PAYLOAD=$(build_payload "$INCLUDE_AUTH")

    echo ""
    echo "🚀 Registering A2A agent..."
    curl -s -X POST \
      -H "Authorization: Bearer $(gcloud auth print-access-token)" \
      -H "Content-Type: application/json" \
      -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
      "${BASE_URL}" \
      -d "${PAYLOAD}" | jq .

    echo ""
    echo "✅ Registration complete. Use 'list' to see the AGENT_ID."
    ;;

  list)
    if [ $# -eq 2 ]; then
      NAME=$2
      echo "📋 Listing agents matching '${NAME}'..."
      RESPONSE=$(curl -s -X GET \
        -H "Authorization: Bearer $(gcloud auth print-access-token)" \
        -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
        "${BASE_URL}")

      if command -v jq &> /dev/null; then
        FILTERED=$(echo "$RESPONSE" | jq --arg name "$NAME" \
          '{agents: [.agents[]? | select(.displayName | ascii_downcase | contains($name | ascii_downcase))]}')
        COUNT=$(echo "$FILTERED" | jq '.agents | length')
        if [ "$COUNT" -eq 0 ]; then
          echo "No agents found matching '${NAME}'."
          echo "Available agents:"
          echo "$RESPONSE" | jq -r '.agents[]?.displayName // empty'
        else
          echo "$FILTERED" | jq .
        fi
      else
        echo "$RESPONSE"
      fi
    else
      echo "📋 Listing all agents..."
      curl -s -X GET \
        -H "Authorization: Bearer $(gcloud auth print-access-token)" \
        -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
        "${BASE_URL}" | jq '[.agents[]? | {displayName, reasoningEngine: (.adkAgentDefinition.provisionedReasoningEngine.reasoningEngine // .a2aAgentDefinition.jsonAgentCard // "N/A"), agentId: (.name | split("/") | last)}]'
    fi
    ;;

  get)
    if [ $# -ne 2 ]; then
      echo "Error: get requires AGENT_ID argument."
      usage
    fi
    AGENT_ID=$2

    echo "🔎 Fetching agent details for ${AGENT_ID}..."
    RESPONSE=$(curl -s -X GET \
      -H "Authorization: Bearer $(gcloud auth print-access-token)" \
      -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
      "${BASE_URL}/${AGENT_ID}")

    # Pretty-print the response and parse the embedded jsonAgentCard
    if command -v jq &> /dev/null; then
      echo ""
      echo "── Agent Metadata ──────────────────────────────────────────"
      echo "$RESPONSE" | jq '{name, displayName, description, createTime, state}'
      echo ""
      echo "── Agent Card (parsed JSON) ────────────────────────────────"
      echo "$RESPONSE" | jq -r '.a2aAgentDefinition.jsonAgentCard // empty' | jq .
    else
      echo "$RESPONSE"
    fi
    ;;

  update|update-auth)
    if [ $# -ne 2 ]; then
      echo "Error: ${COMMAND} requires AGENT_ID argument."
      usage
    fi
    AGENT_ID=$2

    show_config
    INCLUDE_AUTH="false"
    if [ "$COMMAND" = "update-auth" ]; then
      : "${AUTH_ID:?Missing AUTH_ID in .env for update-auth}"
      INCLUDE_AUTH="true"
      echo "  Auth ID:          ${AUTH_ID}"
      echo ""
    fi
    echo "📝 Action: UPDATE agent ${AGENT_ID} (auth=${INCLUDE_AUTH})"
    confirm

    PAYLOAD=$(build_payload "$INCLUDE_AUTH")

    echo ""
    echo "🔄 Updating A2A agent..."
    curl -s -X PATCH \
      -H "Authorization: Bearer $(gcloud auth print-access-token)" \
      -H "Content-Type: application/json" \
      -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
      "${BASE_URL}/${AGENT_ID}" \
      -d "${PAYLOAD}" | jq .

    echo ""
    echo "✅ Update complete."
    ;;

  delete)
    if [ $# -ne 2 ]; then
      echo "Error: delete requires AGENT_ID argument."
      usage
    fi
    AGENT_ID=$2

    echo ""
    echo "⚠️  Action: DELETE agent ${AGENT_ID}"
    echo "  Project: ${GOOGLE_CLOUD_PROJECT}"
    echo "  APP_ID:  ${APP_ID}"
    confirm

    echo ""
    echo "🗑️  Deleting A2A agent..."
    curl -s -X DELETE \
      -H "Authorization: Bearer $(gcloud auth print-access-token)" \
      -H "Content-Type: application/json" \
      -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
      "${BASE_URL}/${AGENT_ID}" | jq .

    echo ""
    echo "✅ Delete complete."
    ;;

  *)
    usage
    ;;
esac
