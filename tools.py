# tools.py
import json
import logging
import os
from pydantic import BaseModel, Field
from typing import Literal, List, Dict, Any, Optional
from tavily import TavilyClient # <-- Import TavilyClient

logger = logging.getLogger(__name__)

# --- Tool Schemas ---

class GetCurrentWeatherParams(BaseModel):
    """Parameters schema for the get_current_weather tool."""
    location: str = Field(..., description="The city and state/country, e.g., 'San Francisco, CA' or 'Jakarta, Indonesia'")
    unit: Literal['celsius', 'fahrenheit'] = Field("celsius", description="The temperature unit (default: celsius)")

# --- NEW: Web Search Tool Schema ---
class WebSearchParams(BaseModel):
    """Parameters schema for the web_search tool."""
    query: str = Field(..., description="The search query to look up on the web.")

# --- Tool Definitions List (for the LLM) ---
available_tools_definitions = [
    {
        "type": "function",
        "function": {
            "name": "get_current_weather",
            "description": "Get the current weather in a specific location.",
            "parameters": GetCurrentWeatherParams.schema() # Use Pydantic model schema
        }
    },
    # --- NEW: Add Web Search Tool Definition ---
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Searches the web for information on a given query. Use this for recent events, specific facts, or topics outside common knowledge.",
            "parameters": WebSearchParams.schema() # Use Pydantic model schema
        }
    }
    # --- Add more tool definitions here later ---
]

# --- Tool Execution Logic ---

def get_current_weather(location: str, unit: str = "celsius") -> str:
    """
    Placeholder function to simulate calling a weather API.
    """
    logger.info(f"Simulating tool call: get_current_weather(location='{location}', unit='{unit}')")
    # ... (simulation logic remains the same) ...
    if "jakarta" in location.lower():
        temp = 30 if unit == "celsius" else 86
        condition = "Hot and humid"
    elif "dallas" in location.lower():
        temp = 85 if unit == "fahrenheit" else 29
        condition = "Partly cloudy"
    else:
        temp = 20 if unit == "celsius" else 68
        condition = "Pleasant"

    return json.dumps({
        "location": location,
        "temperature": temp,
        "unit": unit,
        "condition": condition,
        "forecast": "Stable for the next few hours."
    })

async def web_search(query: str) -> str: # Function remains async
    """
    Performs a web search using the Tavily API.
    """
    logger.info(f"Executing tool call: web_search(query='{query}')")
    tavily_api_key = os.getenv("TAVILY_API_KEY")
    if not tavily_api_key:
        logger.error("TAVILY_API_KEY not found in environment variables.")
        return json.dumps({"error": "Tavily API key not configured."})

    try:
        # Note: TavilyClient itself doesn't seem to have a dedicated async client
        # like OpenAI does. The standard client's methods are synchronous.
        tavily_client = TavilyClient(api_key=tavily_api_key)

        # --- REMOVE await FROM THIS LINE ---
        # Original: response = await tavily_client.search(
        response = tavily_client.search( # <-- No await here
            query=query,
            search_depth="basic",
            include_answer=True,
            max_results=5
        )
        # --- End of change ---

        # Check the structure of the response (it's usually a dict)
        logger.debug(f"Tavily raw response: {response}") # Add debug log

        if isinstance(response, dict): # Check if response is a dictionary as expected
            if response.get("answer"):
                logger.info(f"Tavily search provided a direct answer for query: '{query}'")
                return json.dumps({"summary": response["answer"]})
            elif response.get("results"):
                logger.info(f"Tavily search returned {len(response['results'])} results for query: '{query}'")
                formatted_results = [
                    # Limit snippet length further if needed
                    f"Title: {res.get('title', 'N/A')}\nURL: {res.get('url', 'N/A')}\nSnippet: {res.get('content', 'N/A')[:150]}..."
                    for res in response["results"]
                ]
                return json.dumps({"results": formatted_results})
            else:
                logger.warning(f"Tavily search returned no answer or results for query: '{query}'. Response: {response}")
                return json.dumps({"message": "No relevant information found."})
        else:
            # Handle unexpected response format from Tavily
            logger.error(f"Unexpected response type from Tavily search: {type(response)}. Response: {response}")
            return json.dumps({"error": "Unexpected format received from search API."})


    except Exception as e:
        # Catching the specific error during the call is good,
        # but also catch potential errors processing the response.
        logger.error(f"Error during Tavily search or processing for query '{query}': {e}", exc_info=True)
        return json.dumps({"error": f"Search failed: {type(e).__name__}"})

# --- Mapping tool names to their implementation ---
tool_executor_map = {
    "get_current_weather": get_current_weather,
    "web_search": web_search, # <-- Add web_search mapping
}