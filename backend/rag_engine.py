import os
import json
from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from langchain_core.tools import tool
from langchain.agents import create_agent
from backend.jenkins_client import fetch_jenkins_nodes
from langchain.tools import tool
# Load environment configuration
load_dotenv()

# 1. Initialize Azure OpenAI Client
llm = AzureChatOpenAI(
    azure_deployment=os.getenv("AZURE_DEPLOYMENT_NAME"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2023-05-15"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    temperature=0
)

from .mongo_cbt_client import (
    search_by_build_number, 
    get_latest_report_for_project, 
    get_summary_last_24h,
    search_deep_metric
)
# 2. Universal Real-Time Data Pipeline Tool

def _format_tool_response(payload: dict) -> str:
    """
    Formats and optimizes MongoDB responses for the LLM context window.
    """
    if not payload:
        return json.dumps({"error": "No matching CBT report found."})
    if "error" in payload:
        return json.dumps(payload)
    
    # 1. OPTIMIZATION: Isolate only the fields the AI needs to answer user queries
    # This prevents token bloat and keeps massive test lists under LLM limits.
    if "testcases" in payload and isinstance(payload["testcases"], list):
        optimized_tc = []
        for tc in payload["testcases"]:
            optimized_tc.append({
                "title": tc.get("title", "Unknown"),
                "result": tc.get("result", "N/A"),
                "duration": tc.get("duration", "0:00:00"),
                "qg_status": tc.get("qg_status", "N/A"),
                "comment": tc.get("comment", "N/A")
            })
        payload["testcases"] = optimized_tc

    # 2. Serialize safely
    response_str = json.dumps(payload, default=str)
    
    # 3. CONTEXT SAFETY NET: 150k characters allows for roughly ~35k tokens, 
    # well within modern Enterprise LLM limits but preventing API crashes.
    if len(response_str) > 150000:
        if "testcases" in payload:
            payload["testcases"] = []
            payload["_note"] = "Response heavily truncated due to extreme data size limits. Ask the user for specific subsets of test cases."
            response_str = json.dumps(payload, default=str)
            
    return response_str

@tool
def get_cbt_report_by_build_number(build_number: str) -> str:
    """
    Fetches a specific CBT test report from MongoDB by its BMS build number.
    Use this when the user mentions a specific build number.
    Returns: project identity, build metadata, overall result, test bench, 
             runtime, and a summary of all testcase results.
    """
    data = search_by_build_number(build_number)
    return _format_tool_response(data)

@tool
def get_latest_cbt_report_for_project(project_name: str) -> str:
    """
    Fetches the most recent CBT test report for a given project name from MongoDB.
    Use this when the user asks about a project without specifying a build number.
    Also useful for trend analysis — call multiple times with different project names.
    Returns: latest build metadata, result, test duration, testcase pass/fail summary.
    """
    data = get_latest_report_for_project(project_name)
    return _format_tool_response(data)

@tool
def get_cbt_build_summary_last_24h() -> str:
    """
    Returns aggregated statistics of all CBT builds from the last 24 hours.
    Use this for questions like: how many builds ran today, what is the failure rate,
    which projects had failures, overall health of the test infrastructure.
    """
    data = get_summary_last_24h()
    response_str = json.dumps(data, default=str)
    if len(response_str) > 150000:
        if "recent_builds" in data:
            data["recent_builds"] = data["recent_builds"][:150] 
            data["_note"] = "Build list heavily truncated due to extreme size. Displaying 150 builds."
            response_str = json.dumps(data, default=str)
            
    return response_str

@tool
def get_cbt_deep_metric(build_number: str, metric_query: str) -> str:
    """
    Use this tool when the user asks for specific nested values inside a CBT report,
    such as 'CPU load', 'Power consumption', 'Current', 'Voltage', 'Sleep time', 'Startup time', 
    'DTCs', or any other specific tabular/text data from the test steps.
    - build_number: The specific build number (e.g. '1447833')
    - metric_query: A short 1-3 word keyword search (e.g., 'cpu load', 'sleep', 'power')
    """
    data = search_deep_metric(build_number, metric_query)
    return _format_tool_response(data)

@tool
def get_live_jenkins_inventory() -> str:
    """
    Fetches the live, real-time state of all infrastructure directly from Jenkins.
    """
    nodes = fetch_jenkins_nodes()
    if not nodes:
        return json.dumps({"error": "Unable to communicate with Jenkins API or no data returned."})

    inventory = []
    
    metrics = {
        "Total_Benches_And_Nodes": len(nodes),
        "Idle": 0,
        "Busy": 0,
        "Temporarily_Offline": 0,
        "Offline": 0
    }

    for node in nodes:
        is_offline = node.get("offline", False)
        is_temp_offline = node.get("temporarilyOffline", False)
        is_idle = node.get("idle", False)
        
        # APPLYING EXACT STRICT FORMULA FOR STATUS
        if is_temp_offline == True:
            status = "Temporarily Offline"
            metrics["Temporarily_Offline"] += 1
        elif is_offline == True:
            status = "Offline"
            metrics["Offline"] += 1
        elif is_offline == False and is_idle == True:
            status = "Idle"
            metrics["Idle"] += 1
        elif is_offline == False and is_idle == False:
            status = "Busy"
            metrics["Busy"] += 1
        else:
            status = "Unknown"
        
        labels = [lbl.get("name") for lbl in node.get("assignedLabels", []) if lbl.get("name")]
        
        item = {
            "name": node.get("displayName", "Unknown"),
            "status": status,
            "description": node.get("description", "") or "No description",
            "labels": labels
        }
        
        if status in ["Offline", "Temporarily Offline"]:
            reason = node.get("offlineCauseReason", "")
            item["offline_reason"] = reason.split('\n')[0].strip() if reason else "No reason specified"
            
        inventory.append(item)

    payload = {
        "metrics": metrics,
        "inventory": inventory
    }

    return json.dumps(payload, indent=2)

# Register Tool
tools = [
    get_live_jenkins_inventory, 
    get_cbt_report_by_build_number, 
    get_latest_cbt_report_for_project, 
    get_cbt_build_summary_last_24h,
    get_cbt_deep_metric
]

# 3. ABSOLUTE SYSTEM OVERRIDE (State Modifier)
# This replaces the manual chat_history insertion and creates a permanent jail.
system_override ="""You are a highly restricted CBT Team AI Assistant managing Jenkins infrastructure 
AND CBT (Continuous Build Test) build intelligence for automotive embedded software testing.

You have FIVE tools total:
  1. get_live_jenkins_inventory         — Real-time Jenkins node/bench status
  2. get_cbt_report_by_build_number     — Fetch a specific CBT report summary by build number
  3. get_latest_cbt_report_for_project  — Fetch most recent CBT report summary for a project
  4. get_cbt_build_summary_last_24h     — Aggregated CBT statistics for the last 24 hours
  5. get_cbt_deep_metric                — Extract specific deep data (CPU, Power, Sleep, DTCs, Failures)

*** CRITICAL SECURITY GUARDRAILS ***
1. GREETING RULE: If the user simply greets you (e.g., "hi", "hello", "hey"), politely introduce yourself as the CBT AI Assistant, and ask how you can help them with their infrastructure or test reports today.
2. REFUSAL RULE: If the user asks for ANY general knowledge, programming code, weather, trivia, 
   math, or anything unrelated to Jenkins infrastructure or CBT test reports, reply EXACTLY with:
   "ACCESS DENIED: I am restricted to querying Jenkins infrastructure and CBT report data only."
3. NEVER generate code snippets. NEVER answer math questions.
4. NO HALLUCINATIONS: Always call the appropriate tool before answering any factual question.

*** CBT REPORT ROUTING RULES ***
5. SUMMARY ROUTING: If the user asks "show me build 1447833" or "status of project WS", 
   use get_cbt_report_by_build_number or get_latest_cbt_report_for_project.

6. DEEP METRIC ROUTING (Values & Tables): If the user asks for SPECIFIC inner values 
   (e.g., "What is the CPU load", "Power consumption", "List DTCs", "Startup time"), you MUST 
   use get_cbt_deep_metric. 
   CRITICAL: Pass highly specific, multi-word keywords to `metric_query` to avoid truncation. 
   - Example 1: User asks "cpu load after clear dtc" -> metric_query = "cpu load clear dtc"
   - Example 2: User asks "power consumption" -> metric_query = "power consumption"

7. ROOT CAUSE / FAILURE ROUTING: If the user asks "What is the root cause of failure?", 
   "Why did it fail?", or "Show me the errors", you MUST call get_cbt_deep_metric and pass 
   the exact word "failures" as the metric_query. This will extract all failed test steps.

8. RICH RESPONSES & SCROLLABLE UI: Always present deep metric data beautifully. 
   - When outputting tables, STRICTLY USE the headers provided in `extracted_table.headers`. Do not invent column names like 'Col2'.
   - Present CPU loads, Voltages, and Sleep times using clear Markdown tables.
   - *** CRITICAL UI REQUIREMENT ***: Standard Markdown does not support scrollable tables. When returning a large list of items (like ALL test cases in a build, OR the list of ALL builds in the last 24 hours), you MUST embed the Markdown table inside a generic code block. This forces the chat UI to render a scrollable window. 
   - Wrap the output EXACTLY like this using triple backticks:

   ```text
   | Column 1 | Column 2 | Column 3 | Column 4 |
   |---|---|---|---|
   | Data | Data | Data | Data |
"""

# Build Agent Pipeline WITH the strict state modifier bound directly to the agent
agent_executor = create_agent(llm, tools=tools, system_prompt=system_override)

def get_ai_response(chat_history: list) -> str:
    """Passes only the conversational history. The agent's rules are permanently hardcoded above."""
    
    # We no longer manually prepend the system prompt here.
    # We only format the user/assistant chat history.
    formatted_messages = []
    for msg in chat_history:
        formatted_messages.append((msg["role"], msg["content"]))

    try:
        response = agent_executor.invoke({"messages": formatted_messages})
        return response["messages"][-1].content
    except Exception as e:
        return f"System Error: {str(e)}"