# PadiChat: AI Farming Assistant for Telegram
<img src="https://github.com/user-attachments/assets/fd502c19-a9be-4515-b162-57a6b5d46398" width="150" height="150">

PadiChat is an intelligent Telegram bot designed to assist Southeast Asian farmers. It leverages AI language models (specifically configured for Nebius AI Studio) and agentic workflows (using LangGraph) to provide conversational support, analyze crop images for potential diseases (initial implementation), and offer personalized information based on user location and language preferences.

## Key Features

*   **Conversational AI:** Engage in natural language conversations powered by the Nebius AI LLM (`llm_interface.py`, `agent.py`).
*   **User Onboarding:** Guides new users through setting their preferred language, country, and state/province (`handlers.py` - `onboarding_conversation`).
*   **User Settings Management:** Allows existing users to update their preferences via the `/settings` command (`handlers.py` - `settings_conversation`).
*   **Image Analysis (Vision Capability):** Can receive photos (e.g., of crops) and analyze them using a vision-capable LLM to identify potential issues like diseases (`handlers.py` - `handle_photo`, `agent.py` - `call_llm` multimodal handling).
*   **Personalized Responses:** Tailors system prompts and potentially responses based on stored user profile data (language, location) (`handlers.py` - `SYSTEM_PROMPT_TEMPLATE`, `user_profile.py`).
*   **Tool Usage Ready:** Built with the capability to integrate and use external tools (like weather APIs), although currently disabled in the agent for basic chat/vision focus (`tools.py`, `agent.py` - `execute_tools` node).
*   **State Persistence:**
    *   Remembers user profiles (language, location) across restarts (`user_profile.py`, `user_profiles.json`).
    *   Maintains conversation history within sessions using Telegram's persistence (`main.py` - `PicklePersistence`, `bot_persistence.pkl`).
*   **Markdown Formatting:** Presents responses clearly using Telegram-compatible Markdown (`handlers.py` - `send_long_message`, `telegramify-markdown`).

## Technologies Used

*   Python 3.x
*   `python-telegram-bot`: Framework for interacting with the Telegram Bot API.
*   `LangGraph`: Library for building stateful, multi-actor AI applications (agents).
*   `Langchain` (Core): Utilized by LangGraph and for message types.
*   `openai` SDK: Used to interact with the OpenAI-compatible Nebius AI Studio API.
*   Nebius AI Studio: Provides the Large Language Model (`google/gemma-3-27b-it-fast` configured).
*   `python-dotenv`: For managing environment variables (API keys).
*   `telegramify-markdown`: For converting LLM Markdown output to Telegram's format.
*   `Pydantic`: Used for defining data schemas, particularly for tool parameters (`tools.py`).

## Project Structure

```
/
├── .env                 # Stores API keys (DO NOT COMMIT)
├── main.py              # Bot entry point, initialization, handler registration
├── handlers.py          # Defines Telegram command/message/callback handlers, conversation logic
├── agent.py             # Defines the LangGraph agent (state, nodes, workflow logic)
├── llm_interface.py     # Configures the Nebius AI (OpenAI SDK) client
├── tools.py             # Defines available tools, their schemas, and placeholder functions
├── user_profile.py      # Manages loading/saving/accessing user profile data
├── user_profiles.json   # Stores persistent user profile data (JSON)
├── bot_persistence.pkl  # Stores bot/user data via PicklePersistence (chat history, etc.)
├── requirements.txt     # Python package dependencies
└── venv/                # Python virtual environment (optional)
```

**File Roles:**

*   **`main.py`**: Initializes the bot application, sets up persistence, loads initial profiles, registers all handlers from `handlers.py`, and starts the bot.
*   **`handlers.py`**: Contains the core interaction logic. Defines `ConversationHandler`s for onboarding (`/start`) and settings (`/settings`), message handlers for text (`handle_message`) and photos (`handle_photo`), and callback handlers for buttons. It orchestrates calls to the agent via `_invoke_agent_and_respond` and formats/sends replies.
*   **`agent.py`**: Implements the LangGraph agent. Defines the `AgentState`, the `call_llm` node (which formats messages, includes images, calls Nebius), the `execute_tools` node (currently inactive), and the control flow logic (`should_continue`). Compiles the agent graph (`agent_executor`).
*   **`llm_interface.py`**: Sets up the connection to the Nebius AI Studio API using the `openai` library and API key. Defines the LLM model to use.
*   **`tools.py`**: Defines the structure (schemas) for tools the agent *could* use (e.g., `get_current_weather`) and provides placeholder implementation functions. The `available_tools_definitions` list is intended for the LLM.
*   **`user_profile.py`**: Handles reading from and writing to `user_profiles.json`, providing functions to get, update, and check the completion status of user profiles.
*   **`user_profiles.json`**: A JSON file storing persistent data for each user (ID, name, language, country, state/province).
*   **`bot_persistence.pkl`**: A binary file automatically managed by `python-telegram-bot`'s `PicklePersistence` to save conversation states and `context.user_data`/`context.bot_data` across bot restarts.

