#!/usr/bin/env bash
# Register and manage an A2A agent in Gemini Enterprise.
#
# Unlike ge_register.sh (which uses adk_agent_definition with
# provisioned_reasoning_engine), this uses a2aAgentDefinition with
# jsonAgentCard — the standard A2A registration path.
#
# Ref: https://docs.cloud.google.com/gemini/enterprise/docs/register-and-manage-an-a2a-agent

# Source environment variables from .env file
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo
if [ -f "${SCRIPT_DIR}/adk_agent/.env" ]; then
  source "${SCRIPT_DIR}/adk_agent/.env"
  echo "✅ Loaded environment from adk_agent/.env"
else
  echo "Warning: .env file not found in ${SCRIPT_DIR}/adk_agent/"
fi

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║   📋 A2A Agent Configuration (a2a_ge_register.sh)         ║"
echo "╠═══════════════════════════════════════════════════════════╣"
echo "  Project:        ${GOOGLE_CLOUD_PROJECT}"
echo "  APP_ID:         ${APP_ID}"
echo "  A2A_ENGINE_ID:  ${A2A_ENGINE_ID}"
echo "  DISPLAY_NAME:   ${DISPLAY_NAME_A2A:-ER Query Agent (A2A)}"
echo "  AUTH_ID:        ${AUTH_ID}"
echo "╚═══════════════════════════════════════════════════════════╝"
echo

if [ -n "$GOOGLE_CLOUD_PROJECT" ]; then
  PROJECT_NUMBER=$(gcloud projects describe "$GOOGLE_CLOUD_PROJECT" --format="value(projectNumber)")
else
  echo "Error: GOOGLE_CLOUD_PROJECT environment variable is not set"
  exit 1
fi

DISPLAY_NAME="${DISPLAY_NAME_A2A:-ER Query Agent (A2A)}"
DESCRIPTION="${DESCRIPTION_A2A:-An AI agent that queries Expert Request data via A2A protocol}"
LOCATION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
OAUTH_CLIENT_ID=$(gcloud secrets versions access latest --secret="AGENTSPACE_WEB_CLIENTID" --project="${PROJECT_NUMBER}")
OAUTH_CLIENT_SECRET=$(gcloud secrets versions access latest --secret="AGENTSPACE_WEB_CLIENTSECRET" --project="${PROJECT_NUMBER}") # pragma: allowlist secret
OAUTH_TOKEN_URI="https://oauth2.googleapis.com/token"

# A2A agent URL (Agent Engine endpoint, must end with /a2a)
A2A_URL="https://${LOCATION}-aiplatform.googleapis.com/v1beta1/projects/${PROJECT_NUMBER}/locations/${LOCATION}/reasoningEngines/${A2A_ENGINE_ID}/a2a"

# Base API URL
BASE_URL="https://discoveryengine.googleapis.com/v1alpha/projects/${PROJECT_NUMBER}/locations/global/collections/default_collection/engines/${APP_ID}/assistants/default_assistant/agents"

# Build the jsonAgentCard (escaped JSON string for embedding)
# Must match the agent card returned by the deployed Agent Engine
AGENT_CARD=$(jq -n -c \
  --arg name "$DISPLAY_NAME" \
  --arg desc "$DESCRIPTION" \
  --arg url "$A2A_URL" \
  '{
    protocolVersion: "0.3.0",
    name: $name,
    description: $desc,
    url: $url,
    version: "1.0.0",
    preferredTransport: "HTTP+JSON",
    supportsAuthenticatedExtendedCard: true,
    defaultInputModes: ["text/plain"],
    defaultOutputModes: ["application/json"],
    capabilities: { streaming: false },
    skills: [
      {
        id: "search_expert_requests",
        name: "Search Expert Requests",
        description: "Search and retrieve Expert Request (ER) data from Firestore. Can search by assigned CE email, creation date, or specific ER fields.",
        tags: ["Expert Request", "ER", "Firestore", "Search"],
        examples: ["Find all ERs assigned to user@google.com", "How many ERs were created in 2024?", "Show me the FSA status of ER-431059", "What ERs were created in April 2024?"]
      },
      {
        id: "background_tasks",
        name: "Background Task Management",
        description: "Submit and monitor long-running background tasks. Tasks run asynchronously and can be checked for completion.",
        tags: ["Tasks", "Background", "Async"],
        examples: ["Submit a background task called data_sync for 10 seconds", "Check the status of my task"]
      }
    ]
  }' | sed 's/"/\\"/g')

# Helper: execute curl, pretty-print JSON response, show HTTP status code
curl_jq() {
  local tmpfile
  tmpfile=$(mktemp)
  local http_code
  http_code=$(curl -s -o "$tmpfile" -w "%{http_code}" "$@")
  jq . "$tmpfile" 2>/dev/null || cat "$tmpfile"
  echo ""
  echo "HTTP Status Code: ${http_code}"
  rm -f "$tmpfile"
}

