import json
import re
import os
import requests
import logging
from backend.report_pipeline import pipeline_config

logger = logging.getLogger(__name__)

CBT_INFRA_SIGNALS = [
    ("", "system.io.ioexception",                       "CBT Issue", "Power Supply — COM Port Missing",        "BENCH_DOWN"),
    ("", "the port 'com",                               "CBT Issue", "Power Supply — COM Port Missing",        "BENCH_DOWN"),
    ("", "error occured during turning power supply",   "CBT Issue", "Power Supply — Control Script Failure",   "BENCH_DOWN"),
    ("", "power supply communication failed",           "CBT Issue", "Power Supply — Communication Failure",    "BENCH_DOWN"),
    ("", "xcp not connected to cbt_xcp_",              "CBT Issue", "XCP Probe — Disconnection",              "BENCH_DOWN"),
    ("", "xcp connection failed",                       "CBT Issue", "XCP Probe — Connection Failure",          "BENCH_DOWN"),
    ("", "xcp session could not be established",        "CBT Issue", "XCP Probe — Session Failure",             "BENCH_DOWN"),
    ("", "a2l file could not be loaded",                "CBT Issue", "XCP — A2L Configuration Missing",         "BENCH_DEGRADED"),
    ("", "failedresponseparse",                         "CBT Issue", "VFlash — Firmware Flash Parse Error",     "BENCH_DOWN"),
    ("", "det flashing failed",                         "CBT Issue", "DET Tool — Firmware Flash Failure",       "BENCH_DOWN"),
    ("", "flashing failed",                             "CBT Issue", "Flashing — ECU Programming Failure",      "BENCH_DOWN"),
    ("", "serialloader",                                "CBT Issue", "SerialLoader — Bootloader Failure",       "BENCH_DOWN"),
    ("", "bootp server timeout",                        "CBT Issue", "VFlash — BootP Network Timeout",          "BENCH_DOWN"),
    ("", "could not connect to target",                 "CBT Issue", "Debugger — Target Connection Failure",    "BENCH_DOWN"),
    ("", "canal server not running",                    "CBT Issue", "CAN Hardware — CANAL Server Offline",     "BENCH_DOWN"),
    ("", "channel not available",                       "CBT Issue", "CAN Hardware — Vector Channel Down",      "BENCH_DOWN"),
    ("", "vector hardware not found",                   "CBT Issue", "CAN Hardware — Vector Device Missing",    "BENCH_DOWN"),
    ("", "vectorsimulationnode",                        "CBT Issue", "Vector Simulation Node — Missing",        "BENCH_DOWN"),
    ("", "network interface not found",                 "CBT Issue", "CAN Hardware — Network Interface Down",   "BENCH_DOWN"),
    ("", "could not send request for activediagnosticsession", "CBT Issue", "UDS Tool — Session Failure", "BENCH_DEGRADED"),
    ("", "valid session check failed",                  "CBT Issue", "UDS Tool — Session Validation Failure", "BENCH_DEGRADED"),
    ("", "communicationerror",                          "CBT Issue", "CAN/Diagnostic — Communication Error",  "BENCH_DEGRADED"),
    ("", "canoe is not running",                        "CBT Issue", "CANoe — Test Environment Not Started",    "BENCH_DOWN"),
    ("", "canoe could not be started",                  "CBT Issue", "CANoe — Application Launch Failure",      "BENCH_DOWN"),
    ("", "measurement could not be started",            "CBT Issue", "CANoe — Measurement Start Failure",       "BENCH_DOWN"),
    ("", "test environment initialization failed",      "CBT Issue", "Test Framework — Environment Init Fail",  "BENCH_DOWN"),
    ("", "license not available",                       "CBT Issue", "CANoe/Tool — License Server Down",        "BENCH_DOWN"),
    ("", "jenkins error",                               "CBT Issue", "Jenkins — CI Pipeline Execution Error",   "BENCH_DEGRADED"),
    ("", "workspace not found",                         "CBT Issue", "Jenkins — Workspace Missing",             "BENCH_DEGRADED"),
    ("", "artifact download failed",                    "CBT Issue", "Jenkins — Software Artifact Failure",     "BENCH_DEGRADED"),
    ("", "python script failed to start",               "CBT Issue", "CBT Script — Python Launch Failure",      "BENCH_DEGRADED"),
]

def is_llm_loaded() -> bool:
    """Pings the remote GPU PC to see if it is online and serving the model."""
    if os.getenv("MOCK_LLM", "false").lower() == "true":
        return True
    
    # We ping the /v1/models endpoint of the llama-cpp-python server
    remote_base_url = os.getenv("REMOTE_LLM_URL", "http://localhost:8001").replace("/v1/completions", "")
    try:
        res = requests.get(f"{remote_base_url}/v1/models", timeout=2)
        return res.status_code == 200
    except requests.exceptions.RequestException:
        return False