## Setup and Installation

1.  **Prerequisites:**
    *   Python 3.9+
    *   `pip` (Python package installer)
    *   Git (optional, for cloning)

2.  **Clone the Repository:**
    ```bash
    git clone https://github.com/DaDevChia/PadiChat
    cd PadiChat
    ```

3.  **Create a Virtual Environment (Recommended):**
    ```bash
    python -m venv venv
    # Activate the environment:
    # Windows:
    .\venv\Scripts\activate
    # macOS/Linux:
    source venv/bin/activate
    ```

4.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

5.  **Configure Environment Variables:**
    *   Create a file named `.env` in the root project directory.
    *   Add your API keys to this file:
        ```dotenv
        TELEGRAM_BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
        NEBIUS_API_KEY="YOUR_NEBIUS_API_KEY"
        ```
    *   **Get Keys:**
        *   `TELEGRAM_BOT_TOKEN`: Obtain this from Telegram's BotFather.
        *   `NEBIUS_API_KEY`: Obtain this from your Nebius AI Studio account/dashboard.
    *   **Security:** Ensure the `.env` file is added to your `.gitignore` file to prevent accidentally committing secrets.

## Running the Bot

1.  Make sure your virtual environment is activated.
2.  Ensure the `.env` file is correctly configured with your API keys.
3.  Run the main script:
    ```bash
    python main.py
    ```
4.  The bot should start polling for updates. Check the console output for logs and potential errors.

## Usage

1.  Find your bot on Telegram (using the username you set up with BotFather).
2.  **Start:** Send the `/start` command.
    *   If you are a new user, the bot will guide you through the onboarding process (selecting language, country, and state/province).
    *   If you have already completed onboarding, it will greet you.
3.  **Conversation:** Send text messages to chat with the AI.
4.  **Image Analysis:** Send a photo (e.g., of a potentially diseased crop). You can add a caption to provide context, or the bot will use a default prompt.
5.  **Settings:** Send the `/settings` command to view your current preferences and get options to change language, country, or state/province.
6.  **Cancel:** During the multi-step onboarding or settings processes, you can send `/cancel` to exit the flow.

## How it Works (Workflow Overview)

1.  **User Interaction:** User sends a message, command, photo, or callback query to the bot via Telegram.
2.  **Handler Trigger:** `python-telegram-bot` routes the update to the appropriate handler function in `handlers.py`.
3.  **Onboarding/Settings Flow:** If the user is in an onboarding or settings conversation (`ConversationHandler`), the corresponding state function is executed. User profile data is updated in `user_profiles.json` via `user_profile.py`.
4.  **Regular Message/Photo:**
    *   `handle_message` or `handle_photo` is triggered.
    *   The `_invoke_agent_and_respond` helper function is called.
    *   It retrieves the user's profile (`user_profile.py`).
    *   It loads chat history (from `context.user_data` managed by `PicklePersistence`).
    *   It constructs a dynamic system prompt based on the user's profile.
    *   If a photo was sent, it's downloaded and encoded into base64.
    *   It prepares the `AgentState` including messages, profile info, and image data.
5.  **Agent Invocation:** The `agent_executor.ainvoke()` method from `agent.py` is called with the prepared state.
6.  **LLM Call (`agent.py`):**
    *   The `call_llm` node formats the message history into the structure expected by the Nebius API.
    *   Crucially, if `image_base64` is present in the state, it modifies the last user message to include the image data (multimodal input).
    *   It calls the Nebius `chat.completions.create` endpoint via the client configured in `llm_interface.py`. (Tool usage is currently disabled here).
7.  **Tool Execution (Future/Disabled):** The `should_continue` node would route to `execute_tools` if the LLM requested a tool. `execute_tools` would look up the function in `tools.py` and run it, returning the result to `call_llm`.
8.  **Response Processing:** The LLM's final text response is extracted from the agent's final state.
9.  **History Update:** The updated conversation history (including the AI's response) is saved back into `context.user_data`.
10. **Send Reply:** `_invoke_agent_and_respond` calls `send_long_message` in `handlers.py`.
11. **Formatting & Sending:** `send_long_message` converts the LLM's Markdown response using `telegramify-markdown` and sends it back to the user via Telegram, splitting long messages if necessary.
