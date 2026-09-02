import json
import re
import os
import threading
import logging
from backend.report_pipeline import pipeline_config

logger = logging.getLogger(__name__)

_llm_instance = None
_llm_lock = threading.Lock()

def get_llm():
    global _llm_instance
    if os.getenv("MOCK_LLM", "false").lower() == "true":
        return None
        
    with _llm_lock:
        if _llm_instance is None:
            try:
                from llama_cpp import Llama
                logger.info(f"⏳ Loading LLaMA 3 model from {pipeline_config.GGUF_MODEL_PATH}...")
                _llm_instance = Llama(
                    model_path=pipeline_config.GGUF_MODEL_PATH,
                    n_ctx=pipeline_config.LLM_N_CTX,
                    n_threads=pipeline_config.LLM_N_THREADS,
                    n_gpu_layers=pipeline_config.LLM_N_GPU_LAYERS,
                    verbose=False
                )
            except Exception as e:
                logger.error(f"❌ Failed to load LLM: {e}", exc_info=True)
                raise e
    return _llm_instance

def is_llm_loaded() -> bool:
    if os.getenv("MOCK_LLM", "false").lower() == "true":
        return True
    return _llm_instance is not None or os.path.exists(pipeline_config.GGUF_MODEL_PATH)

def _build_llm_prompt(build_data: dict, failed_logs_summary: str) -> str:
    return f"""You are an Expert Automotive ECU Software Test Analyst. Your job is to classify a CBT (Continuous Build and Test) failure by evaluating the TEST INTENT against the ERROR LOGS.

PROJECT CONTEXT:
- Build Number: {build_data.get("build_number", "N/A")}
- Project: {build_data.get("project", "N/A")}

CLASSIFICATION TAXONOMY & RULES:
You must determine if this is a Software Defect or a Bench/Hardware fault based on CONTEXT. 

[Category A] SOFTWARE ISSUE — ECU Logic Defect
Select this if the ECU failed to meet the test intent, or if the ECU crashed/stopped responding during a valid test step.
Examples: 
- ECU did not enter sleep mode within timeout.
- Expected DTC was not stored.
- ECU rejected a valid UDS diagnostic request (Negative Response).
- Cycle time violations (CAN/FlexRay timing).
- ECU stopped communicating *during* an active feature test (indicates an ECU reset/crash).

[Category B] CBT ISSUE — Test Bench / Infrastructure Fault
Select this ONLY if the logs indicate the physical test environment was broken before the ECU could even be tested.
Examples:
- Host PC Windows errors (System.IO.IOException, missing COM ports).
- Measurement tooling completely disconnected from the start (XCP probe missing).
- Jenkins/CANoe environment crashed or licenses were missing.

[Category C] SUSPECTED CBT ISSUE — MANUAL REVIEW REQUIRED
Select this if the logs are entirely empty or the failure is too ambiguous to confidently classify.

REASONING CHAIN (Think step by step):
Step 1: Read the "Test Intent" to understand what the framework was trying to do.
Step 2: Read the "Failed Step". Did the test environment break, or did the ECU fail to behave correctly?
Step 3: Consider nuance: A "communication error" during flashing might be a bad flash file (Software) or a broken CAN cable (CBT). Use surrounding context to decide.
Step 4: Output your final classification and a 1-2 sentence root cause.

DEDUPLICATED LOGS:
{failed_logs_summary}

Respond ONLY with valid JSON. No preamble. No line breaks inside strings.
{{
  "fault_category": "Software Issue", "CBT Issue", or "Review Required",
  "root_cause_analysis": "1-2 sentences: based on the Test Intent, explain what failed.",
  "confidence_score": <integer 1-100 based on how clear the logs are>,
  "recommendation": "Suggested next action"
}}
JSON:"""

