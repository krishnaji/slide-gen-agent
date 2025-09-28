# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import re
from typing import Any

import requests
import vertexai
from fastapi.openapi.models import OAuth2
from fastapi.openapi.models import OAuthFlowAuthorizationCode
from fastapi.openapi.models import OAuthFlows
from google.adk.agents import Agent
from google.adk.auth.auth_credential import AuthCredential
from google.adk.auth.auth_credential import AuthCredentialTypes
from google.adk.auth.auth_credential import OAuth2Auth
from google.adk.auth.auth_tool import AuthConfig
from google.adk.tools.authenticated_function_tool import AuthenticatedFunctionTool
from google.adk.tools import FunctionTool,AgentTool
from google.adk.tools import google_search
from googleapiclient.discovery import build
from google.oauth2 import credentials
import uuid

# ==============================================================================
# --- Configuration ---
# ==============================================================================

# --- API Scopes ---
SCOPES = [
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents.readonly",
]

# --- Model Configuration ---
MODEL_NAME = "gemini-2.5-flash"

# --- Template Configuration ---
# The ID is the long string in the URL, e.g., .../presentation/d/PRESENTATION_ID/edit
TEMPLATE_ID = "1CHFtSGAvm-XdHX3RSDjM7RabFG5MDeq9kKgfcsEYyRI"
 
# ==============================================================================
# --- Authentication Setup for Web OAuth Flow ---
# ==============================================================================
def load_credentials() -> tuple[str, str]:
    """Loads OAuth client ID and secret from credentials.json."""
    if not os.path.exists("./slide-gen-agent/credentials.json"):
        raise FileNotFoundError(
            "credentials.json not found. Please follow the setup instructions to"
            " create and place it in the correct directory."
        )
    with open("./slide-gen-agent/credentials.json", "r") as f:
        # Assumes credentials are for a 'web' application
        creds_data = json.load(f).get("web", {})
    client_id = creds_data.get("client_id")
    client_secret = creds_data.get("client_secret")
    if not client_id or not client_secret:
        raise ValueError(
            "client_id and/or client_secret not found in credentials.json."
        )
    return client_id, client_secret


client_id, client_secret = load_credentials()


# authorization for the specified Google API scopes.
google_auth_config = AuthConfig(
    auth_scheme=OAuth2(
        flows=OAuthFlows(
            authorizationCode=OAuthFlowAuthorizationCode(
                authorizationUrl="https://accounts.google.com/o/oauth2/auth",
                tokenUrl="https://oauth2.googleapis.com/token",
                scopes={scope: "Access Google APIs" for scope in SCOPES},
            )
        )
    ),
    raw_auth_credential=AuthCredential(
        auth_type=AuthCredentialTypes.OAUTH2,
        oauth2=OAuth2Auth(client_id=client_id, client_secret=client_secret),
    ),
)


# ==============================================================================
# --- Tool Definitions ---
# ==============================================================================
def create_presentation_from_template(title: str,  credential: AuthCredential) -> str:
    """Creates a new Google Slides presentation by copying a predefined template."""
    creds = credentials.Credentials(token=credential.oauth2.access_token)
    drive_service = build("drive", "v3", credentials=creds)
    if "YOUR_PRESENTATION_ID_HERE" in TEMPLATE_ID:
        return "Error: The TEMPLATE_ID has not been configured in agent.py."
    try:
        copied_file = (
            drive_service.files()
            .copy(fileId=TEMPLATE_ID, body={"name": title})
            .execute()
        )
        pid = copied_file.get("id")
        return f"Presentation created. ID: {pid}. URL: https://docs.google.com/presentation/d/{pid}/"
    except Exception as e:
        return f"Error: {e}"


def read_google_doc(doc_url: str, credential:  AuthCredential) -> str:
    """Reads the text content of a Google Doc."""
    creds = credentials.Credentials(token=credential.oauth2.access_token)
    docs_service = build("docs", "v1", credentials=creds)
    match = re.search(r"/document/d/([a-zA-Z0-9-_]+)", doc_url)
    if not match:
        return "Error: Invalid Google Doc URL."
    try:
        doc = docs_service.documents().get(documentId=match.group(1)).execute()
        content = doc.get("body").get("content")
        return "".join(
            elem.get("textRun", {}).get("content", "")
            for value in content
            if "paragraph" in value
            for elem in value.get("paragraph").get("elements")
        )
    except Exception as e:
        return f"Error: {e}"


def read_content_from_public_url(url: str) -> str:
    """Reads text content from a public URL, like a Google Cloud Storage public link."""
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        return f"Error fetching content from URL: {e}"

