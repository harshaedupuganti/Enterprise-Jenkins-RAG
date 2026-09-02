import os
import json
from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from langchain.agents import create_agent
from langchain.tools import tool

from backend.jenkins_client import fetch_jenkins_nodes
from backend.cbt_knowledge_client import get_cbt_knowledge_base
from .mongo_cbt_client import (
    search_by_build_number, 
    get_latest_report_for_project, 
    get_summary_last_24h,
    search_deep_metric
)

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

# 2. Universal Real-Time Data Pipeline Tool

def _format_tool_response(payload: dict) -> str:
    """
    Formats and optimizes MongoDB responses for the LLM context window.
    """
    if not payload:
        return json.dumps({"error": "No matching CBT report found."})
    if "error" in payload:
        return json.dumps(payload)
    
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

    response_str = json.dumps(payload, default=str)
    
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
def get_cbt_build_summary_last_24h(hours: int = 24, start_date: str = None, end_date: str = None, project: str = None) -> str:
    """
    Returns aggregated statistics of CBT builds for ANY requested timeframe.
    Use this for questions like: how many builds ran in the last X hours/days, what is the failure rate,
    which projects had failures, or overall health over a timeframe.
    """
    data = get_summary_last_24h(hours=hours, start_date=start_date, end_date=end_date, project=project)
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
    metrics = {"Total_Benches_And_Nodes": len(nodes), "Idle": 0, "Busy": 0, "Temporarily_Offline": 0, "Offline": 0}

    for node in nodes:
        is_offline = node.get("offline", False)
        is_temp_offline = node.get("temporarilyOffline", False)
        is_idle = node.get("idle", False)
        
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

    return json.dumps({"metrics": metrics, "inventory": inventory}, indent=2)

@tool
def compare_builds_metric(build_numbers: str, metric_query: str) -> str:
    """
    Compares a specific metric (CPU load, power, sleep time, DTCs, cycle time)
    across two or more CBT build numbers side by side.
    
    Use when user says: "compare build X and Y", "difference between 1466646 and 1466284 for cpu load",
    "which build has better cpu load: X or Y", "trend of sleep time across builds X, Y, Z".
    
    - build_numbers: Comma-separated build numbers, e.g. "1466646,1466284,1465000"
    - metric_query: The metric to compare, e.g. "cpu load", "sleep", "power", "failures", "cycle time"
    
    Returns structured comparison data for all requested builds.
    """
    build_list = [b.strip() for b in build_numbers.split(",") if b.strip()]
    if len(build_list) < 2:
        return json.dumps({"error": "Please provide at least 2 build numbers separated by commas."})
    if len(build_list) > 5:
        return json.dumps({"error": "Maximum 5 builds can be compared at once to avoid context limits."})
    
    results = {}
    for build_num in build_list:
        # Calls the actual DB search function for each build
        results[build_num] = search_deep_metric(build_num, metric_query)
    
    return json.dumps({
        "comparison_type": "Multi-Build Metric Comparison",
        "metric": metric_query,
        "builds_compared": build_list,
        "data": results
    }, default=str)

# Register Tools
tools = [
    get_live_jenkins_inventory, 
    get_cbt_report_by_build_number, 
    get_latest_cbt_report_for_project, 
    get_cbt_build_summary_last_24h,
    get_cbt_deep_metric,
    get_cbt_knowledge_base,
    compare_builds_metric,
]

