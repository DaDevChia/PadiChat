# agent.py
import json
import logging
import base64 # Import standard library
from typing import TypedDict, List, Annotated, Sequence, Dict, Any, Optional, Literal
from operator import itemgetter

from openai import BadRequestError
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, ToolMessage, HumanMessage, AIMessage, SystemMessage

from llm_interface import nebius_client, LLM_MODEL_NAME
from tools import available_tools_definitions, tool_executor_map

logger = logging.getLogger(__name__)

# --- UPDATED Agent State Definition ---
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_id: int
    user_profile: Dict[str, Any]
    image_base64: Optional[str] # <-- New field for image data

# --- Agent Nodes ---

# --- MODIFIED call_llm to handle images ---
def call_llm(state: AgentState) -> Dict[str, Any]:
    """Calls the Nebius LLM, handling potential image input."""
    messages: Sequence[BaseMessage] = state['messages']
    image_data_b64 = state.get('image_base64') # Get image data if present
    user_profile = state.get('user_profile', {})
    logger.info(f"Calling LLM for user {state['user_id']} with {len(messages)} messages. Image present: {'Yes' if image_data_b64 else 'No'}")

    formatted_messages = []
    last_human_message_index = -1

    for i, msg in enumerate(messages):
        if isinstance(msg, HumanMessage):
            # Store index of the last human message to potentially attach image to it
            last_human_message_index = i
            formatted_messages.append({"role": "user", "content": msg.content or ""})
        elif isinstance(msg, AIMessage):
            ai_msg_data = {"role": "assistant", "content": msg.content if msg.content is not None else None}
            if msg.tool_calls:
                 ai_msg_data["tool_calls"] = [ # Format tool calls...
                      { "id": tc.get("id"), "type": "function", "function": { "name": tc.get("name"), "arguments": json.dumps(tc.get("args", {})) }}
                      for tc in msg.tool_calls ]
                 if ai_msg_data["content"] is None: del ai_msg_data["content"]
            elif ai_msg_data["content"] is None: ai_msg_data["content"] = ""
            if ai_msg_data.get("content") is not None or ai_msg_data.get("tool_calls"): formatted_messages.append(ai_msg_data)
        elif isinstance(msg, ToolMessage):
            formatted_messages.append({ "role": "tool", "tool_call_id": msg.tool_call_id, "content": msg.content or "", "name": msg.name})
        elif isinstance(msg, SystemMessage):
             formatted_messages.append({"role": "system", "content": msg.content or ""})
        else:
            logger.warning(f"Unexpected message type during formatting: {type(msg)}")

    # --- Attach Image to the last Human message if image_data exists ---
    if image_data_b64 and last_human_message_index != -1:
        logger.info("Attaching image data to the last user message.")
        last_msg = formatted_messages[last_human_message_index]
        # Ensure content is a list for multimodal input
        if isinstance(last_msg["content"], str):
            last_msg["content"] = [{"type": "text", "text": last_msg["content"]}] # Convert text to list item
        elif not isinstance(last_msg["content"], list): # Handle unexpected content types
             logger.warning("Last user message content is not string or list, cannot attach image properly.")
             last_msg["content"] = [{"type": "text", "text": "Please describe the image."}] # Fallback text

        # Add the image part - assuming JPEG for now, adjust if needed
        last_msg["content"].append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{image_data_b64}"
            }
        })
    elif image_data_b64:
        # If no human message found (e.g., history only system prompt), send image with generic text
        logger.warning("Image data present but no preceding user message found. Sending image with generic prompt.")
        formatted_messages.append({
             "role": "user",
             "content": [
                  {"type": "text", "text": "Analyze this image."},
                  {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data_b64}"}}
             ]
        })


    valid_formatted_messages = [m for m in formatted_messages if m.get("role")]
    if not valid_formatted_messages:
         logger.error("No valid messages to send to LLM after formatting."); return {"messages": [AIMessage(content="Internal Error: No history.")]}

    logger.debug(f"Formatted messages being sent to LLM: {json.dumps(valid_formatted_messages, indent=2)}") # Pretty print debug

    try:
        # --- Call LLM (TOOLS STILL DISABLED for testing basic chat + vision) ---
        logger.info("Attempting LLM call (Vision possible).")
        response = nebius_client.chat.completions.create(
            model=LLM_MODEL_NAME, # Assuming this model supports vision
            messages=valid_formatted_messages,
            # tools=available_tools_definitions, # Keep disabled
            # tool_choice="auto",             # Keep disabled
            temperature=0.6,
        )

        message = response.choices[0].message
        response_tool_calls = [] # Keep empty

        ai_message = AIMessage(
            content=message.content or "",
            tool_calls=response_tool_calls
        )
        return {"messages": [ai_message]}

    except BadRequestError as e: # Handle specific errors
        logger.error(f"BadRequestError calling Nebius LLM: {e}", exc_info=True)
        error_detail = f"Details: {e.body.get('detail', 'Unknown')}" if hasattr(e, 'body') and isinstance(e.body, dict) else str(e)
        error_message = AIMessage(content=f"Sorry, model request error ({error_detail}).")
        return {"messages": [error_message]}
    except Exception as e:
        logger.error(f"Error calling Nebius LLM: {e}", exc_info=True)
        error_message = AIMessage(content=f"Sorry, error processing request ({type(e).__name__}).")
        return {"messages": [error_message]}


# --- execute_tools (remains the same, won't be called yet) ---
def execute_tools(state: AgentState) -> Dict[str, Any]:
    """Executes the tool calls requested by the LLM."""
    messages = state['messages']
    last_message = messages[-1]

    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        logger.warning("execute_tools called without tool calls in the last message.")
        return {}

# --- should_continue (remains the same) ---
def should_continue(state: AgentState) -> Literal["execute_tools", "__end__"]:
    """Determines the next step based on the last message."""
    last_message = state['messages'][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        logger.info("Routing: LLM requested tools -> execute_tools")
        return "execute_tools"
    else:
        logger.info("Routing: LLM provided final response -> __end__")
        return "__end__"

# --- build_agent_graph (remains the same) ---
def build_agent_graph():
    graph = StateGraph(AgentState)
    graph.add_node("call_llm", call_llm)
    graph.add_node("execute_tools", execute_tools)
    graph.set_entry_point("call_llm")
    graph.add_conditional_edges(
        "call_llm", should_continue, {"execute_tools": "execute_tools", "__end__": END}
    )
    graph.add_edge("execute_tools", "call_llm")
    agent_executor = graph.compile()
    logger.info("LangGraph agent graph compiled.")
    return agent_executor

# --- Initialize Agent (remains the same) ---
agent_executor = build_agent_graph()