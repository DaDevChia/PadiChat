# handlers.py
import logging
import asyncio
# --- Add telegramify_markdown imports ---
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
SYSTEM_PROMPT = (
    "You are AgriSight Bot, a helpful AI assistant for Southeast Asian farmers. "
    "Keep your answers concise and focused, aiming for 2-4 paragraphs unless asked for more detail. "
    "Use standard Markdown formatting like **bold**, *italic*, `code`, [links](https://example.com), and bullet points (* item or - item). "
    "Structure information clearly."
)


# --- telegramify_markdown Configuration ---
# Allows more common Markdown variations if LLM produces them
customize.strict_markdown = False
# Optional: Makes long quotes expandable in Telegram
customize.cite_expandable = True
# Optional: Customize symbols if desired
# customize.markdown_symbol.head_level_1 = "📌"
# customize.markdown_symbol.link = "🔗"


# States and get_profiles remain the same
ASKING_LANGUAGE, ASKING_REGION = range(2)
def get_profiles(context: ContextTypes.DEFAULT_TYPE) -> dict:
    return context.bot_data.setdefault("user_profiles", {})


# --- UPDATED send_long_message using telegramify_markdown ---
async def send_long_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str):
    """Converts LLM Markdown using telegramify_markdown and sends, splitting if needed."""
    if not text:
        logger.warning(f"Attempted to send empty message to chat {chat_id}")
        await context.bot.send_message(chat_id=chat_id, text="...")
        return

    logger.debug("Original text from LLM:\n%s", text)
    try:
        # Convert the entire text using the library
        # This handles escaping needed for Telegram's MarkdownV2
        converted_text = telegramify_markdown.markdownify(text)
        logger.debug("Converted text via telegramify_markdown:\n%s", converted_text)
    except Exception as e:
        logger.error(f"Error during markdownify conversion for chat {chat_id}: {e}", exc_info=True)
        # Fallback: Try sending original text plain, truncated
        try:
            fallback_text = f"[Error converting response formatting]\n\n{text}"
            await context.bot.send_message(chat_id=chat_id, text=fallback_text[:TELEGRAM_MAX_MESSAGE_LENGTH])
        except Exception as fallback_e:
             logger.error(f"Fallback send failed after conversion error: {fallback_e}")
        return # Stop processing if conversion failed

    # Now split the *converted_text* if it's too long
    if len(converted_text) <= TELEGRAM_MAX_MESSAGE_LENGTH:
        try:
            # Send the converted text using MarkdownV2
            await context.bot.send_message(
                chat_id=chat_id,
                text=converted_text,
                parse_mode=ParseMode.MARKDOWN_V2
            )
        except Exception as e:
            logger.error(f"Error sending short converted message to chat {chat_id}: {e}", exc_info=True)
            # Fallback: Try sending original text plain
            try:
                 await context.bot.send_message(chat_id=chat_id, text=text)
            except Exception as fallback_e:
                 logger.error(f"Fallback send failed for short message: {fallback_e}")
                 await context.bot.send_message(chat_id=chat_id, text="Sorry, error sending response.")
    else:
        logger.info(f"Converted message for chat {chat_id} is too long ({len(converted_text)} chars). Splitting.")
        start = 0
        while start < len(converted_text):
            # Splitting logic operates on the converted_text
            end_limit = start + TELEGRAM_MAX_MESSAGE_LENGTH
            split_pos = converted_text.rfind('\n', start, end_limit)
            if split_pos <= start:
                split_pos = end_limit

            chunk = converted_text[start:min(split_pos, len(converted_text))]

            try:
                # Send the chunk, already formatted for MarkdownV2
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            except Exception as e:
                logger.error(f"Error sending converted chunk to chat {chat_id}: {e}", exc_info=True)
                # Fallback: Try sending the raw *original* text chunk? More complex.
                # Simplest fallback is to indicate an error for this part.
                try:
                    await context.bot.send_message(chat_id=chat_id, text="[Error sending part of the formatted response]")
                except Exception as fallback_e:
                     logger.error(f"Fallback error message send failed: {fallback_e}")
                break # Stop sending further chunks on error

            start = split_pos
            if start < len(converted_text) and converted_text[start] == '\n':
                 start += 1
            await asyncio.sleep(0.5) # Keep the delay

