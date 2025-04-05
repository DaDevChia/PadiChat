# tools.py
import json
import logging
from pydantic import BaseModel, Field
from typing import Literal, List, Dict, Any

logger = logging.getLogger(__name__)

# --- Tool Schemas (using Pydantic as per Nebius docs) ---

class GetCurrentWeatherParams(BaseModel):
    """Parameters schema for the get_current_weather tool."""
    location: str = Field(..., description="The city and state/country, e.g., 'San Francisco, CA' or 'Jakarta, Indonesia'")
    unit: Literal['celsius', 'fahrenheit'] = Field("celsius", description="The temperature unit (default: celsius)")

# --- Tool Definitions List (for the LLM) ---
# This list describes the tools available to the LLM.
available_tools_definitions = [
    {
        "type": "function",
        "function": {
            "name": "get_current_weather",
            "description": "Get the current weather in a specific location.",
            "parameters": GetCurrentWeatherParams.schema() # Use Pydantic model schema
        }
    },
    # --- Add more tool definitions here later ---
    # Example: Crop disease identification tool schema
    # {
    #     "type": "function",
    #     "function": {
    #         "name": "identify_crop_disease",
    #         "description": "Analyzes an image of a crop to identify potential diseases.",
    #         "parameters": {
    #             "type": "object",
    #             "properties": {
    #                "image_url": { # Or maybe image data needs to be handled differently
    #                     "type": "string",
    #                     "description": "URL of the crop image to analyze."
    #                 }
    #              },
    #             "required": ["image_url"]
    #         }
    #     }
    # }
]

# --- Tool Execution Logic (Simulated for now) ---

def get_current_weather(location: str, unit: str = "celsius") -> str:
    """
    Placeholder function to simulate calling a weather API.
    In a real implementation, this would use 'requests' to call OpenWeatherMap, etc.
    """
    logger.info(f"Simulating tool call: get_current_weather(location='{location}', unit='{unit}')")
    # Simulate different responses based on location for demo
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

# --- Mapping tool names to their implementation ---
# This dictionary will be used by the LangGraph agent to execute the right function.
tool_executor_map = {
    "get_current_weather": get_current_weather,
    # "identify_crop_disease": identify_crop_disease_function, # Add real function later
}