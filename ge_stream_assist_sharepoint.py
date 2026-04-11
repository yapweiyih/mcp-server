# Copyright (C) 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import logging
import os
import random

import google.auth
import google.auth.transport.requests
import requests
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


class AgentSpaceClient:
    """
    Client for interacting with the Gemini Enterprise streamAssist API.
    Provides methods for querying an Assistant/Agent and parsing responses.
    """

    def __init__(
        self,
        project_id: str,
        app_id: str,
        agent_id: str | None = None,
        location: str = "global",
        sharepoint_datastore_id: str | None = None,
        project_number: str | None = None,
        debug: bool = False,
    ):
        """
        Initializes the AgentSpaceClient.

        Args:
            project_id: The Google Cloud Project ID.
            app_id: The Discovery Engine app/engine ID.
            agent_id: (Optional) The Agent ID (short form or full resource name).
            location: The deployment location (e.g., 'global').
            sharepoint_datastore_id: (Optional) SharePoint DataStore ID.
        """
        self.project_id = project_id
        self.app_id = app_id
        self.location = location
        self._access_token = None
        self.sharepoint_datastore_id = sharepoint_datastore_id
        self.project_number = project_number
        self.debug = debug

        # Ensure agent_id is correctly formatted as a full resource name
        if agent_id and agent_id.strip():
            if "/" not in agent_id:
                # Construct full resource name if only short ID is provided
                self.agent_id = (
                    f"projects/{project_id}/locations/{location}/collections/default_collection/"
                    f"engines/{app_id}/assistants/default_assistant/agents/{agent_id}"
                )
            else:
                self.agent_id = agent_id
        else:
            self.agent_id = None

        # --- DataStore Specs Injection during Init ---
        self.data_store_specs = []
        if sharepoint_datastore_id:
            logging.info(
                f"Injecting SharePoint DataStoreSpec into Client Init with Datastore: {sharepoint_datastore_id}"
            )
            suffixes = ["_attachment", "_comment", "_event", "_page", "_file"]
            proj = self.project_number if self.project_number else self.project_id
            for suffix in suffixes:
                self.data_store_specs.append(
                    {
                        "data_store": f"projects/{proj}/locations/{self.location}/collections/default_collection/dataStores/{sharepoint_datastore_id}{suffix}"
                    }
                )

    def get_access_token(self) -> str:
        """
        Retrieves a valid GCP access token with cloud-platform Scope.

        Returns:
            The access token string.
        """
        if not self._access_token:
            logging.info("Refreshing access token...")
            credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            auth_req = google.auth.transport.requests.Request()
            credentials.refresh(auth_req)
            self._access_token = credentials.token
        return self._access_token

    def query_assistant(self, query_text: str, session_id: str | None = None) -> dict:
        """
        Sends a query to the streamAssist API.

        Args:
            query_text: The prompt string to send to the assistant.
            session_id: (Optional) The session ID to use/resume. Defaults to random/new ("-").

        Returns:
            The JSON response dictionary from the API.
        """
        token = self.get_access_token()
        url = (
            f"https://discoveryengine.googleapis.com/v1alpha/projects/{self.project_id}/"
            f"locations/{self.location}/collections/default_collection/engines/{self.app_id}/"
            f"assistants/default_assistant:streamAssist"
        )

        # Generate a 19-digit random session ID if not provided, resembling what API expectation models
        sess_id = session_id if session_id else "-"
        proj = self.project_number if self.project_number else self.project_id

        # Build payload based on verified patterns
        payload = {
            "name": f"projects/{proj}/locations/{self.location}/collections/default_collection/engines/{self.app_id}/assistants/default_assistant",
            "query": {"parts": [{"text": query_text}]},
            "session": f"projects/{proj}/locations/{self.location}/collections/default_collection/engines/{self.app_id}/sessions/{sess_id}",
            "answer_generation_mode": "NORMAL",
            "assist_skipping_mode": "REQUEST_ASSIST",
            "user_metadata": {"time_zone": "Asia/Singapore"},
            "tools_spec": {
                "vertex_ai_search_spec": {"data_store_specs": []},
                "image_generation_spec": {},
                "video_generation_spec": {},
                "tool_registry": "default_tool_registry",
            },
        }

        # Inject DataStore Specs populated during init
        if hasattr(self, "data_store_specs") and self.data_store_specs:
            payload["tools_spec"]["vertex_ai_search_spec"]["data_store_specs"].extend(
                self.data_store_specs
            )

        # Save raw request to a json file (only in debug mode)
        if self.debug:
            request_file = "sharepoint_stream_assist_request.json"
            with open(request_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            logging.info(f"Saved raw request to {request_file}")

        logging.info(f"Sending streamAssist request for query: {query_text}")
        response = requests.post(
            url, headers={"Authorization": f"Bearer {token}"}, json=payload
        )

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            logging.error(f"HTTP Error: {e.response.text}")
            raise

        return response.json()

    def list_assistant_info(self) -> list[dict] | None:
        """
        List all assistants for the configured Discovery Engine.

        Returns:
            List of assistant dictionaries or None if the operation fails.
        """
        access_token = self.get_access_token()
        parent = (
            f"projects/{self.project_id}/locations/{self.location}"
            f"/collections/default_collection/engines/{self.app_id}"
        )
        url = f"https://discoveryengine.googleapis.com/v1alpha/{parent}/assistants"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        all_assistants = []
        page_token = None

        try:
            logging.info("Fetching assistants information from API...")
            while True:
                params = {}
                if page_token:
                    params["pageToken"] = page_token

                response = requests.get(url, headers=headers, params=params)
                response.raise_for_status()

                data = response.json()
                assistants_on_page = data.get("assistants", [])

                if not assistants_on_page:
                    break

                all_assistants.extend(assistants_on_page)

                page_token = data.get("nextPageToken")
                if not page_token:
                    break

            return all_assistants

        except Exception as e:
            logging.error(f"Error listing assistants: {e}")
            return None

    @staticmethod
    def filter_and_extract(
        result: list | dict, extract_references: bool = False
    ) -> dict:
        """
        Filters 'thought' replies and extracts final grounded text from the response,
        along with metadata like query, assistToken, and attributionToken.

        Args:
            result: The response from the streamAssist API (can be a dict or list of dicts).
            extract_references: (Optional) If True, extracts grounding references.

        Returns:
            A dictionary containing:
            'text': The extracted final answer text string.
            'query': The user query if found.
            'assistToken': The assist token if found.
            'attributionToken': The attribution token if found.
            'references': List of reference dicts (uri, title, document) if requested.
        """
        if not isinstance(result, list):
            result = [result]

        extracted_text = []
        found_query = None
        assist_token = None
        attribution_token = None
        references = []

        for entry in result:
            # 1. Extract Text
            if "answer" in entry and "replies" in entry["answer"]:
                for reply in entry["answer"]["replies"]:
                    if "groundedContent" in reply:
                        gc = reply["groundedContent"]
                        content = gc.get("content", {})
                        # Skip replies that contain "thoughts" / reasoning to present clean text to user
                        if content.get("thought") is True:
                            logging.debug("Skipping thought content")
                            continue

                        text = content.get("text")
                        if text:
                            extracted_text.append(text)

                        # Extract References
                        if extract_references and "textGroundingMetadata" in gc:
                            tg_metadata = gc["textGroundingMetadata"]
                            if "references" in tg_metadata:
                                for ref in tg_metadata["references"]:
                                    if "documentMetadata" in ref:
                                        doc_meta = ref["documentMetadata"]
                                        ref_dict = {
                                            "uri": doc_meta.get("uri"),
                                            "title": doc_meta.get("title"),
                                            "document": doc_meta.get("document"),
                                        }
                                        if ref_dict not in references:
                                            references.append(ref_dict)

                    # Fallback for simple content or other structures if they exist
                    elif "content" in reply and "text" in reply["content"]:
                        extracted_text.append(reply["content"]["text"])

            # 2. Extract Query
            if "answer" in entry and "diagnosticInfo" in entry["answer"]:
                diag = entry["answer"]["diagnosticInfo"]
                if "plannerSteps" in diag:
                    for step in diag["plannerSteps"]:
                        if "queryStep" in step:
                            parts = step["queryStep"].get("parts", [])
                            if parts and "text" in parts[0]:
                                found_query = parts[0]["text"]

            # 3. Extract Assist Token
            if "assistToken" in entry and not assist_token:
                assist_token = entry["assistToken"]

            # 4. Extract Attribution Token
            if "attributionToken" in entry and not attribution_token:
                attribution_token = entry["attributionToken"]
            elif "answer" in entry and "replies" in entry["answer"]:
                for reply in entry["answer"]["replies"]:
                    if "groundedContent" in reply:
                        gc = reply["groundedContent"]
                        if "attributionToken" in gc and not attribution_token:
                            attribution_token = gc["attributionToken"]

        return {
            "text": "".join(extracted_text),
            "query": found_query,
            "assistToken": assist_token,
            "attributionToken": attribution_token,
            "references": references,
        }


if __name__ == "__main__":
    # Load configuration from adk_agent/.env file
    _env_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "adk_agent", ".env"
    )
    load_dotenv(_env_path)

    # Configuration OVERRIDES (Set these values to override .env variables for testing)
    OVERRIDE_PROJECT_ID = None
    OVERRIDE_APP_ID = None
    OVERRIDE_AGENT_ID = None
    OVERRIDE_LOCATION = None
    OVERRIDE_SHAREPOINT_DATASTORE_ID = None
    OVERRIDE_PROJECT_NUMBER = None

    project_id = (
        OVERRIDE_PROJECT_ID
        if OVERRIDE_PROJECT_ID is not None
        else os.getenv("PROJECT_ID", os.getenv("GOOGLE_CLOUD_PROJECT"))
    )
    app_id = OVERRIDE_APP_ID if OVERRIDE_APP_ID is not None else os.getenv("APP_ID")
    agent_id = (
        OVERRIDE_AGENT_ID if OVERRIDE_AGENT_ID is not None else os.getenv("AGENT_ID")
    )
    location = (
        OVERRIDE_LOCATION
        if OVERRIDE_LOCATION is not None
        else os.getenv("LOCATION", "global")
    )

    # SharePoint config
    # Loading SHAREPOINT_COLLECTION_ID value as the DataStore ID per project layout instruction
    sharepoint_datastore_id = (
        OVERRIDE_SHAREPOINT_DATASTORE_ID
        if OVERRIDE_SHAREPOINT_DATASTORE_ID is not None
        else os.getenv("SHAREPOINT_COLLECTION_ID")
    )
    project_number = (
        OVERRIDE_PROJECT_NUMBER
        if OVERRIDE_PROJECT_NUMBER is not None
        else os.getenv("PROJECT_NUMBER")
    )

    print("\n--- Current Configuration ---")
    print(f"PROJECT_ID: {project_id}")
    print(f"APP_ID: {app_id}")
    print(f"AGENT_ID: {agent_id}")
    print(f"LOCATION: {location}")
    print(f"SHAREPOINT_COLLECTION_ID: {sharepoint_datastore_id}")
    print(f"PROJECT_NUMBER: {project_number}")

    if not all([project_id, app_id]):
        logging.error("Missing required environment variables. Please check .env file.")
        logging.info("Expected: PROJECT_ID, APP_ID")
        exit(1)

    client = AgentSpaceClient(
        project_id=project_id,
        app_id=app_id,
        agent_id=agent_id,
        location=location,
        sharepoint_datastore_id=sharepoint_datastore_id,
        project_number=project_number,
    )

    try:
        print("\n--- DataStore Specs Verification ---")
        if hasattr(client, "data_store_specs"):
            print(json.dumps(client.data_store_specs, indent=2))

        print("\n--- Querying Assistant ---")
        prompt = "What expert requests are assigned to weiyih@google.com?"
        response = client.query_assistant(prompt)

        # Save raw response to a json file (debug mode)
        if client.debug:
            output_file = "sharepoint_stream_assist_response.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(response, f, indent=2)
            print(f"\n--- Saved Raw Response to {output_file} ---")

        print("\n--- Extracted Answer & Metadata ---")
        extraction = client.filter_and_extract(response, extract_references=True)

        print(f"Query: {extraction['query'] if extraction['query'] else prompt}")
        print(f"Full Text Response:\n{extraction['text']}")
        print(f"Assist Token: {extraction['assistToken']}")
        print(f"Attribution Token: {extraction['attributionToken']}")

        if extraction.get("references"):
            print("\n--- Grounding References ---")
            for i, ref in enumerate(extraction["references"], 1):
                print(f"[{i}] {ref['title']}")
                print(f"    URI: {ref['uri']}")
                print(f"    Document: {ref['document']}")

    except Exception as e:
        logging.error(f"An error occurred during demonstration: {e}")
