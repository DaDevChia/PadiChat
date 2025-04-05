# user_profile.py
import json
import logging
import os
from typing import Dict, Any, Optional
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# --- Constants ---
load_dotenv()
PROFILE_FILE = os.getenv("PROFILE_FILE")

# --- Profile Functions ---

def load_user_profiles() -> Dict[int, Dict[str, Any]]:
    """Loads user profiles from the JSON file."""
    if not os.path.exists(PROFILE_FILE):
        logger.warning(f"Profile file '{PROFILE_FILE}' not found. Starting with empty profiles.")
        return {}
    try:
        with open(PROFILE_FILE, 'r', encoding='utf-8') as f:
            # Ensure keys are integers after loading from JSON
            data = json.load(f)
            return {int(k): v for k, v in data.items()}
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from '{PROFILE_FILE}'. Starting with empty profiles.", exc_info=True)
        return {}
    except Exception as e:
        logger.error(f"Failed to load profiles from '{PROFILE_FILE}': {e}", exc_info=True)
        return {}

def save_user_profiles(profiles: Dict[int, Dict[str, Any]]) -> None:
    """Saves the current user profiles to the JSON file."""
    try:
        with open(PROFILE_FILE, 'w', encoding='utf-8') as f:
            json.dump(profiles, f, ensure_ascii=False, indent=4)
        # logger.info(f"User profiles saved to '{PROFILE_FILE}'.") # Log sparingly maybe
    except Exception as e:
        logger.error(f"Failed to save profiles to '{PROFILE_FILE}': {e}", exc_info=True)

def get_user_profile(user_id: int, profiles: Dict[int, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Gets a specific user's profile."""
    return profiles.get(user_id)

def update_user_profile(user_id: int, profiles: Dict[int, Dict[str, Any]], **kwargs) -> None:
    """Creates or updates a user's profile data."""
    if user_id not in profiles:
        profiles[user_id] = {}
    profiles[user_id].update(kwargs)
    logger.info(f"Updated profile for user {user_id}. New data: {kwargs}")
    # Save immediately after update for persistence
    save_user_profiles(profiles)

def is_onboarding_complete(user_id: int, profiles: Dict[int, Dict[str, Any]]) -> bool:
    """Checks if essential onboarding information (e.g., language, region) exists."""
    profile = profiles.get(user_id, {})
    # Define what constitutes "complete" onboarding for now
    return "language" in profile and "region" in profile