usage() {
  echo "Usage: $0 {"
  echo "  register |"
  echo "  register-auth |"
  echo "  list [name] |"
  echo "  delete <AGENT_ID> |"
  echo "  create-auth |"
  echo "  delete-auth"
  echo "}"
  echo ""
  echo "Note: All configuration is loaded from .env file"
  exit 1
}

if [ $# -lt 1 ]; then
  usage
fi

COMMAND=$1

case $COMMAND in
  register)
    curl_jq -X POST \
      -H "Authorization: Bearer $(gcloud auth print-access-token)" \
      -H "Content-Type: application/json" \
      -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
      "${BASE_URL}" \
      -d '{
        "name": "'"${DISPLAY_NAME}"'",
        "displayName": "'"${DISPLAY_NAME}"'",
        "description": "'"${DESCRIPTION}"'",
        "a2aAgentDefinition": {
          "jsonAgentCard": "'"${AGENT_CARD}"'"
        }
      }'
    ;;
  register-auth)
    curl_jq -X POST \
      -H "Authorization: Bearer $(gcloud auth print-access-token)" \
      -H "Content-Type: application/json" \
      -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
      "${BASE_URL}" \
      -d '{
        "name": "'"${DISPLAY_NAME}"'",
        "displayName": "'"${DISPLAY_NAME}"'",
        "description": "'"${DESCRIPTION}"'",
        "a2aAgentDefinition": {
          "jsonAgentCard": "'"${AGENT_CARD}"'"
        },
        "authorizationConfig": {
          "agentAuthorization": "projects/'"${PROJECT_NUMBER}"'/locations/global/authorizations/'"${AUTH_ID}"'"
        }
      }'
    ;;
  create-auth)
    curl_jq -X POST \
      -H "Authorization: Bearer $(gcloud auth print-access-token)" \
      -H "Content-Type: application/json" \
      -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
      "https://discoveryengine.googleapis.com/v1alpha/projects/${PROJECT_NUMBER}/locations/global/authorizations?authorizationId=${AUTH_ID}" \
      -d '{
        "name": "projects/'"${PROJECT_NUMBER}"'/locations/global/authorizations/'"${AUTH_ID}"'",
        "serverSideOauth2": {
          "clientId": "'"${OAUTH_CLIENT_ID}"'",
          "clientSecret": "'"${OAUTH_CLIENT_SECRET}"'",
          "authorizationUri": "'"${OAUTH_AUTH_URI}"'",
          "tokenUri": "'"${OAUTH_TOKEN_URI}"'"
        }
      }'
    ;;
  delete-auth)
    curl_jq -X DELETE \
      -H "Authorization: Bearer $(gcloud auth print-access-token)" \
      -H "Content-Type: application/json" \
      -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
      "https://discoveryengine.googleapis.com/v1alpha/projects/${PROJECT_NUMBER}/locations/global/authorizations/${AUTH_ID}"
    ;;
  list)
    if [ $# -eq 2 ]; then
      # Name filter given — show full details for matching agents
      NAME=$2
      RESPONSE=$(curl -s -X GET \
        -H "Authorization: Bearer $(gcloud auth print-access-token)" \
        -H "Content-Type: application/json" \
        -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
        "${BASE_URL}")

      if command -v jq &> /dev/null; then
        FILTERED=$(echo "$RESPONSE" | jq --arg name "$NAME" \
          '{agents: [.agents[]? | select(.displayName | ascii_downcase | contains($name | ascii_downcase))]}')
        COUNT=$(echo "$FILTERED" | jq '.agents | length')
        if [ "$COUNT" -eq 0 ]; then
          echo "No agents found with name containing '$NAME'."
          echo "Available agents:"
          echo "$RESPONSE" | jq -r '.agents[]?.displayName // empty'
        else
          echo "$FILTERED" | jq .
        fi
      else
        echo "$RESPONSE"
      fi
    else
      # No name filter — show compact summary only
      curl -s -X GET \
        -H "Authorization: Bearer $(gcloud auth print-access-token)" \
        -H "Content-Type: application/json" \
        -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
        "${BASE_URL}" | jq '[.agents[]? | {displayName, reasoningEngine: (.adkAgentDefinition.provisionedReasoningEngine.reasoningEngine // .a2aAgentDefinition.jsonAgentCard // "N/A"), agentId: (.name | split("/") | last)}]'
    fi
    ;;
  delete)
    if [ $# -ne 2 ]; then
      echo "Error: delete requires AGENT_ID argument."
      usage
    fi
    AGENT_ID=$2
    curl_jq -X DELETE \
      -H "Authorization: Bearer $(gcloud auth print-access-token)" \
      -H "Content-Type: application/json" \
      -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
      "${BASE_URL}/${AGENT_ID}"
    ;;
  *)
    usage
    ;;
esac