def _build_llm_prompt(build_data: dict, failed_logs_summary: str) -> str:
    return f"""You are an Expert Automotive ECU Software Test Analyst. Classify the following CBT failure.

PROJECT CONTEXT:
- Build Number: {build_data.get("build_number", "N/A")}
- Project: {build_data.get("project", "N/A")}

CLASSIFICATION RULES:
Your primary focus MUST be on the "Test Intent" (the overarching goal of the test case). The true failure reason is usually tied to what the test was trying to achieve, rather than granular or generic test-step errors.

[Category A] SOFTWARE DEFECT — ECU Logic Error
Select when logs show ECU behavioral failures related to the intent:
  - Sleep/Power Management: Intent is sleep/wakeup, ECU fails to enter sleep state.
  - ECU State/Boot: Intent is mode transition, ECU fails normal operation.
  - DTC Logic: Intent is fault injection, DTC is not set or missing.
  - UDS Response: Intent is diagnostics, bad response code or NRC received.
  - Flashing/Programming: Intent is firmware flash (VFlash, SerialLoader), flashing process fails.
  - Feature/Calibration: Intent is physical feature control (e.g., EPB, ABS), feature fails.

[Category B] SUSPECTED CBT ISSUE — MANUAL REVIEW REQUIRED
Select ONLY when:
  - ALL failed step text values are empty.
  - The failure pattern is completely ambiguous with no recognizable ECU signature.

REASONING CHAIN (Think step by step before outputting JSON):
Step 1: Read the Test Intent (Title + Description). What was this test trying to do?
Step 2: Look at the failed steps. Do they indicate the intent failed?
Step 3: If intent failed due to software/ECU logic → fault_category = "Software Issue — [Type]"
Step 4: Write a 1-2 sentence root cause statement focusing on the intent.

DEDUPLICATED LOGS:
{failed_logs_summary}

Respond ONLY with valid JSON. No preamble. No line breaks inside strings.
{{
  "fault_category": "Software Issue — [Type]" or "Suspected CBT Issue — Review Required",
  "root_cause_analysis": "1-2 sentences: based on the Test Intent, explain what failed.",
  "affected_component": "Name of component",
  "recommendation": "Suggested next action"
}}
JSON:"""

