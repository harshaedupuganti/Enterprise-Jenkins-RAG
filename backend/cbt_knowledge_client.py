import os
import json
import logging
import functools
import re
from typing import Dict, Any, List
from langchain.tools import tool

logger = logging.getLogger(__name__)

# Define the path to the data directory
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

@functools.lru_cache(maxsize=1)
def _load_all_json_knowledge() -> Dict[str, Any]:
    """
    Dynamically loads all JSON files from the backend/data directory.
    Cached in memory to ensure sub-millisecond retrieval during chat execution.
    """
    combined_knowledge = {}
    
    if not os.path.exists(DATA_DIR):
        logger.warning(f"Data directory not found at {DATA_DIR}. Creating it.")
        os.makedirs(DATA_DIR, exist_ok=True)
        return combined_knowledge

    for filename in os.listdir(DATA_DIR):
        if filename.endswith(".json"):
            filepath = os.path.join(DATA_DIR, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    # Use the filename (without .json) as the root key for the data
                    key_name = filename[:-5]
                    combined_knowledge[key_name] = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load JSON file {filename}: {e}")

    return combined_knowledge

def _search_nested_dict(data: Any, keywords: List[str]) -> bool:
    """Recursively checks if any keyword exists in the dictionary's string values."""
    if isinstance(data, str):
        data_lower = data.lower()
        return any(kw in data_lower for kw in keywords)
    elif isinstance(data, dict):
        return any(_search_nested_dict(v, keywords) for v in data.values())
    elif isinstance(data, list):
        return any(_search_nested_dict(item, keywords) for item in data)
    return False

@tool
def get_cbt_knowledge_base(query: str) -> str:
    """
    Official Enterprise Knowledge Base for CBT (Continuous Build and Test).
    
    Use this tool when the user asks about:
    - CBT definitions, CBT+, shift-left testing, CI/CD pipeline integration.
    - Test execution strategies (Standard, Extended, Release) and durations.
    - Hardware setups (Gen1, Gen2, braking, steering) and architecture layers.
    - Supported products (IBC, ESC, SBW, etc.) and categories.
    - Dashboard URLs (Jenkins, Grafana, IQM, PowerBI, manual builds).
    
    Do NOT use for real-time Jenkins states or specific MongoDB build metrics.
    
    Args:
        query: The user's specific concept, hardware, or dashboard question.
    """
    kb = _load_all_json_knowledge()
    
    if not kb:
        return json.dumps({"error": "No knowledge base files found in the backend/data/ directory."})

    query_lower = query.lower()
    # Extract meaningful keywords (ignore short words like "is", "the", "a")
    keywords = [w for w in re.split(r"\W+", query_lower) if len(w) > 2]
    
    # If the query is broad (e.g., "tell me about CBT"), return the whole KB capped
    if not keywords:
        output = json.dumps(kb, indent=2)
        return output if len(output) < 10000 else output[:10000] + "\n...[Content truncated]"

    # Filter the JSON based on keyword hits to save token space
    filtered_result = {}
    
    for file_key, file_data in kb.items():
        # Handle the CBT concepts JSON structure
        if "knowledge_base" in file_data:
            kb_root = file_data["knowledge_base"]
            matched_sections = {}
            for section_key, section_data in kb_root.items():
                if _search_nested_dict(section_key, keywords) or _search_nested_dict(section_data, keywords):
                    matched_sections[section_key] = section_data
            if matched_sections:
                filtered_result[file_key] = matched_sections
                
        # Handle the Dashboards JSON structure
        elif "cbt_resources" in file_data:
            matched_resources = []
            for resource in file_data["cbt_resources"]:
                if _search_nested_dict(resource, keywords):
                    matched_resources.append(resource)
            if matched_resources:
                filtered_result[file_key] = {"matched_resources": matched_resources}
                
        # Fallback for future JSON structures
        else:
            if _search_nested_dict(file_data, keywords):
                 filtered_result[file_key] = file_data

    # If keywords didn't yield specific matches, return everything to let the LLM sort it out
    payload = filtered_result if filtered_result else kb
    return json.dumps(payload, indent=2)