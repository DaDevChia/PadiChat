# llm_interface.py
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# --- Model Definitions ---
# Using Gemma-3 as it supports tool calling according to your docs/needs
# Use the "-fast" suffix if desired and available for this model
LLM_MODEL_NAME = "google/gemma-3-27b-it-fast"
# VISION_MODEL_NAME = "google/gemma-3-27b-it-fast" # Keep track if needed separately
# TEXT_MODEL_NAME = "deepseek-ai/DeepSeek-V3-0324" # Keep track if needed separately


# --- Nebius OpenAI Client Configuration ---
def get_nebius_client() -> OpenAI:
    """Initializes and returns the OpenAI client configured for Nebius."""
    api_key = os.getenv("NEBIUS_API_KEY")
    if not api_key:
        raise ValueError("NEBIUS_API_KEY not found in environment variables.")

    client = OpenAI(
        base_url="https://api.studio.nebius.com/v1/",
        api_key=api_key,
    )
    return client

# Initialize client globally or create on demand
# Global instance might be slightly more efficient if reused heavily
nebius_client = get_nebius_client()
