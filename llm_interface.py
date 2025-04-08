# llm_interface.py
import os
from openai import AsyncOpenAI

# --- Model Definitions ---
TEXT_TOOL_MODEL_NAME = "meta-llama/Meta-Llama-3.1-70B-Instruct-fast"
VISION_MODEL_NAME = "google/gemma-3-27b-it-fast"

# --- Nebius OpenAI Client Configuration ---
def get_nebius_client() -> AsyncOpenAI:
    """Initializes and returns the ASYNCHRONOUS OpenAI client configured for Nebius."""
    api_key = os.getenv("NEBIUS_API_KEY")
    if not api_key:
        raise ValueError("NEBIUS_API_KEY not found in environment variables.")

    client = AsyncOpenAI(
        base_url="https://api.studio.nebius.com/v1/",
        api_key=api_key,
    )
    return client

# Initialize client globally or create on demand
nebius_client: AsyncOpenAI = get_nebius_client() # Add type hint for clarity

print(f"LLM Interface Configured (Async Client):") # Update print statement
print(f"  Text/Tool Model: {TEXT_TOOL_MODEL_NAME}")
print(f"  Vision Model:    {VISION_MODEL_NAME}")