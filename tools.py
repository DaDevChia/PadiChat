# tools.py
import json
import logging
import os
from pydantic import BaseModel, Field
from typing import Literal, List, Dict, Any, Optional
from tavily import TavilyClient

logger = logging.getLogger(__name__)

class GetCurrentWeatherParams(BaseModel):
    location: str = Field(..., description="The city and state/country, e.g., 'San Francisco, CA' or 'Jakarta, Indonesia'")
    unit: Literal['celsius', 'fahrenheit'] = Field("celsius", description="The temperature unit (default: celsius)")

class WebSearchParams(BaseModel):
    query: str = Field(..., description="The search query to look up on the web.")

available_tools_definitions = [
    {
        "type": "function",
        "function": {
            "name": "get_current_weather",
            "description": "Get the current weather in a specific location.",
            "parameters": GetCurrentWeatherParams.schema()
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Searches the web for information on a given query. Use this for recent events, specific facts, or topics outside common knowledge. Provides search results with snippets and URLs.",
            "parameters": WebSearchParams.schema()
        }
    }
]

def get_current_weather(location: str, unit: str = "celsius") -> str:
    logger.info(f"Simulating tool call: get_current_weather(location='{location}', unit='{unit}')")
    if "jakarta" in location.lower(): temp = 30 if unit == "celsius" else 86; condition = "Hot and humid"
    elif "dallas" in location.lower(): temp = 85 if unit == "fahrenheit" else 29; condition = "Partly cloudy"
    else: temp = 20 if unit == "celsius" else 68; condition = "Pleasant"
    return json.dumps({"location": location, "temperature": temp, "unit": unit, "condition": condition, "forecast": "Stable for the next few hours."})


async def web_search(query: str) -> str:
    """
    Performs a web search using the Tavily API and returns a structured
    JSON string containing results (title, url, content) and optionally a summary answer.
    """
    logger.info(f"Executing tool call: web_search(query='{query}')")
    tavily_api_key = os.getenv("TAVILY_API_KEY")
    if not tavily_api_key:
        logger.error("TAVILY_API_KEY not found in environment variables.")
        return json.dumps({"error": "Tavily API key not configured."})

    try:
        tavily_client = TavilyClient(api_key=tavily_api_key)
        # Perform the synchronous search call (no await)
        response_dict = tavily_client.search(
            query=query,
            search_depth="basic", # Basic is often enough and faster
            include_answer=True,  # Request the summarized answer
            include_raw_content=False, # Don't need raw HTML
            max_results=5 # Limit results
        )

        logger.debug(f"Tavily raw response dict: {response_dict}")

        # Prepare the structured output for the LLM
        output_data = {
            "query": response_dict.get("query", query),
            "tavily_answer": None, # Initialize
            "search_results": []
        }

        # Add the summarized answer if available
        if response_dict.get("answer"):
            output_data["tavily_answer"] = response_dict["answer"]
            logger.info(f"Tavily search provided a direct answer for query: '{query}'")

        # Process individual search results
        if isinstance(response_dict.get("results"), list):
             logger.info(f"Tavily search returned {len(response_dict['results'])} results for query: '{query}'")
             for res in response_dict["results"]:
                 # Ensure required fields exist and have reasonable values before adding
                 if res.get("url") and res.get("content"):
                     output_data["search_results"].append({
                         "title": res.get("title", "N/A"),
                         "url": res.get("url"),
                         # Use 'content' as it's the query-related snippet
                         "content_snippet": res.get("content")
                         # Optionally add 'score': res.get('score') if needed
                     })
                 else:
                     logger.warning(f"Skipping Tavily result missing URL or content: {res.get('title')}")

        # If no results AND no answer, indicate that
        if not output_data["tavily_answer"] and not output_data["search_results"]:
             logger.warning(f"Tavily search returned no answer or processable results for query: '{query}'. Response: {response_dict}")
             # Return a message indicating no info found
             return json.dumps({"query": query, "message": "No relevant information found from web search."})

        # Convert the structured output data to a JSON string for the ToolMessage
        output_json = json.dumps(output_data, ensure_ascii=False, indent=2)
        logger.debug(f"Formatted JSON output for LLM:\n{output_json}")
        return output_json

    except Exception as e:
        logger.error(f"Error during Tavily search or processing for query '{query}': {e}", exc_info=True)
        # Return an error structure in JSON format
        return json.dumps({"query": query, "error": f"Search failed: {type(e).__name__} - {e}"})


tool_executor_map = {
    "get_current_weather": get_current_weather,
    "web_search": web_search,
}