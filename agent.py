# agent.py
import json
import logging
from typing import TypedDict, List, Annotated, Sequence, Dict, Any, Optional, Literal
from operator import itemgetter
import openai

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, ToolMessage, HumanMessage, AIMessage, SystemMessage

from llm_interface import nebius_client, LLM_MODEL_NAME
from tools import available_tools_definitions, tool_executor_map

logger = logging.getLogger(__name__)

# AgentState definition remains the same
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_id: int
    user_profile: Dict[str, Any]


def call_llm(state: AgentState) -> Dict[str, Any]:
    """Calls the Nebius LLM with the current message history and available tools."""
    messages: Sequence[BaseMessage] = state['messages']
    user_profile = state.get('user_profile', {})
    logger.info(f"Calling LLM for user {state['user_id']} with {len(messages)} messages.")

    formatted_messages = []
    # --- Message formatting loop (kept mostly the same, relies on correct input types now) ---
    for msg in messages:
        if isinstance(msg, HumanMessage):
            formatted_messages.append({"role": "user", "content": msg.content or ""})
        elif isinstance(msg, AIMessage):
            # ... (AIMessage formatting logic as before) ...
            ai_msg_data = {"role": "assistant", "content": msg.content if msg.content is not None else None}
            if msg.tool_calls:
                 ai_msg_data["tool_calls"] = [ # Assuming tool_calls on AIMessage are list of dicts {'id':.. 'name':.. 'args':..}
                      { "id": tc.get("id"), "type": "function", "function": { "name": tc.get("name"), "arguments": json.dumps(tc.get("args", {})) }}
                      for tc in msg.tool_calls
                 ]
                 if ai_msg_data["content"] is None: del ai_msg_data["content"]
            elif ai_msg_data["content"] is None: ai_msg_data["content"] = ""
            if ai_msg_data.get("content") is not None or ai_msg_data.get("tool_calls"):
                 formatted_messages.append(ai_msg_data)
        elif isinstance(msg, ToolMessage):
            # ... (ToolMessage formatting logic as before) ...
            formatted_messages.append({ "role": "tool", "tool_call_id": msg.tool_call_id, "content": msg.content or "", "name": msg.name})
        elif isinstance(msg, SystemMessage):
             formatted_messages.append({"role": "system", "content": msg.content or ""})
        # NOTE: We now expect only correct types due to improved history handling in handlers.py
        else:
            logger.warning(f"Unexpected message type during formatting (should have been fixed in handler): {type(msg)}")

    valid_formatted_messages = [m for m in formatted_messages if m.get("role")]
    if not valid_formatted_messages:
         logger.error("No valid messages to send to LLM after formatting.")
         return {"messages": [AIMessage(content="Internal Error: No history to process.")]}

    logger.debug(f"Formatted messages being sent to LLM: {valid_formatted_messages}")

    try:
        # --- Temporarily REMOVE tools and tool_choice to isolate the 400 error ---
        # This allows testing basic chat functionality first.
        logger.info("Attempting LLM call WITHOUT tools/tool_choice for basic chat test.")
        response = nebius_client.chat.completions.create(
            model=LLM_MODEL_NAME,
            messages=valid_formatted_messages,
            # tools=available_tools_definitions, # <-- Temporarily disabled
            # tool_choice="auto",             # <-- Temporarily disabled
            temperature=0.6,
        )
        # --- End of temporary change ---

        message = response.choices[0].message
        response_tool_calls = [] # Will be empty since tools are disabled

        ai_message = AIMessage(
            content=message.content or "",
            tool_calls=response_tool_calls
        )
        return {"messages": [ai_message]}

    # --- FIX: Use the imported BadRequestError ---
    except openai.BadRequestError as e:
        logger.error(f"BadRequestError calling Nebius LLM: {e}", exc_info=True)
        error_detail = f"Details: {e.body.get('detail', 'Unknown')}" if hasattr(e, 'body') and isinstance(e.body, dict) else str(e)
        error_message = AIMessage(content=f"Sorry, there was an issue configuring the request for the AI model ({error_detail}).")
        return {"messages": [error_message]}
    except Exception as e:
        logger.error(f"Error calling Nebius LLM: {e}", exc_info=True)
        error_message = AIMessage(content=f"Sorry, I encountered an error trying to process your request ({type(e).__name__}). Please try again.")
        return {"messages": [error_message]}


# --- execute_tools function (Ensure args parsing is robust) ---

def execute_tools(state: AgentState) -> Dict[str, Any]:
    """Executes the tool calls requested by the LLM."""
    messages = state['messages']
    last_message = messages[-1]

    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        logger.warning("execute_tools called without tool calls in the last message.")
        return {}

    tool_messages = []
    # Remember: last_message.tool_calls here is now in Langchain's AIMessage format: list of dicts with 'id', 'name', 'args'
    for tool_call in last_message.tool_calls:
        tool_name = tool_call.get("name")
        tool_call_id = tool_call.get("id") # Get the ID for the response ToolMessage
        tool_args = tool_call.get("args", {}) # Args should already be a dict here

        if not tool_name or not tool_call_id:
             logger.error(f"Invalid tool call structure received from LLM: {tool_call}")
             # Create a ToolMessage indicating the error
             tool_messages.append(ToolMessage(content=f"Error: Invalid tool call structure from LLM.", tool_call_id=tool_call_id or "missing_id"))
             continue # Skip to the next tool call if any

        tool_to_execute = tool_executor_map.get(tool_name)

        if not tool_to_execute:
            logger.error(f"Tool '{tool_name}' requested by LLM is not available.")
            result_content = f"Error: Tool '{tool_name}' not found."
        else:
            try:
                logger.info(f"Executing tool '{tool_name}' with args: {tool_args}")
                # Execute the actual tool function (ensure args are passed correctly)
                tool_result = tool_to_execute(**tool_args) # Pydantic models in tools.py handle validation
                result_content = str(tool_result)
                logger.info(f"Tool '{tool_name}' executed successfully.")
            except Exception as e:
                # Catch errors during actual tool execution (e.g., API call failure)
                logger.error(f"Error executing tool '{tool_name}' implementation: {e}", exc_info=True)
                result_content = f"Error: Failed to execute tool '{tool_name}'. Reason: {type(e).__name__}."

        # Append a ToolMessage with the result
        tool_messages.append(ToolMessage(content=result_content, tool_call_id=tool_call_id, name=tool_name))

    return {"messages": tool_messages}


# --- should_continue function (remains the same) ---
def should_continue(state: AgentState) -> Literal["execute_tools", "__end__"]:
    """Determines the next step based on the last message."""
    last_message = state['messages'][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        logger.info("Routing: LLM requested tools -> execute_tools")
        return "execute_tools"
    else:
        logger.info("Routing: LLM provided final response -> __end__")
        return "__end__"

# --- build_agent_graph function (remains the same) ---
def build_agent_graph():
    graph = StateGraph(AgentState)
    graph.add_node("call_llm", call_llm)
    graph.add_node("execute_tools", execute_tools)
    graph.set_entry_point("call_llm")
    graph.add_conditional_edges(
        "call_llm",
        should_continue,
        {"execute_tools": "execute_tools", "__end__": END}
    )
    graph.add_edge("execute_tools", "call_llm")
    agent_executor = graph.compile()
    logger.info("LangGraph agent graph compiled.")
    return agent_executor

# --- Initialize Agent (keep as before) ---
agent_executor = build_agent_graph()