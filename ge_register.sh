#!/usr/bin/env bash

# Source environment variables from .env file
# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo
if [ -f "${SCRIPT_DIR}/adk_agent/.env" ]; then
  source "${SCRIPT_DIR}/adk_agent/.env"
  echo "Loaded environment variables from adk_agent/.env file"
else
  echo "Warning: .env file not found in ${SCRIPT_DIR}/adk_agent/"
fi

echo "     GOOGLE_CLOUD_PROJECT: ${GOOGLE_CLOUD_PROJECT}"
echo "     APP_ID: ${APP_ID}"
echo "     OAUTH_AUTH_URI: ${OAUTH_AUTH_URI}"
echo "     ENGINE_ID: $ENGINE_ID"
echo "     DISPLAY_NAME: $DISPLAY_NAME"
echo "     AUTH_ID: $AUTH_ID"
echo
echo

if [ -n "$GOOGLE_CLOUD_PROJECT" ]; then
  PROJECT_NUMBER=$(gcloud projects describe "$GOOGLE_CLOUD_PROJECT" --format="value(projectNumber)")
else
  echo "Error: GOOGLE_CLOUD_PROJECT environment variable is not set"
  exit 1
fi

DESCRIPTION="This is your AI productivity agent"
TOOL_DESCRIPTION="You are a AI productivity agent."
LOCATION="us-central1"
OAUTH_CLIENT_ID=$(gcloud secrets versions access latest --secret="AGENTSPACE_WEB_CLIENTID" --project="${PROJECT_NUMBER}")
OAUTH_CLIENT_SECRET=$(gcloud secrets versions access latest --secret="AGENTSPACE_WEB_CLIENTSECRET" --project="${PROJECT_NUMBER}") # pragma: allowlist secret
OAUTH_TOKEN_URI="https://oauth2.googleapis.com/token"

ADK_DEPLOYMENT_ID=$ENGINE_ID
BASE_URL="https://discoveryengine.googleapis.com/v1alpha/projects/${PROJECT_NUMBER}/locations/global/collections/default_collection/engines/${APP_ID}/assistants/default_assistant/agents"

