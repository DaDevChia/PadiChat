# agent.py
import json
import logging
import base64
from typing import TypedDict, List, Annotated, Sequence, Dict, Any, Optional, Literal
from operator import itemgetter
import asyncio

from openai import BadRequestError
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, ToolMessage, HumanMessage, AIMessage, SystemMessage

# Import Nebius client and SPECIFIC model names
from llm_interface import nebius_client, TEXT_TOOL_MODEL_NAME, VISION_MODEL_NAME
from tools import available_tools_definitions, tool_executor_map

logger = logging.getLogger(__name__)

# --- Agent State Definition ---
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_id: int
    user_profile: Dict[str, Any]
    image_base64: Optional[str]

# --- Agent Nodes ---
# --- call_llm to select model and enable/disable tools ---
async def call_llm(state: AgentState) -> Dict[str, Any]:
    """
    Calls the appropriate Nebius LLM (Text/Tool or Vision) based on input
    and enables tools only for the text/tool model.
    """
    messages: Sequence[BaseMessage] = state['messages']
    image_data_b64 = state.get('image_base64')
    user_profile = state.get('user_profile', {})

    # --- Model and Tool Configuration based on Image Presence ---
    if image_data_b64:
        model_to_use = VISION_MODEL_NAME
        tools_to_pass = None  # Gemma doesn't support tools
        tool_choice_to_pass = None # Don't specify tool choice for vision model
        logger.info(f"Image detected for user {state['user_id']}. Using VISION model: {model_to_use}. Tools DISABLED.")
    else:
        model_to_use = TEXT_TOOL_MODEL_NAME
        tools_to_pass = available_tools_definitions # Pass tool definitions to Llama
        tool_choice_to_pass = "auto" # Let Llama decide if tools are needed
        logger.info(f"No image detected for user {state['user_id']}. Using TEXT/TOOL model: {model_to_use}. Tools ENABLED.")

    logger.info(f"Calling LLM for user {state['user_id']} with {len(messages)} messages.")

    # --- Message Formatting Logic ---
    # This logic correctly formats messages with or without images,
    # and with or without tool calls/results in history.
    formatted_messages = []
    last_human_message_index = -1
    for i, msg in enumerate(messages):
        if isinstance(msg, HumanMessage):
            last_human_message_index = i
            # For vision model, content might be modified later if image exists
            formatted_messages.append({"role": "user", "content": msg.content or ""})
        elif isinstance(msg, AIMessage):
            ai_msg_data = {"role": "assistant", "content": msg.content if msg.content is not None else None}
            if msg.tool_calls:
                 api_tool_calls = [
                      {
                           "id": tc.get("id"),
                           "type": "function",
                           "function": {
                                "name": tc.get("name"),
                                "arguments": json.dumps(tc.get("args", {})) if isinstance(tc.get("args"), dict) else tc.get("args", "{}")
                           }
                      } for tc in msg.tool_calls ]
                 ai_msg_data["tool_calls"] = api_tool_calls
                 if ai_msg_data["content"] is None: del ai_msg_data["content"]
            elif ai_msg_data["content"] is None: ai_msg_data["content"] = ""
            if ai_msg_data.get("content") is not None or ai_msg_data.get("tool_calls"): formatted_messages.append(ai_msg_data)
        elif isinstance(msg, ToolMessage):
            formatted_messages.append({ "role": "tool", "tool_call_id": msg.tool_call_id, "content": msg.content or "", "name": msg.name })
        elif isinstance(msg, SystemMessage):
             formatted_messages.append({"role": "system", "content": msg.content or ""})
        else: logger.warning(f"Unexpected message type during formatting: {type(msg)}")

    # --- Image Attachment Logic (applies ONLY if image_data_b64 is present) ---
    if image_data_b64 and last_human_message_index != -1:
        logger.debug("Attaching image data to the last user message for VISION model.")
        last_msg = formatted_messages[last_human_message_index]
        # Ensure content is list for multimodal
        if isinstance(last_msg["content"], str): last_msg["content"] = [{"type": "text", "text": last_msg["content"]}]
        elif not isinstance(last_msg["content"], list): last_msg["content"] = [{"type": "text", "text": "Please describe the image."}]
        # Append image part
        last_msg["content"].append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data_b64}"}})
    elif image_data_b64: # Image present, but no human message (e.g., only system prompt)
         logger.warning("Image data present but no preceding user message found. Sending image with generic prompt for VISION model.")
         formatted_messages.append({"role": "user", "content": [{"type": "text", "text": "Analyze this image."}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data_b64}"}}]})

    # --- Final Checks and API Call ---
    valid_formatted_messages = [m for m in formatted_messages if m.get("role")]
    if not valid_formatted_messages:
        logger.error("No valid messages to send to LLM after formatting.");
        return {"messages": [AIMessage(content="Internal Error: No history.")]}

    logger.debug(f"Formatted messages being sent to {model_to_use}:\n{json.dumps(valid_formatted_messages, indent=2)}")

    try:
        logger.info(f"Attempting API call to model: {model_to_use}")
        api_call_params = {
            "model": model_to_use,
            "messages": valid_formatted_messages,
            "temperature": 0.6,
        }
        # Conditionally add tool parameters ONLY if calling the text/tool model
        if model_to_use == TEXT_TOOL_MODEL_NAME and tools_to_pass:
             api_call_params["tools"] = tools_to_pass
             api_call_params["tool_choice"] = tool_choice_to_pass
             logger.debug("Tool parameters included in API call.")
        else:
             logger.debug("Tool parameters excluded for VISION model API call.")


        response = await nebius_client.chat.completions.create(**api_call_params) # Use await

        message = response.choices[0].message

        # --- Parse tool calls (will only be present if Llama model was called and decided to use tools) ---
        response_tool_calls = []
        if message.tool_calls:
            logger.info(f"LLM response from {model_to_use} includes {len(message.tool_calls)} tool call(s).")
            for tool_call in message.tool_calls:
                try:
                    args_dict = json.loads(tool_call.function.arguments)
                    response_tool_calls.append({ "id": tool_call.id, "name": tool_call.function.name, "args": args_dict })
                except json.JSONDecodeError: logger.error(f"Failed to parse JSON arguments for tool call {tool_call.id}", exc_info=True)
                except Exception as e: logger.error(f"Unexpected error processing tool call {tool_call.id}: {e}", exc_info=True)
        elif model_to_use == TEXT_TOOL_MODEL_NAME:
             logger.info(f"LLM response from {model_to_use} has no tool calls.")

        ai_message_content = message.content if message.content is not None else ""

        # Now create the AIMessage instance
        ai_message = AIMessage(
            content=ai_message_content, # This will now be a string (or list if vision model returned structured content)
            tool_calls=response_tool_calls
        )

        logger.debug(f"LLM ({model_to_use}) response parsed into AIMessage: {ai_message}")
        return {"messages": [ai_message]}

    except BadRequestError as e: # Handle specific errors more gracefully
        logger.error(f"BadRequestError calling Nebius LLM ({model_to_use}): {e}", exc_info=True)
        error_detail = f"Details: {e.body.get('detail', 'Unknown')}" if hasattr(e, 'body') and isinstance(e.body, dict) else str(e)
        # Provide more context in the error message
        error_content = f"Sorry, there was an error communicating with the AI model ({model_to_use}). Details: {error_detail}. Please try again or rephrase."
        error_message = AIMessage(content=error_content)
        return {"messages": [error_message]}
    except Exception as e:
        logger.error(f"Error calling Nebius LLM ({model_to_use}): {e}", exc_info=True)
        error_message = AIMessage(content=f"Sorry, an unexpected error occurred while processing your request with model {model_to_use} ({type(e).__name__}).")
        return {"messages": [error_message]}


# --- execute_tools ---
# This node is only reached if call_llm (using Llama) returns tool calls.
async def execute_tools(state: AgentState) -> Dict[str, List[ToolMessage]]:
    messages = state['messages']
    last_message = messages[-1]

    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        logger.warning("execute_tools called but last message has no tool calls.")
        return {"messages": []} # Return empty list, graph should handle this

    tool_messages: List[ToolMessage] = []
    logger.info(f"Executing {len(last_message.tool_calls)} tool call(s)...")

    for tool_call in last_message.tool_calls:
        tool_name = tool_call.get("name")
        tool_id = tool_call.get("id")
        tool_args = tool_call.get("args", {})

        if not tool_name or not tool_id:
             logger.warning(f"Skipping invalid tool call structure: {tool_call}")
             continue

        logger.info(f"Attempting execution: tool='{tool_name}', id='{tool_id}', args={tool_args}")
        tool_function = tool_executor_map.get(tool_name)

        if not tool_function:
            logger.error(f"Tool '{tool_name}' requested by LLM is not implemented or mapped.")
            result = f"Error: Tool '{tool_name}' not found."
        else:
            try:
                # Execute the tool function (await if async)
                if asyncio.iscoroutinefunction(tool_function):
                     result = await tool_function(**tool_args)
                else:
                     result = tool_function(**tool_args) # Assuming sync tools are okay if brief

                logger.info(f"Tool '{tool_name}' executed successfully. Result type: {type(result)}")
                # Ensure result is string
                if not isinstance(result, str):
                    try: result = json.dumps(result)
                    except Exception: logger.warning(f"Failed to serialize result for tool '{tool_name}'", exc_info=True); result = repr(result)

            except Exception as e:
                logger.error(f"Error executing tool '{tool_name}' with args {tool_args}: {e}", exc_info=True)
                result = f"Error executing tool {tool_name}: {type(e).__name__} - {e}"

        tool_messages.append(ToolMessage(content=str(result), tool_call_id=tool_id, name=tool_name))
        logger.debug(f"Appended ToolMessage: id={tool_id}, name={tool_name}, content_len={len(str(result))}")

    return {"messages": tool_messages}

# This logic correctly routes based on whether the *last* message (which would be from Llama if tools were possible) contains tool calls.
def should_continue(state: AgentState) -> Literal["execute_tools", "__end__"]:
    last_message = state['messages'][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        if any(tc.get("id") for tc in last_message.tool_calls):
             logger.info("Routing: LLM requested tools -> execute_tools")
             return "execute_tools"
        else:
             logger.warning("Routing: AIMessage has tool_calls attribute, but it's empty/invalid. Ending.")
             return "__end__"
    else:
        logger.info("Routing: LLM provided final response or no tools requested/possible -> __end__")
        return "__end__"


# --- build_agent_graph ---
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
    logger.info("LangGraph agent graph compiled with conditional model selection and tool execution.")
    return agent_executor

# --- Initialize Agent ---
agent_executor = build_agent_graph()