#! /bin/env bash

source adk_agent/.env

# Delete existing ADK Agent with the same DISPLAY NAME if any
OLD_AGENT_ID=$(bash as_register.sh list ${DISPLAY_NAME} | grep "name" | grep -o '/agents/[0-9]*' | cut -d'/' -f3)

echo "  OLD_AGENT_ID: $OLD_AGENT_ID"
echo

echo "**********************************************"
echo "Delete old agentspace agent: $OLD_AGENT_ID"
bash as_register.sh delete $OLD_AGENT_ID
echo

echo "**********************************************"
echo "Delete AUTH_ID: $AUTH_ID"
bash as_register.sh delete-auth $AUTH_ID
echo
