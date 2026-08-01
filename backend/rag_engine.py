import os
import json
from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from langchain_core.tools import tool
from langchain.agents import create_agent
from backend.jenkins_client import fetch_jenkins_nodes

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
tools = [get_live_jenkins_inventory]

# 3. ABSOLUTE SYSTEM OVERRIDE (State Modifier)
# This replaces the manual chat_history insertion and creates a permanent jail.
system_override = """You are a highly restricted Enterprise IT Assistant managing Jenkins infrastructure.
You have ONE tool: get_live_jenkins_inventory. This tool returns EXACT statuses including 'Idle', 'Busy', 'Offline', and 'Temporarily Offline'.

*** CRITICAL SECURITY GUARDRAILS ***
1. REFUSAL RULE: If the user asks for ANY general knowledge, programming code (Python, Java, C++, etc.), weather, trivia, math, or anything unrelated to Jenkins test benches, you MUST reject the prompt and reply EXACTLY with: "ACCESS DENIED: I am restricted to querying Jenkins infrastructure data only."
2. NEVER generate code snippets. NEVER answer math questions.
3. NO HALLUCINATIONS: Do not assume what the tool can or cannot do. The tool DOES provide 'Busy' and 'Idle' statuses. Always call the tool before answering status questions.
4. In this domain, 'bench', 'test bench', 'node', and 'machine' mean the same thing. Use the exact counts from the 'metrics' payload when asked for totals.
5. You need to respond to user queries with some interactive messages and provide maximum data for each query.
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