def _run_llm_on_testcases(build_data: dict, failed_tcs: list) -> dict:
    if os.getenv("MOCK_LLM", "false").lower() == "true":
        return {
            "category": "Software Issue — Mock Analysis (DEV MODE)",
            "text": "Mock analysis for development. LLM is disabled.",
            "confidence_score": 0,
            "analysis_stage": "mock",
            "severity": "N/A"
        }
        
    unique_error_signatures = set()
    compressed_logs = []
    
    for tc in failed_tcs:
        title = tc.get("title", "Unknown Test")
        desc = tc.get("description", "")
        intent_str = f"Test Intent: [{title}] - {desc}" if desc else f"Test Intent: [{title}]"
        
        steps = tc.get("failed_steps", [])
        
        if not steps:
            compressed_logs.append(f"{intent_str} | Error: No detailed step logs (empty).")
            continue
            
        for step in steps:
            raw_text = step.get("text", "")
            # Fingerprint the error to deduplicate repeating loop failures
            sig = raw_text[:80].lower() 
            if sig not in unique_error_signatures:
                unique_error_signatures.add(sig)
                clean_log = raw_text[:250] + "..." if len(raw_text) > 250 else raw_text
                clean_log = clean_log.replace("\n", " ").replace("\r", " ").replace('"', "'")
                compressed_logs.append(f"{intent_str} | Failed Step [{step.get('ident')}]: {clean_log}")
                
                # Protect context window length
                if len(unique_error_signatures) >= 15:
                    break
        if len(unique_error_signatures) >= 15:
            break

    if not compressed_logs:
        return {
            "category": "Review Required", 
            "text": "All step logs are empty. Manual inspection of the Jenkins workspace is required.", 
            "confidence_score": 10, 
            "analysis_stage": "review_required", 
            "severity": "N/A"
        }
    
    failed_logs_summary = "\n".join(compressed_logs)
    prompt = _build_llm_prompt(build_data, failed_logs_summary)
    
    try:
        llm = get_llm()
        response = llm(
            prompt, 
            max_tokens=pipeline_config.LLM_MAX_TOKENS, 
            temperature=pipeline_config.LLM_TEMPERATURE, 
            stop=["</s>", "```"]
        )
        raw_text = response["choices"][0]["text"].strip()
        
        # Robust JSON extraction
        start_idx = raw_text.find('{')
        end_idx = raw_text.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = raw_text[start_idx:end_idx+1]
            json_str = re.sub(r'[\n\r]+', ' ', json_str)
            parsed = json.loads(json_str)
            
            # Map LLM categories back to UI styling categories safely
            raw_cat = parsed.get("fault_category", "Review Required")
            if "Software" in raw_cat:
                final_cat = "Software Issue"
            elif "CBT" in raw_cat and "Review" not in raw_cat and "Suspect" not in raw_cat:
                final_cat = "CBT Issue"
            elif "Suspect" in raw_cat:
                final_cat = "Suspected CBT Issue"
            else:
                final_cat = "Review Required"

            # Parse confidence strictly as integer
            try:
                conf = int(parsed.get("confidence_score", 50))
            except ValueError:
                conf = 50
            
            return {
                "category": final_cat,
                "text": parsed.get("root_cause_analysis", "No analysis generated."),
                "confidence_score": conf,
                "analysis_stage": "llm",
                "severity": "BENCH_DOWN" if final_cat == "CBT Issue" else "N/A"
            }
        else:
            raise ValueError("No valid JSON brackets found in LLM output.")
            
    except Exception as e:
        logger.error(f"[pipeline_llm] Inference failed for build {build_data.get('build_number')}: {e}", exc_info=True)
        return {
            "category": "Review Required", 
            "text": "AI inference engine failed to parse the logs.", 
            "confidence_score": 0, 
            "analysis_stage": "error", 
            "severity": "N/A"
        }

def analyze_failure(build_data: dict) -> dict:
    """
    Main entry point for pipeline orchestrator.
    Passes all failed testcases directly to the LLM for contextual semantic analysis.
    """
    try:
        if build_data.get("end_result", "N/A") not in ["FAIL", "TIMEOUT", "EXECUTION_ERROR"]:
            return {"category": "-", "text": "", "confidence_score": 100, "analysis_stage": "skip", "severity": "N/A"}
        
        failed_tcs = [tc for tc in build_data.get("testcases", []) if tc.get("result") in ["FAIL", "TIMEOUT", "EXECUTION_ERROR"]]
        
        if not failed_tcs:
            return {
                "category": "Review Required", 
                "text": "Build marked failed but no failed testcases found in the MongoDB document.", 
                "confidence_score": 0, 
                "analysis_stage": "review_required", 
                "severity": "N/A"
            }
            
        # Enterprise Approach: Let the LLM evaluate the complete deduplicated trace.
        return _run_llm_on_testcases(build_data, failed_tcs)
        
    except Exception as e:
        logger.error(f"[pipeline_llm] Fatal error in analyze_failure: {e}", exc_info=True)
        return {
            "category": "Review Required", 
            "text": "Analysis failed due to internal pipeline error.", 
            "confidence_score": 0, 
            "analysis_stage": "error", 
            "severity": "N/A"
        }