def _run_llm_on_testcases(build_data: dict, failed_tcs: list) -> dict:
    if os.getenv("MOCK_LLM", "false").lower() == "true":
        return {
            "category": "Software Issue", "text": "Mock analysis. LLM disabled.",
            "confidence_score": 0, "analysis_stage": "mock", "severity": "N/A"
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
            sig = raw_text[:80].lower() 
            if sig not in unique_error_signatures:
                unique_error_signatures.add(sig)
                clean_log = raw_text[:250] + "..." if len(raw_text) > 250 else raw_text
                clean_log = clean_log.replace("\n", " ").replace("\r", " ").replace('"', "'")
                compressed_logs.append(f"{intent_str} | Failed Step [{step.get('ident')}]: {clean_log}")
                if len(unique_error_signatures) >= 15: break
        if len(unique_error_signatures) >= 15: break

    if not compressed_logs:
        return {"category": "Review Required", "text": "All logs empty.", "confidence_score": 10, "analysis_stage": "review", "severity": "N/A"}
    
    prompt = _build_llm_prompt(build_data, "\n".join(compressed_logs))
    
    try:
        # === NEW ENTERPRISE REMOTE API CALL ===
        remote_llm_url = os.getenv("REMOTE_LLM_URL", "http://127.0.0.1:8001")
        if not remote_llm_url.endswith("/v1/completions"):
            remote_llm_url = f"{remote_llm_url.rstrip('/')}/v1/completions"

        payload = {
            "prompt": prompt,
            "max_tokens": pipeline_config.LLM_MAX_TOKENS,
            "temperature": pipeline_config.LLM_TEMPERATURE,
            "stop": ["</s>", "```"]
        }
        
        # Will fail gracefully if your GPU PC is turned off
        response = requests.post(remote_llm_url, json=payload, timeout=120)
        response.raise_for_status()
        
        raw_text = response.json()["choices"][0]["text"].strip()
        
        start_idx = raw_text.find('{')
        end_idx = raw_text.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = re.sub(r'[\n\r]+', ' ', raw_text[start_idx:end_idx+1])
            parsed = json.loads(json_str)
            
            raw_cat = parsed.get("fault_category", "Review Required")
            if "Software" in raw_cat: final_cat = "Software Issue"
            elif "CBT" in raw_cat and "Review" not in raw_cat and "Suspect" not in raw_cat: final_cat = "CBT Issue"
            elif "Suspect" in raw_cat: final_cat = "Suspected CBT Issue"
            else: final_cat = "Review Required"

            return {
                "category": final_cat,
                "text": parsed.get("root_cause_analysis", "No analysis generated."),
                "confidence_score": 80,
                "analysis_stage": "llm",
                "severity": "BENCH_DOWN" if final_cat == "CBT Issue" else "N/A"
            }
        else:
            raise ValueError("No JSON found.")
            
    except requests.exceptions.RequestException as e:
        logger.warning(f"Remote LLM Unreachable: {e}")
        return {"category": "Review Required", "text": "GPU Node is Offline. Manual review required.", "confidence_score": 0, "analysis_stage": "gpu_offline", "severity": "N/A"}
    except Exception as e:
        logger.error(f"Inference parse failed: {e}")
        return {"category": "Review Required", "text": "AI parse failed.", "confidence_score": 0, "analysis_stage": "error", "severity": "N/A"}

def analyze_failure(build_data: dict) -> dict:
    try:
        if build_data.get("end_result", "N/A") not in ["FAIL", "TIMEOUT", "EXECUTION_ERROR"]:
            return {"category": "-", "text": "", "confidence_score": 100, "analysis_stage": "skip", "severity": "N/A"}
        
        failed_tcs = [tc for tc in build_data.get("testcases", []) if tc.get("result") in ["FAIL", "TIMEOUT", "EXECUTION_ERROR"]]
        
        if not failed_tcs:
            return {"category": "Review Required", "text": "No failed testcases found.", "confidence_score": 0, "analysis_stage": "review", "severity": "N/A"}
            
        cbt_hit = None
        cbt_fail_idx = -1
        
        for i, tc in enumerate(failed_tcs):
            for step in tc.get("failed_steps", []):
                step_text_lower = step.get("text", "").lower()
                step_ident_lower = step.get("ident", "").lower()
                
                for (name_kw, text_kw, category, sub_category, severity) in CBT_INFRA_SIGNALS:
                    if ((not name_kw) or (name_kw in step_ident_lower)) and ((not text_kw) or (text_kw in step_text_lower)):
                        cbt_hit = {
                            "sub_category": sub_category,
                            "severity": severity,
                            "root_tc": tc.get("title", "Unknown"),
                            "trigger_text": step.get("text", "")[:150].split("\\n")[0].strip()
                        }
                        cbt_fail_idx = i
                        break
                if cbt_hit: break
            if cbt_hit: break
            
        if cbt_hit and len(failed_tcs) > 3 and cbt_fail_idx == 0:
            cbt_fail_idx = 0 

        if cbt_hit:
            cascade_count = len(failed_tcs) - 1 - cbt_fail_idx
            cbt_analysis = f"{cbt_hit['sub_category']} in testcase '{cbt_hit['root_tc']}'. Evidence: \"{cbt_hit['trigger_text']}\"."
            if cascade_count > 0: cbt_analysis += f" {cascade_count} subsequent testcase(s) cascaded."
            
            if cbt_fail_idx == 0:
                return {
                    "category": "CBT Issue",
                    "sub_category": cbt_hit["sub_category"],
                    "text": f"Root cause: {cbt_analysis} Action: Assign to bench maintenance.",
                    "confidence_score": 95,
                    "analysis_stage": "deterministic",
                    "severity": cbt_hit["severity"],
                    "trigger_step": cbt_hit["trigger_text"]
                }
            else:
                prior_failed_tcs = failed_tcs[:cbt_fail_idx]
                llm_res = _run_llm_on_testcases(build_data, prior_failed_tcs)
                return {
                    "category": "Multiple Issues (SW + CBT)",
                    "sub_category": cbt_hit["sub_category"],
                    "text": f"1. [SW] {llm_res['text']} | 2. [CBT] {cbt_analysis}",
                    "confidence_score": 85,
                    "analysis_stage": "mixed",
                    "severity": cbt_hit["severity"],
                    "trigger_step": cbt_hit["trigger_text"]
                }
                
        return _run_llm_on_testcases(build_data, failed_tcs)
    except Exception as e:
        logger.error(f"Fatal error in analyze_failure: {e}", exc_info=True)
        return {"category": "Review Required", "text": "Analysis failed.", "confidence_score": 0, "analysis_stage": "error", "severity": "N/A"}