# 3. ABSOLUTE SYSTEM OVERRIDE (State Modifier)
system_override = """You are a highly restricted Enterprise IT Assistant managing Jenkins infrastructure
AND CBT (Continuous Build and Test) build intelligence for automotive embedded software testing.

You have SEVEN specialized tools:
  1. get_live_jenkins_inventory         — Real-time Jenkins node/bench availability.
  2. get_cbt_report_by_build_number     — Fetch a specific CBT report summary by build number.
  3. get_latest_cbt_report_for_project  — Fetch most recent CBT report summary for a project.
  4. get_cbt_build_summary_last_24h     — Aggregated CBT statistics for last 24 hours.
  5. get_cbt_deep_metric                — Extract specific deep metrics (CPU, Power, Sleep, DTCs, Failures).
  6. get_cbt_knowledge_base             — Official CBT static reference: architecture, definitions, dashboards, URLs.
  7. compare_builds_metric              — Compare metrics side-by-side across multiple builds.

*** TOOL ROUTING POLICIES ***
1. REFERENCE / ARCHITECTURE / LINKS:
   - If asked "What is CBT?", "Explain shift-left", or "Give me the Grafana/Jenkins link":
     --> MUST use `get_cbt_knowledge_base`.

2. LIVE METRICS & ERRORS:
   - If asked for CPU loads, DTC lists, or "Why did build X fail?":
     --> MUST use `get_cbt_deep_metric`.
   - If asked for report summaries:
     --> MUST use `get_cbt_report_by_build_number` or `get_latest_cbt_report_for_project`.

*** STRICT SCOPE & VERBOSITY RULES (CRITICAL) ***
1. ANSWER EXACTLY WHAT IS ASKED: Never volunteer unprompted information.
2. IGNORE EXCESS TOOL DATA: Extract ONLY the exact data point needed to answer the user's specific question. Discard the rest.
3. BE CONCISE BUT POLITE: Provide a brief 1-2 sentence professional introduction before showing data. 
4. NO TRUNCATION: NEVER truncate tables, logs, or lists with "..." or "etc.". Output every single row.

*** PRESENTATION RULES ***
- Output tabular data using standard Markdown table syntax.
- Structure conceptual answers clearly with subheadings and bullet points.
- Always include the actual URLs (hyperlinked) when referencing dashboards or monitoring tools.

*** CRITICAL SECURITY GUARDRAILS ***
1. GREETING RULE: If the user simply greets you, politely introduce yourself as the CBT AI Assistant.
2. REFUSAL RULE: If the user asks for ANY general knowledge, programming code, weather, trivia, or math, reply EXACTLY with:
   "ACCESS DENIED: I am restricted to querying Jenkins infrastructure and CBT report data only."
3. NO HALLUCINATIONS: Always call the appropriate tool before answering any factual question.

*** CBT REPORT ROUTING RULES ***
4. SUMMARY ROUTING: If user asks "show me build 1447833" -> use get_cbt_report_by_build_number.
5. DEEP METRIC ROUTING (Values & Tables): If user asks for SPECIFIC inner values ("CPU load", "Sleep time"), MUST use get_cbt_deep_metric. Pass highly specific, multi-word keywords to `metric_query`.
6. ROOT CAUSE / FAILURE ROUTING: If user asks "Why did it fail?", MUST call get_cbt_deep_metric and pass "failures" as the metric_query.
7. MULTI-BUILD COMPARISON: If the user asks to compare a metric across multiple builds (e.g. "compare cpu load between 1466646 and 1466284"), use compare_builds_metric. Pass ALL build numbers as a comma-separated string.
   PRESENTATION: Format the comparison as a clean Markdown table with one column per build. Highlight the best/worst value in each row. Add a "Winner" column.
   Example output table format:
   | Metric | Build 1466646 | Build 1466284 | Winner |
   |--------|--------------|--------------|--------|
   | Core 0 Avg Load | 7.2% | 8.9% | 1466646 ✓ |
8. RICH RESPONSES & PROPER UI RENDERING: Always present deep metric data beautifully. STRICTLY USE the headers provided in `extracted_table.headers`. DO NOT wrap Markdown tables inside ```text or ```markdown code blocks. Our frontend UI renders raw markdown tables natively. Just output the raw markdown table directly.
9. BENCH/NODE RESOLUTION: Bench = Node. If the user asks about bench status, search Jenkins inventory.
"""

agent_executor = create_agent(llm, tools=tools, system_prompt=system_override)

def get_ai_response(chat_history: list) -> str:
    formatted_messages = []
    for msg in chat_history:
        formatted_messages.append((msg["role"], msg["content"]))

    try:
        response = agent_executor.invoke({"messages": formatted_messages})
        return response["messages"][-1].content
    except Exception as e:
        return f"System Error: {str(e)}"