usage() {
  echo "Usage: $0 {"
  echo "  register |"
  echo "  list [name] |"
  echo "  delete <AGENT_ID> |"
  echo "  register-auth |"
  echo "  create-auth |"
  echo "  delete-auth |"
  echo "  update <AGENT_ID> |"
  echo "  update-auth <AGENT_ID>"
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
    curl -s -X POST \
      -H "Authorization: Bearer $(gcloud auth print-access-token)" \
      -H "Content-Type: application/json" \
      -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
      -w "\nHTTP Status Code: %{http_code}\n" \
      "${BASE_URL}" \
      -d '{
        "displayName": "'"${DISPLAY_NAME}"'",
        "description": "'"${DESCRIPTION}"'",
        "adk_agent_definition": {
          "tool_settings": {
            "tool_description": "'"${TOOL_DESCRIPTION}"'"
          },
          "provisioned_reasoning_engine": {
            "reasoning_engine": "projects/'"${PROJECT_NUMBER}"'/locations/'"${LOCATION}"'/reasoningEngines/'"${ADK_DEPLOYMENT_ID}"'"
          }
        }
      }' | jq .
    ;;
  register-auth)
    curl -s -X POST \
      -H "Authorization: Bearer $(gcloud auth print-access-token)" \
      -H "Content-Type: application/json" \
      -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
      -w "\nHTTP Status Code: %{http_code}\n" \
      "${BASE_URL}" \
      -d '{
        "displayName": "'"${DISPLAY_NAME}"'",
        "description": "'"${DESCRIPTION}"'",
        "adk_agent_definition": {
          "tool_settings": {
            "tool_description": "'"${TOOL_DESCRIPTION}"'"
          },
          "provisioned_reasoning_engine": {
            "reasoning_engine": "projects/'"${PROJECT_NUMBER}"'/locations/'"${LOCATION}"'/reasoningEngines/'"${ADK_DEPLOYMENT_ID}"'"
          }
        },
        "authorization_config": {
            "tool_authorizations": ["projects/'"${PROJECT_NUMBER}"'/locations/global/authorizations/'"${AUTH_ID}"'"]
        }
      }' | jq .
    ;;
  create-auth)
    curl -s -X POST \
      -H "Authorization: Bearer $(gcloud auth print-access-token)" \
      -H "Content-Type: application/json" \
      -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
      -w "\nHTTP Status Code: %{http_code}\n" \
      "https://discoveryengine.googleapis.com/v1alpha/projects/${PROJECT_NUMBER}/locations/global/authorizations?authorizationId=${AUTH_ID}" \
      -d '{
        "name": "projects/'"${PROJECT_NUMBER}"'/locations/global/authorizations/'"${AUTH_ID}"'",
        "serverSideOauth2": {
          "clientId": "'"${OAUTH_CLIENT_ID}"'",
          "clientSecret": "'"${OAUTH_CLIENT_SECRET}"'",
          "authorizationUri": "'"${OAUTH_AUTH_URI}"'",
          "tokenUri": "'"${OAUTH_TOKEN_URI}"'"
        }
      }' | jq .
    ;;
  delete-auth)
    curl -s -X DELETE \
      -H "Authorization: Bearer $(gcloud auth print-access-token)" \
      -H "Content-Type: application/json" \
      -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
      -w "\nHTTP Status Code: %{http_code}\n" \
      "https://discoveryengine.googleapis.com/v1alpha/projects/${PROJECT_NUMBER}/locations/global/authorizations/${AUTH_ID}" | jq .
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
    curl -s -X DELETE \
      -H "Authorization: Bearer $(gcloud auth print-access-token)" \
      -H "Content-Type: application/json" \
      -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
      -w "\nHTTP Status Code: %{http_code}\n" \
      "${BASE_URL}/${AGENT_ID}" | jq .
    ;;
  update)
    if [ $# -ne 2 ]; then
      echo "Error: update requires AGENT_ID argument."
      usage
    fi
    AGENT_ID=$2
    NEW_DISPLAY_NAME=$DISPLAY_NAME
    curl -s -X PATCH \
      -H "Authorization: Bearer $(gcloud auth print-access-token)" \
      -H "Content-Type: application/json" \
      -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
      -w "\nHTTP Status Code: %{http_code}\n" \
      "${BASE_URL}/${AGENT_ID}" \
      -d '{
        "displayName": "'"${NEW_DISPLAY_NAME}"'",
        "description": "'"${DESCRIPTION}"'",
        "adk_agent_definition": {
          "tool_settings": {
            "tool_description": "'"${TOOL_DESCRIPTION}"'"
          },
          "provisioned_reasoning_engine": {
            "reasoning_engine": "projects/'"${PROJECT_NUMBER}"'/locations/'"${LOCATION}"'/reasoningEngines/'"${ADK_DEPLOYMENT_ID}"'"
          }
        }
      }' | jq .
    ;;
  update-auth)
    if [ $# -ne 2 ]; then
      echo "Error: update-auth requires AGENT_ID argument."
      usage
    fi
    AGENT_ID=$2
    NEW_DISPLAY_NAME=$DISPLAY_NAME
    curl -s -X PATCH \
      -H "Authorization: Bearer $(gcloud auth print-access-token)" \
      -H "Content-Type: application/json" \
      -H "X-Goog-User-Project: ${PROJECT_NUMBER}" \
      -w "\nHTTP Status Code: %{http_code}\n" \
      "${BASE_URL}/${AGENT_ID}" \
      -d '{
        "displayName": "'"${NEW_DISPLAY_NAME}"'",
        "description": "'"${DESCRIPTION}"'",
        "adk_agent_definition": {
          "tool_settings": {
            "tool_description": "'"${TOOL_DESCRIPTION}"'"
          },
          "provisioned_reasoning_engine": {
            "reasoning_engine": "projects/'"${PROJECT_NUMBER}"'/locations/'"${LOCATION}"'/reasoningEngines/'"${ADK_DEPLOYMENT_ID}"'"
          }
        },
        "authorization_config": {
            "tool_authorizations": ["projects/'"${PROJECT_NUMBER}"'/locations/global/authorizations/'"${AUTH_ID}"'"]
        }
      }' | jq .
    ;;
  *)
    usage
    ;;
esac