def create_slide(presentation_id: str, title: str, body: str, credential: AuthCredential) -> str:
    """
    Creates a new slide with a title and body, dynamically finding a suitable layout.
    """
    creds = credentials.Credentials(token=credential.oauth2.access_token)
    slides_service = build("slides", "v1", credentials=creds)
    try:
        # 1. Get presentation details to find available layouts
        presentation = slides_service.presentations().get(
            presentationId=presentation_id, fields="layouts"
        ).execute()
        layouts = presentation.get("layouts", [])

        # 2. Find a layout with both a TITLE and a BODY placeholder
        suitable_layout_id = None
        for layout in layouts:
            has_title = False
            has_body = False
            for element in layout.get("pageElements", []):
                placeholder = element.get("shape", {}).get("placeholder", {})
                if placeholder:
                    placeholder_type = placeholder.get("type")
                    if placeholder_type == "TITLE":
                        has_title = True
                    elif placeholder_type == "BODY":
                        has_body = True
            if has_title and has_body:
                suitable_layout_id = layout["objectId"]
                break

        if not suitable_layout_id:
            return 'Error: Could not find a suitable layout with both a title and a body placeholder in the presentation template.'

        # 3. Create the new slide using the found layout ID
        create_slide_request = {
            "createSlide": {
                "objectId": f"new_slide_{uuid.uuid4()}",
                "slideLayoutReference": {
                    "layoutId": suitable_layout_id
                }
            }
        }
        response = slides_service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": [create_slide_request]}
        ).execute()

        slide_id = response["replies"][0]["createSlide"]["objectId"]

        # 4. Get the placeholder IDs for the new slide's title and body
        slide = slides_service.presentations().get(
            presentationId=presentation_id,
            fields=f"slides(objectId,pageElements(objectId,shape(placeholder(type))))"
        ).execute().get('slides', [])

        new_slide_elements = next((s['pageElements'] for s in slide if s['objectId'] == slide_id), None)
        if not new_slide_elements:
            return f"Error: Could not find elements on the newly created slide '{slide_id}'."

        title_id = next(
            (e["objectId"] for e in new_slide_elements if e.get("shape", {}).get("placeholder", {}).get("type") == "TITLE"),
            None
        )
        body_id = next(
            (e["objectId"] for e in new_slide_elements if e.get("shape", {}).get("placeholder", {}).get("type") == "BODY"),
            None
        )

        if not title_id or not body_id:
             return f"Error: Could not find title or body placeholders on the new slide using layout '{suitable_layout_id}'."

        # 5. Insert the title and body text into the placeholders
        insert_text_requests = [
            {"insertText": {"objectId": title_id, "text": title}},
            {"insertText": {"objectId": body_id, "text": body}},
        ]
        slides_service.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": insert_text_requests}
        ).execute()

        return f"Slide '{title}' created successfully."
    except Exception as e:
        return f"An unexpected error occurred: {e}"

# ==============================================================================
# --- Agent Definition ---
# ==============================================================================
search_agent = Agent(
name="search_agent",
model=MODEL_NAME,
description="An AI agent to search for content using Google Search.",
instruction="You are an expert at using Google Search to find relevant information for presentations.",
tools=[google_search]
)
SlideGeneratorAgent = Agent(
    name="slide_generator_agent",
    model=MODEL_NAME,
    description="An AI agent to create presentations from text or documents.",
    instruction=f"""
    **Persona & Tone:** Professional, concise, data-driven, and direct.
    **Goal:** Understand user intent to create a useful and relevant presentation draft.

    **Workflow:**
    1.  **Understand & Clarify:** Greet the user. Ask for the presentation's topic, purpose, and audience. Ask if they have content (e.g., a Google Doc link, a public Google Cloud Storage URL, or text). Ask for the desired tone and slide count. Ask if you should use Google Search for more content.
    2.  **Gather & Plan:** After clarifying, call `create_presentation_from_template` with a suitable title. If the user provides a URL for the content, choose the correct tool: for 'docs.google.com' links, use `read_google_doc`; for other links (like 'storage.googleapis.com'), use `read_content_from_public_url`. Synthesize all info into a plan.
    3.  **Structure & Generate:** Create a logical flow (e.g., Intro, Problem, Solution, Conclusion). For each slide, generate a concise title and scannable body text. Call `create_slide` for each.
    4.  **Research** If external research is approved, delegate queries to the `search_agent` to gather supplementary facts and data.
    4.  **Deliver & Refine:** Provide the presentation URL. State that it is a first draft and you are ready for feedback (e.g., "The draft is ready. Let me know what changes you'd like."). Await their response.
    """,
    tools=[
        AuthenticatedFunctionTool(
            func=create_presentation_from_template, auth_config=google_auth_config
        ),
        AuthenticatedFunctionTool(func=read_google_doc, auth_config=google_auth_config),
        FunctionTool(func=read_content_from_public_url),
        AuthenticatedFunctionTool(func=create_slide, auth_config=google_auth_config),
        AgentTool(search_agent)
    ],
)

# ==============================================================================
# --- Final App Initialization and ADK Export ---
# ==============================================================================
root_agent = SlideGeneratorAgent
 