# --- Onboarding handlers (no changes needed) ---
# ... (start, ask_language_callback, ask_region, cancel_onboarding) ...
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    # ... (no changes needed) ...
    user = update.effective_user; chat_id = update.effective_chat.id; user_id = user.id
    profiles = get_profiles(context)
    if user_id not in profiles: update_user_profile(user_id, profiles, name=user.first_name)
    logger.info(f"User {user_id} ({user.first_name}) initiated /start in chat {chat_id}.")
    if is_onboarding_complete(user_id, profiles):
        profile = get_user_profile(user_id, profiles)
        await context.bot.send_message(chat_id=chat_id, text=f"Welcome back, {profile.get('name', 'friend')}! (Region: {profile.get('region', 'N/A')}, Lang: {profile.get('language', 'N/A')}). How can I help?")
        context.user_data.pop("chat_history_dicts", None)
        return ConversationHandler.END
    else: # Onboarding logic...
        logger.info(f"Starting onboarding for user {user_id}.")
        keyboard = [[InlineKeyboardButton("English 🇬🇧", callback_data='lang_en')], [InlineKeyboardButton("Bahasa Indonesia 🇮🇩", callback_data='lang_id')], [InlineKeyboardButton("Other", callback_data='lang_other')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(chat_id=chat_id, text=f"Hello {user.first_name}! Please select your language:", reply_markup=reply_markup)
        return ASKING_LANGUAGE

async def ask_language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (no changes needed) ...
    query = update.callback_query; await query.answer()
    user_id = query.from_user.id; chosen_lang_code = query.data.split('_')[1]
    profiles = get_profiles(context)
    lang_map = {"en": "English", "id": "Bahasa Indonesia", "other": "Other"}
    chosen_lang_name = lang_map.get(chosen_lang_code, "Selected")
    logger.info(f"User {user_id} selected language code: {chosen_lang_code}")
    if chosen_lang_code == "other":
         await query.edit_message_text(text="Thank you. Currently, only English supported. Proceeding in English.")
         update_user_profile(user_id, profiles, language='en')
    else:
        update_user_profile(user_id, profiles, language=chosen_lang_code)
        await query.edit_message_text(text=f"Great! You selected {chosen_lang_name}.")
    await context.bot.send_message(chat_id=query.message.chat_id, text="Next, please tell me your primary farming region/province.")
    return ASKING_REGION

async def ask_region(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (no changes needed) ...
    user_id = update.effective_user.id; chat_id = update.effective_chat.id
    region_text = update.message.text; profiles = get_profiles(context)
    logger.info(f"User {user_id} provided region: {region_text}")
    update_user_profile(user_id, profiles, region=region_text)
    await context.bot.send_message(chat_id=chat_id, text=f"Thanks! Region set to '{region_text}'. Onboarding complete! 🎉 How can I help?")
    context.user_data.pop("chat_history_dicts", None) # Clear history after onboarding
    return ConversationHandler.END

async def cancel_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
     # ... (no changes needed) ...
     user = update.effective_user; chat_id = update.effective_chat.id
     logger.info(f"User {user.id} cancelled onboarding.")
     await context.bot.send_message(chat_id=chat_id, text="Onboarding cancelled. Send /start to begin again.")
     return ConversationHandler.END

# --- handle_message (Loading indicator and System Prompt logic remains) ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles regular text messages AFTER onboarding, using the LangGraph agent."""
    user = update.effective_user; chat_id = update.effective_chat.id; user_id = user.id
    message_text = update.message.text; profiles = get_profiles(context)

    if not user_id in profiles or not is_onboarding_complete(user_id, profiles):
        logger.warning(f"Message from non-onboarded user {user_id}: '{message_text}'")
        await context.bot.send_message(chat_id=chat_id, text="Please use /start to complete setup.")
        return

    user_profile = get_user_profile(user_id, profiles)
    logger.info(f"Handling message from onboarded user {user_id} ({user_profile.get('name')}): '{message_text}'")

    # Send Typing Action
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # History loading with System Prompt prepended (remains the same logic)
    history_key = "chat_history_dicts"
    if history_key not in context.user_data:
        context.user_data[history_key] = [{"role": "system", "content": SYSTEM_PROMPT}]
        logger.info(f"Initialized history for user {user_id} with system prompt.")

    current_history_objects: List[BaseMessage] = []
    system_prompt_present = False
    for msg_dict in context.user_data[history_key]:
        role = msg_dict.get("role"); content = msg_dict.get("content", "")
        if role == "system":
             current_history_objects.append(SystemMessage(content=content))
             system_prompt_present = True
        elif role == "user": current_history_objects.append(HumanMessage(content=content))
        elif role == "assistant": current_history_objects.append(AIMessage(content=content, tool_calls=msg_dict.get("tool_calls", [])))
        elif role == "tool":
             tool_call_id = msg_dict.get("tool_call_id"); name = msg_dict.get("name")
             if tool_call_id: current_history_objects.append(ToolMessage(content=content, tool_call_id=tool_call_id, name=name))
             else: logger.warning(f"Skipping history item: ToolMessage dict missing tool_call_id: {msg_dict}")
        else: logger.warning(f"Skipping history item with unknown role: {msg_dict}")
    if not system_prompt_present:
         current_history_objects.insert(0, SystemMessage(content=SYSTEM_PROMPT))
         logger.warning(f"Re-added missing system prompt to history for user {user_id}")
    current_history_objects.append(HumanMessage(content=message_text))
    max_history_len = 10
    if len(current_history_objects) > max_history_len:
         current_history_objects = current_history_objects[:1] + current_history_objects[-max_history_len+1:]

    # Agent invocation logic (remains the same)
    agent_input_state = AgentState(messages=current_history_objects, user_id=user_id, user_profile=user_profile)
    response_text = None
    try:
        final_state = await agent_executor.ainvoke(agent_input_state)
        final_messages: List[BaseMessage] = final_state.get('messages', [])
        if final_messages:
             last_ai_message = final_messages[-1]
             if isinstance(last_ai_message, AIMessage):
                 response_text = last_ai_message.content
             else:
                 response_text = "Received an unexpected response structure."
                 logger.warning(f"Agent flow ended with non-AIMessage: {last_ai_message}")

             # Save history back as dictionaries (remains the same)
             context.user_data[history_key] = [
                 {"role": "system", "content": msg.content} if isinstance(msg, SystemMessage) else
                 {"role": "user", "content": msg.content} if isinstance(msg, HumanMessage) else
                 {"role": "assistant", "content": msg.content, "tool_calls": msg.tool_calls} if isinstance(msg, AIMessage) else
                 {"role": "tool", "content": msg.content, "tool_call_id": msg.tool_call_id, "name": msg.name} if isinstance(msg, ToolMessage) else
                 {}
                 for msg in final_messages
             ]
             context.user_data[history_key] = [d for d in context.user_data[history_key] if d]
        else:
            response_text = "Sorry, something went wrong and I couldn't get a response."
            logger.error(f"Agent invocation returned empty final state for user {user_id}")
    except Exception as e:
        logger.error(f"Error invoking LangGraph agent for user {user_id}: {e}", exc_info=True)
        response_text = f"Sorry, a critical error occurred ({type(e).__name__}). Please try again later."

    # Use the UPDATED helper function to send the response
    await send_long_message(context, chat_id, response_text)


# --- Error handler (no changes needed) ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Update {update} caused error {context.error}", exc_info=context.error)

# --- Onboarding conversation setup (no changes needed) ---
onboarding_conversation = ConversationHandler(
     entry_points=[CommandHandler('start', start)],
     states={
         ASKING_LANGUAGE: [CallbackQueryHandler(ask_language_callback, pattern='^lang_')],
         ASKING_REGION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_region)],
     },
     fallbacks=[CommandHandler('cancel', cancel_onboarding)],
)