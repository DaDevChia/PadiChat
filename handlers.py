# handlers.py
import logging
import asyncio
from typing import List
import telegramify_markdown
from telegramify_markdown import customize

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, ToolMessage, SystemMessage

from user_profile import get_user_profile, update_user_profile, is_onboarding_complete
from agent import agent_executor, AgentState

logger = logging.getLogger(__name__)

# Constants
TELEGRAM_MAX_MESSAGE_LENGTH = 4096
# --- MODIFIED System Prompt Template ---
SYSTEM_PROMPT_TEMPLATE = (
    "You are AgriSight Bot, a helpful AI assistant for Southeast Asian farmers. "
    "The user is located in {state_province}, {country}. "
    "You MUST respond ONLY in {language_name}. Do not use any other language. " # <-- More direct language instruction
    "Keep your answers concise and focused (2-4 paragraphs unless asked for more). "
    "Use standard Markdown formatting: **bold**, *italic*, `code`, [links](https://example.com), and bullet points (* item or - item). "
    "Structure information clearly."
)

# --- Language Code to Full Name Mapping (for prompt) ---
LANG_CODE_TO_NAME = {
    "en": "English",
    "id": "Bahasa Indonesia",
    "vi": "Vietnamese",
    "th": "Thai",
    "tl": "Tagalog",
    # Add others as needed
}

# telegramify_markdown Configuration (remains the same)
customize.strict_markdown = False
customize.cite_expandable = True

# --- Onboarding Conversation States ---
# (Keep previous names for clarity within onboarding)
ONBOARD_LANG, ONBOARD_COUNTRY, ONBOARD_STATE = range(3)

# --- NEW Settings Conversation States ---
SELECT_SETTING, CHANGE_LANG, CHANGE_COUNTRY, CHANGE_STATE = range(10, 14) # Use different range


