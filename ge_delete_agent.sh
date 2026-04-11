#! /bin/env bash

source adk_agent/.env

# Delete existing ADK Agent with the same DISPLAY NAME if any.
# Use jq to extract the FIRST matching agent ID from the filtered response.
OLD_AGENT_ID=$(bash ge_register.sh list "${DISPLAY_NAME}" 2>/dev/null \
  | sed -n '/^{/,/^}/p' \
  | jq -r '.agents[0].name // empty' \
  | grep -o '/agents/[0-9]*' \
  | cut -d'/' -f3)

if [ -z "$OLD_AGENT_ID" ]; then
  echo "No agent found with display name: ${DISPLAY_NAME}"
  exit 1
fi


echo "  OLD_AGENT_ID: $OLD_AGENT_ID"
echo

echo "**********************************************"
echo "Delete old agentspace agent: $OLD_AGENT_ID"
bash ge_register.sh delete "$OLD_AGENT_ID"
echo

echo "**********************************************"
echo "Delete AUTH_ID: $AUTH_ID"
bash ge_register.sh delete-auth "$AUTH_ID"
echo
