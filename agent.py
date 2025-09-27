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
import os
import re
import json
from google.adk.agents import Agent

# ADK SlidesToolSet
from google.adk.tools.google_api_tool import SlidesToolset
from google.adk.tools import google_search, AgentTool

from dotenv import load_dotenv
load_dotenv()


# --- Model Configuration ---
MODEL_NAME = "gemini-2.5-flash"

# ==============================================================================
# --- ADK Authentication Configuration ---
# ==============================================================================
try:
    with open("./slide-gen-agent/credentials.json", "r") as f:
        client_secrets = json.load(f)["web"]
        CLIENT_ID = client_secrets["client_id"]
        CLIENT_SECRET = client_secrets["client_secret"]
except FileNotFoundError:
    raise FileNotFoundError(
        "credentials.json not found. Please download it from your GCP project's OAuth 2.0 Client IDs."
    )
except KeyError:
    raise ValueError("credentials.json is malformed. It must contain 'installed' with 'client_id' and 'client_secret'.")


# ==============================================================================
# --- Tool Definitions (Refactored for ADK Authentication) ---
# ==============================================================================
slides_toolset = SlidesToolset(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
)

search_agent = Agent(
name="search_agent",
model="gemini-2.5-pro",
description="An AI agent to search for content using Google Search.",
instruction="You are an expert at using Google Search to find relevant information for presentations.",
tools=[google_search]
)

SlideGeneratorAgent = Agent(
    name="slide_generator_agent",
    model="gemini-2.5-pro",
    description="An AI agent to create presentations using Google Slides API.",
    instruction="""
  You are an expert at using the Google Slides API, and you create slides with the clarity and impact of a McKinsey analyst.
1. First, use the search_agent to find content for the presentation topic.
2. Then, create a new presentation using the slides_presentations_create tool. The body should contain a title.
3. Use the slides_presentations_batch_update tool to add slides and content. The first slide should have the title of the presentation.
4. Finally, report the URL of the created presentation to the user.
    """,
    tools=[
    slides_toolset,
    AgentTool(search_agent) 
    ]
)

# ==============================================================================
# --- Final App Initialization and ADK Export ---
# ==============================================================================
root_agent = SlideGeneratorAgent