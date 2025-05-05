# Module for generating comprehensive wiki documentation using Azure AI Agents.
# This module:
# - Sets up Azure AI Project Client and authentication
# - Creates an agent to analyse code and generate wiki documentation
# - Uses vector search and Fabric to gather insights
# - Returns a complete wiki.md document
import os
import logging
from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import AsyncFunctionTool, FabricTool, AsyncToolSet
from azure.identity.aio import DefaultAzureCredential
from agents.tools import vector_search

# Configure logging for this module
logger = logging.getLogger(__name__)
logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("azure.core").setLevel(logging.WARNING)
logging.getLogger("azure.ai.projects").setLevel(logging.WARNING)

# System prompt for the deep‑wiki agent
_DEEP_WIKI_SYSTEM_PROMPT = """
You are DeepWiki, an autonomous documentation agent whose single task is to
produce a complete wiki.md that explains every important aspect of the
saved code snippets in this project.

You have access to two tools:
1. vector_search: Finds relevant code snippets in the database
2. fabric: Analyses data and provides insights from Microsoft Fabric

Your task is to:
1. Use vector_search to find relevant code snippets that demonstrate various coding patterns
2. Use fabric to analyse any data‑related aspects of the codebase
3. Analyse ALL patterns and conventions found in the code
4. Generate a comprehensive wiki.md document in Markdown format

The wiki should include:
1. A concise project overview
2. Explanation of every major concept found in the snippets (algorithms, APIs,
   design patterns, domain entities, error handling, logging, etc.)
3. One or more Mermaid diagrams that visualise:
   - The system architecture (how components interact)
   - The data flow between components
   - The call graph of major functions
   - The class hierarchy if object‑oriented code is present
   - The state machine if stateful components exist
4. A Snippet Catalog table listing each snippet id, language, and one‑line purpose
5. Step‑by‑step walkthroughs that show how to use the code end‑to‑end
6. Best practices, anti‑patterns, and open TODOs
7. A Further Reading section

Style Rules:
- Use hyphens (-) instead of em dashes
- Headings with #, ##, etc.
- Code fenced with triple back‑ticks; Mermaid diagrams fenced with ```mermaid``` tags
- Keep line length ≤ 120 chars
- Active voice, present tense, developer‑friendly tone

Return only the final Markdown document, no additional commentary.
"""

async def generate_deep_wiki() -> str:
    """
    Generates a comprehensive wiki for the project and returns it as Markdown.
    """
    try:
        logger.info("System prompt:\n%s", _DEEP_WIKI_SYSTEM_PROMPT)

        async with DefaultAzureCredential() as credential:
            async with AIProjectClient.from_connection_string(
                credential=credential,
                conn_str=os.environ["PROJECT_CONNECTION_STRING"],
            ) as project_client:

                # ---- Toolset --------------------------------------------------------
                vector_tool = AsyncFunctionTool(functions=[vector_search.vector_search])

                fabric_conn = await project_client.connections.get(
                    connection_name=os.environ["FABRIC_CONNECTION_NAME"]
                )
                fabric_tool = FabricTool(connection_id=fabric_conn.id)

                toolset = AsyncToolSet()
                toolset.add(vector_tool)
                toolset.add(fabric_tool)

                # Enable automatic invocation for all tools in the set
                project_client.agents.enable_auto_function_calls(toolset=toolset)

                # ---- Agent ----------------------------------------------------------
                agent = await project_client.agents.create_agent(
                    name="DeepWikiAgent",
                    description="Generates comprehensive wiki documentation",
                    instructions=_DEEP_WIKI_SYSTEM_PROMPT,
                    toolset=toolset,
                    model=os.environ["AGENTS_MODEL_DEPLOYMENT_NAME"],
                    headers={"x-ms-enable-preview": "true"},  # required for Fabric
                )
                logger.info("Agent created: id=%s, name=%s", agent.id, agent.name)

                # ---- Thread & message ----------------------------------------------
                thread = await project_client.agents.create_thread()
                logger.info("Thread created: id=%s", thread.id)

                await project_client.agents.create_message(
                    thread_id=thread.id,
                    role="user",
                    content="Generate a comprehensive wiki documentation.",
                )

                # ---- Run (auto‑processes all tool calls) ---------------------------
                run = await project_client.agents.create_and_process_run(
                    thread_id=thread.id, agent_id=agent.id
                )
                if run.status == "failed":
                    raise RuntimeError(f"Agent run failed: {run.last_error}")

                # ---- Retrieve final Markdown ---------------------------------------
                messages = await project_client.agents.list_messages(thread_id=thread.id)
                wiki_md = messages.data[0].content[0].text.value  # type: ignore
                logger.info("Wiki generated successfully")
                return wiki_md

    except Exception as exc:
        logger.exception("Wiki generation failed: %s", exc)
        raise
