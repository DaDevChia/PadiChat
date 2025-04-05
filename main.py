# main.py
import logging
import os
from dotenv import load_dotenv

# Persistence needed for user_data if bot restarts
from telegram.ext import Application, MessageHandler, filters, PicklePersistence

# Import handlers and profile functions
from user_profile import load_user_profiles, save_user_profiles # Need save for shutdown
from handlers import onboarding_conversation, handle_message, error_handler, settings_conversation, handle_photo

# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO # Set to DEBUG for more LangGraph/LLM details
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("langgraph").setLevel(logging.INFO) # Adjust LangGraph verbosity
logger = logging.getLogger(__name__)

# --- Persistence Setup ---
# Use PicklePersistence to save context.user_data and context.bot_data
# This saves chat history and loaded profiles across restarts.
persistence = PicklePersistence(filepath="bot_persistence.pkl")

# --- Main Bot Execution ---
def main() -> None:
    """Start the bot."""
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    api_key = os.getenv("NEBIUS_API_KEY") # Check if key loaded

    if not token:
        logger.critical("TELEGRAM_BOT_TOKEN not found in .env file! Exiting.")
        return
    if not api_key:
        logger.warning("NEBIUS_API_KEY not found in .env file! LLM calls will fail.")
        # Decide if you want to exit or run without LLM: return

    # Create the Application with persistence
    application = Application.builder().token(token).persistence(persistence).build()

    # --- Load Profiles into Bot Data (if not handled by persistence) ---
    # Persistence might handle loading bot_data automatically.
    # If starting fresh or persistence fails, load manually.
    if "user_profiles" not in application.bot_data:
        logger.info("Loading profiles manually into bot_data (persistence likely empty/new).")
        application.bot_data["user_profiles"] = load_user_profiles()
        logger.info(f"Loaded {len(application.bot_data['user_profiles'])} user profiles.")
    else:
         logger.info("User profiles found in persistent bot_data.")


    # --- Register Handlers ---
    application.add_handler(onboarding_conversation)
    application.add_handler(settings_conversation) # <-- Add the settings conversation
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo)) # <-- Add photo handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    # --- Start Bot ---
    logger.info("Starting bot polling...")
    application.run_polling()

    # --- Save Profiles on Shutdown (Optional but good practice) ---
    # Polling runs indefinitely, this might not be hit easily unless stopped gracefully.
    # Persistence handles saving, but manual save can be a backup.
    logger.info("Attempting to save profiles on shutdown...")
    save_user_profiles(application.bot_data.get("user_profiles", {}))


if __name__ == '__main__':
    main()