# Helper Function (remains the same)
def get_profiles(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.bot_data.setdefault("user_profiles", {})

# send_long_message function (remains the same)
async def send_long_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str):
    """Converts LLM Markdown and sends, splitting if needed."""
    # ... (previous implementation is fine) ...
    if not text: logger.warning(f"Attempted to send empty message to chat {chat_id}"); await context.bot.send_message(chat_id=chat_id, text="..."); return
    logger.debug("Original text from LLM:\n%s", text)
    try: converted_text = telegramify_markdown.markdownify(text); logger.debug("Converted text:\n%s", converted_text)
    except Exception as e: logger.error(f"Markdownify conversion error: {e}", exc_info=True); await context.bot.send_message(chat_id=chat_id, text=f"[Formatting Error]\n\n{text[:1000]}..."); return
    if len(converted_text) <= TELEGRAM_MAX_MESSAGE_LENGTH:
        try: await context.bot.send_message(chat_id=chat_id, text=converted_text, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as e: logger.error(f"Error sending short converted msg: {e}", exc_info=True); await context.bot.send_message(chat_id=chat_id, text=text) # Fallback plain
    else:
        logger.info(f"Converted message too long ({len(converted_text)} chars). Splitting."); start = 0
        while start < len(converted_text):
            end_limit = start + TELEGRAM_MAX_MESSAGE_LENGTH; split_pos = converted_text.rfind('\n', start, end_limit)
            if split_pos <= start: split_pos = end_limit
            chunk = converted_text[start:min(split_pos, len(converted_text))]
            try: await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception as e: logger.error(f"Error sending converted chunk: {e}", exc_info=True); await context.bot.send_message(chat_id=chat_id, text="[Error sending part]"); break
            start = split_pos
            if start < len(converted_text) and converted_text[start] == '\n': start += 1
            await asyncio.sleep(0.5)

# --- Helper Function for Language Keyboard ---
def get_language_keyboard(callback_prefix: str = "lang_") -> InlineKeyboardMarkup:
    """Generates the language selection keyboard."""
    keyboard = [
        [InlineKeyboardButton("English 🇬🇧", callback_data=f'{callback_prefix}en')],
        [InlineKeyboardButton("Bahasa Indonesia 🇮🇩", callback_data=f'{callback_prefix}id')],
        [InlineKeyboardButton("Tiếng Việt 🇻🇳", callback_data=f'{callback_prefix}vi')],
        [InlineKeyboardButton("ภาษาไทย 🇹🇭", callback_data=f'{callback_prefix}th')],
        [InlineKeyboardButton("Tagalog 🇵🇭", callback_data=f'{callback_prefix}tl')],
        [InlineKeyboardButton("Other (Defaults to English)", callback_data=f'{callback_prefix}other')],
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Helper Function for Country Keyboard ---
def get_country_keyboard(callback_prefix: str = "country_") -> InlineKeyboardMarkup:
    """Generates the country selection keyboard."""
    countries = [
        ("Indonesia 🇮🇩", "ID"), ("Malaysia 🇲🇾", "MY"), ("Philippines 🇵🇭", "PH"),
        ("Singapore 🇸🇬", "SG"), ("Thailand 🇹🇭", "TH"), ("Vietnam 🇻🇳", "VN"),
        ("Other", "OTHER") ]
    keyboard = []; row = []
    for name, code in countries:
        row.append(InlineKeyboardButton(name, callback_data=f'{callback_prefix}{code}'))
        if len(row) == 2: keyboard.append(row); row = []
    if row: keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)


# --- Onboarding Handlers (using ONBOARD_ states) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    user = update.effective_user; chat_id = update.effective_chat.id; user_id = user.id
    profiles = get_profiles(context)
    if user_id not in profiles: update_user_profile(user_id, profiles, name=user.first_name)
    logger.info(f"/start command from user {user_id}")

    if is_onboarding_complete(user_id, profiles):
        profile = get_user_profile(user_id, profiles)
        await context.bot.send_message(chat_id=chat_id, text=f"Welcome back, {profile.get('name')}! (Loc: {profile.get('state_province')}, {profile.get('country')}. Lang: {profile.get('language')}). Send /settings to change preferences.")
        context.user_data.pop("chat_history_dicts", None)
        return ConversationHandler.END
    else:
        logger.info(f"Starting/Resuming onboarding for user {user_id}.")
        await context.bot.send_message(chat_id=chat_id, text=f"Hello {user.first_name}! Let's set up your preferences. Select your language:", reply_markup=get_language_keyboard("onboard_lang_")) # Use prefix
        return ONBOARD_LANG # Use onboarding state

async def onboard_ask_language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    user_id = query.from_user.id; chosen_lang_code = query.data.split('_')[-1] # Get code
    profiles = get_profiles(context)
    chosen_lang_name = LANG_CODE_TO_NAME.get(chosen_lang_code, "Other")
    logger.info(f"Onboarding: User {user_id} selected lang code: {chosen_lang_code}")

    if chosen_lang_code == "other":
         await query.edit_message_text(text="Using English as default.")
         update_user_profile(user_id, profiles, language='en')
    else:
        update_user_profile(user_id, profiles, language=chosen_lang_code)
        await query.edit_message_text(text=f"Language set to {chosen_lang_name}.")

    await context.bot.send_message(chat_id=query.message.chat_id, text="Now, select your country:", reply_markup=get_country_keyboard("onboard_country_")) # Use prefix
    return ONBOARD_COUNTRY

async def onboard_ask_country_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    user_id = query.from_user.id; chosen_country_code = query.data.split('_')[-1]
    profiles = get_profiles(context)
    country_map = {"ID": "Indonesia", "MY": "Malaysia", "PH": "Philippines", "SG": "Singapore", "TH": "Thailand", "VN": "Vietnam", "OTHER": "Other"}
    chosen_country_name = country_map.get(chosen_country_code, "Other")
    logger.info(f"Onboarding: User {user_id} selected country: {chosen_country_name}")

    update_user_profile(user_id, profiles, country=chosen_country_name)
    await query.edit_message_text(text=f"Country set to {chosen_country_name}.")
    await context.bot.send_message(chat_id=query.message.chat_id, text="Finally, please type your state or province name:")
    return ONBOARD_STATE

async def onboard_ask_state_province(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id; chat_id = update.effective_chat.id
    state_province_text = update.message.text; profiles = get_profiles(context)
    logger.info(f"Onboarding: User {user_id} provided state/province: {state_province_text}")
    update_user_profile(user_id, profiles, state_province=state_province_text)
    profile = get_user_profile(user_id, profiles)
    await context.bot.send_message(chat_id=chat_id, text=f"Setup complete! Location: {profile.get('state_province')}, {profile.get('country')}. Language: {profile.get('language')}.\n\nHow can I help?")
    context.user_data.pop("chat_history_dicts", None)
    return ConversationHandler.END

async def onboard_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
     logger.info(f"User {update.effective_user.id} cancelled onboarding.")
     await context.bot.send_message(chat_id=update.effective_chat.id, text="Onboarding cancelled. Send /start to try again.")
     return ConversationHandler.END


# --- NEW Settings Conversation Handlers (using SELECT_SETTING states) ---

async def settings_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the settings change conversation."""
    user = update.effective_user
    profiles = get_profiles(context)

    # Ensure user is onboarded first
    if not is_onboarding_complete(user.id, profiles):
        await update.message.reply_text("Please complete the initial setup using /start before changing settings.")
        return ConversationHandler.END

    profile = get_user_profile(user.id, profiles)
    current_settings_text = (
        f"Current Settings:\n"
        f"- Language: {LANG_CODE_TO_NAME.get(profile.get('language', 'N/A'), 'N/A')}\n"
        f"- Country: {profile.get('country', 'N/A')}\n"
        f"- State/Province: {profile.get('state_province', 'N/A')}\n\n"
        "What would you like to change?"
    )

    keyboard = [
        [InlineKeyboardButton("Change Language", callback_data='setting_change_lang')],
        [InlineKeyboardButton("Change Country", callback_data='setting_change_country')],
        [InlineKeyboardButton("Change State/Province", callback_data='setting_change_state')],
        [InlineKeyboardButton("Cancel", callback_data='setting_cancel')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(current_settings_text, reply_markup=reply_markup)
    return SELECT_SETTING

async def settings_select_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles button presses from the main settings menu."""
    query = update.callback_query
    await query.answer()
    action = query.data # e.g., 'setting_change_lang'

    if action == 'setting_change_lang':
        await query.edit_message_text("Please select your new preferred language:", reply_markup=get_language_keyboard("setting_select_lang_")) # Use settings prefix
        return CHANGE_LANG
    elif action == 'setting_change_country':
        await query.edit_message_text("Please select your new country:", reply_markup=get_country_keyboard("setting_select_country_")) # Use settings prefix
        return CHANGE_COUNTRY
    elif action == 'setting_change_state':
        await query.edit_message_text("Please type your new state or province name:")
        return CHANGE_STATE
    elif action == 'setting_cancel':
        await query.edit_message_text("Settings change cancelled.")
        return ConversationHandler.END
    else:
        await query.edit_message_text("Invalid selection. Settings change cancelled.")
        return ConversationHandler.END

async def settings_receive_language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles new language selection."""
    query = update.callback_query; await query.answer()
    user_id = query.from_user.id; chosen_lang_code = query.data.split('_')[-1]
    profiles = get_profiles(context)
    chosen_lang_name = LANG_CODE_TO_NAME.get(chosen_lang_code, "Other")
    logger.info(f"Settings: User {user_id} changed lang code to: {chosen_lang_code}")

    lang_to_save = 'en' if chosen_lang_code == "other" else chosen_lang_code
    update_user_profile(user_id, profiles, language=lang_to_save)

    await query.edit_message_text(f"Language updated to {chosen_lang_name}.\nUse /settings again for more changes.")
    context.user_data.pop("chat_history_dicts", None) # Clear history as context changed
    return ConversationHandler.END

async def settings_receive_country_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles new country selection and prompts for state/province."""
    query = update.callback_query; await query.answer()
    user_id = query.from_user.id; chosen_country_code = query.data.split('_')[-1]
    profiles = get_profiles(context)
    country_map = {"ID": "Indonesia", "MY": "Malaysia", "PH": "Philippines", "SG": "Singapore", "TH": "Thailand", "VN": "Vietnam", "OTHER": "Other"}
    chosen_country_name = country_map.get(chosen_country_code, "Other")
    logger.info(f"Settings: User {user_id} changed country to: {chosen_country_name}")

    update_user_profile(user_id, profiles, country=chosen_country_name)

    # Clear old state/province since country changed
    update_user_profile(user_id, profiles, state_province=None) # Or delete key

    await query.edit_message_text(f"Country updated to {chosen_country_name}.\nNow, please type your new state or province name:")
    return CHANGE_STATE # Go directly to asking for the state

async def settings_receive_state(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the text input for the new state/province."""
    user_id = update.effective_user.id; chat_id = update.effective_chat.id
    state_province_text = update.message.text; profiles = get_profiles(context)
    logger.info(f"Settings: User {user_id} changed state/province to: {state_province_text}")

    update_user_profile(user_id, profiles, state_province=state_province_text)

    await context.bot.send_message(chat_id=chat_id, text=f"State/Province updated to '{state_province_text}'.\nSettings updated successfully! Use /settings again for more changes.")
    context.user_data.pop("chat_history_dicts", None) # Clear history as context changed
    return ConversationHandler.END

async def settings_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the settings change conversation."""
    # Check if called via callback query or command
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Settings change cancelled.")
    elif update.message:
        await update.message.reply_text("Settings change cancelled.")
    logger.info(f"User {update.effective_user.id} cancelled settings change.")
    return ConversationHandler.END


# --- Regular Message Handler (Using DYNAMIC system prompt) ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles regular text messages AFTER onboarding, using the LangGraph agent with dynamic context."""
    user = update.effective_user; chat_id = update.effective_chat.id; user_id = user.id
    message_text = update.message.text; profiles = get_profiles(context)

    if not user_id in profiles or not is_onboarding_complete(user_id, profiles):
        logger.warning(f"Message from non-onboarded user {user_id}: '{message_text}'")
        await context.bot.send_message(chat_id=chat_id, text="Please use /start to complete setup.")
        return

    user_profile = get_user_profile(user_id, profiles)
    logger.info(f"Handling message from onboarded user {user_id} ({user_profile.get('name')}): '{message_text}'")
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # Construct Dynamic System Prompt
    user_lang_code = user_profile.get('language', 'en')
    user_lang_name = LANG_CODE_TO_NAME.get(user_lang_code, 'English') # Get full name for prompt
    user_country = user_profile.get('country', 'Southeast Asia')
    user_state = user_profile.get('state_province', 'unspecified region')
    dynamic_system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        state_province=user_state, country=user_country, language_name=user_lang_name # Use name
    )
    logger.debug(f"Using dynamic system prompt for user {user_id}: {dynamic_system_prompt}")

    # History loading/reconstruction using the DYNAMIC prompt (remains the same logic)
    history_key = "chat_history_dicts"
    current_history_objects: List[BaseMessage] = []
    if history_key in context.user_data:
        system_prompt_found_and_updated = False
        for msg_dict in context.user_data[history_key]:
            role = msg_dict.get("role"); content = msg_dict.get("content", "")
            if role == "system":
                 current_history_objects.append(SystemMessage(content=dynamic_system_prompt)); system_prompt_found_and_updated = True
            elif role == "user": current_history_objects.append(HumanMessage(content=content))
            elif role == "assistant": current_history_objects.append(AIMessage(content=content, tool_calls=msg_dict.get("tool_calls", [])))
            elif role == "tool":
                 tool_call_id = msg_dict.get("tool_call_id"); name = msg_dict.get("name")
                 if tool_call_id: current_history_objects.append(ToolMessage(content=content, tool_call_id=tool_call_id, name=name))
                 else: logger.warning(f"Skipping ToolMessage dict missing tool_call_id: {msg_dict}")
            else: logger.warning(f"Skipping history item with unknown role: {msg_dict}")
        if not system_prompt_found_and_updated:
             current_history_objects.insert(0, SystemMessage(content=dynamic_system_prompt)); logger.info(f"Prepended dynamic system prompt for {user_id}")
    else: current_history_objects.append(SystemMessage(content=dynamic_system_prompt)); logger.info(f"Initialized history for {user_id} with dynamic prompt.")
    current_history_objects.append(HumanMessage(content=message_text))
    max_history_len = 10
    if len(current_history_objects) > max_history_len: current_history_objects = current_history_objects[:1] + current_history_objects[-max_history_len+1:]

    # Agent invocation (remains the same - TOOLS STILL DISABLED IN agent.py)
    agent_input_state = AgentState(messages=current_history_objects, user_id=user_id, user_profile=user_profile)
    response_text = None
    try:
        final_state = await agent_executor.ainvoke(agent_input_state)
        final_messages: List[BaseMessage] = final_state.get('messages', [])
        if final_messages:
             last_ai_message = final_messages[-1]
             if isinstance(last_ai_message, AIMessage): response_text = last_ai_message.content
             else: response_text = "Unexpected response."; logger.warning(f"Agent ended non-AIMessage: {last_ai_message}")
             # Save history back as dictionaries (remains the same)
             context.user_data[history_key] = [ # Save logic...
                 {"role": "system", "content": msg.content} if isinstance(msg, SystemMessage) else
                 {"role": "user", "content": msg.content} if isinstance(msg, HumanMessage) else
                 {"role": "assistant", "content": msg.content, "tool_calls": msg.tool_calls} if isinstance(msg, AIMessage) else
                 {"role": "tool", "content": msg.content, "tool_call_id": msg.tool_call_id, "name": msg.name} if isinstance(msg, ToolMessage) else {}
                 for msg in final_messages ]
             context.user_data[history_key] = [d for d in context.user_data[history_key] if d]
        else: response_text = "Couldn't get response."; logger.error(f"Agent returned empty state for {user_id}")
    except Exception as e: logger.error(f"Error invoking agent for {user_id}: {e}", exc_info=True); response_text = f"Critical error ({type(e).__name__})."

    await send_long_message(context, chat_id, response_text)


# Error handler remains the same
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Update {update} caused error {context.error}", exc_info=context.error)

# --- Onboarding Conversation Handler Definition (using ONBOARD_ states) ---
onboarding_conversation = ConversationHandler(
    entry_points=[CommandHandler('start', start)],
    states={
        ONBOARD_LANG: [CallbackQueryHandler(onboard_ask_language_callback, pattern='^onboard_lang_')],
        ONBOARD_COUNTRY: [CallbackQueryHandler(onboard_ask_country_callback, pattern='^onboard_country_')],
        ONBOARD_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_ask_state_province)],
    },
    fallbacks=[CommandHandler('cancel', onboard_cancel)],
    name="onboarding_flow", # Give names for potential persistence differentiation
    # persistent=True, # Optional persistence for onboarding state
)

# --- NEW Settings Conversation Handler Definition ---
settings_conversation = ConversationHandler(
    entry_points=[CommandHandler('settings', settings_start)],
    states={
        SELECT_SETTING: [CallbackQueryHandler(settings_select_action_callback, pattern='^setting_change_|^setting_cancel$')],
        CHANGE_LANG: [CallbackQueryHandler(settings_receive_language_callback, pattern='^setting_select_lang_')],
        CHANGE_COUNTRY: [CallbackQueryHandler(settings_receive_country_callback, pattern='^setting_select_country_')],
        CHANGE_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, settings_receive_state)],
    },
    fallbacks=[CommandHandler('cancel', settings_cancel), CallbackQueryHandler(settings_cancel, pattern='^setting_cancel$')],
     name="settings_flow",
     # persistent=True, # Optional
)