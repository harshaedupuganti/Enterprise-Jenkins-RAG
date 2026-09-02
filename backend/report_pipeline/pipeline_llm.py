import json
import re
import os
import threading
import logging
from backend.report_pipeline import pipeline_config

logger = logging.getLogger(__name__)

CBT_INFRA_SIGNALS = [
    # HARDWARE: Power Supply / Serial Port
    ("", "system.io.ioexception",                       "CBT Issue", "Power Supply — COM Port Missing (Hardware Fault)",        "BENCH_DOWN"),
    ("", "the port 'com",                               "CBT Issue", "Power Supply — COM Port Missing (Hardware Fault)",        "BENCH_DOWN"),
    ("", "error occured during turning power supply",   "CBT Issue", "Power Supply — Control Script Failure",                   "BENCH_DOWN"),
    ("", "power supply communication failed",           "CBT Issue", "Power Supply — Communication Failure",                    "BENCH_DOWN"),
    # HARDWARE: XCP Probe / Measurement
    ("", "xcp not connected to cbt_xcp_",              "CBT Issue", "XCP Probe — Disconnection (Hardware Fault)",              "BENCH_DOWN"),
    ("", "xcp connection failed",                       "CBT Issue", "XCP Probe — Connection Failure",                          "BENCH_DOWN"),
    ("", "xcp session could not be established",        "CBT Issue", "XCP Probe — Session Failure",                             "BENCH_DOWN"),
    ("", "a2l file could not be loaded",                "CBT Issue", "XCP — A2L Configuration File Missing",                    "BENCH_DEGRADED"),
    # HARDWARE: Flash / Programming Tool
    ("", "failedresponseparse",                         "CBT Issue", "VFlash — Firmware Flash Parse Error",                     "BENCH_DOWN"),
    ("", "det flashing failed",                         "CBT Issue", "DET Tool — Firmware Flash Failure",                       "BENCH_DOWN"),
    ("", "flashing failed",                             "CBT Issue", "Flashing — ECU Programming Failure",                      "BENCH_DOWN"),
    ("", "serialloader",                                "CBT Issue", "SerialLoader — Bootloader Flash Tool Failure",            "BENCH_DOWN"),
    ("", "bootp server timeout",                        "CBT Issue", "VFlash — BootP Network Timeout (Ethernet Flash)",         "BENCH_DOWN"),
    ("", "could not connect to target",                 "CBT Issue", "Debugger — Target Connection Failure",                    "BENCH_DOWN"),
    # HARDWARE: CAN / Network Hardware
    ("", "canal server not running",                    "CBT Issue", "CAN Hardware — CANAL Server Offline",                     "BENCH_DOWN"),
    ("", "channel not available",                       "CBT Issue", "CAN Hardware — Vector Channel Not Available",             "BENCH_DOWN"),
    ("", "vector hardware not found",                   "CBT Issue", "CAN Hardware — Vector Device Missing",                    "BENCH_DOWN"),
    ("", "vectorsimulationnode",                        "CBT Issue", "Vector Simulation Node — Missing or Crashed",             "BENCH_DOWN"),
    ("", "network interface not found",                 "CBT Issue", "CAN Hardware — Network Interface Missing",                "BENCH_DOWN"),
    # SOFTWARE TOOL: UDS / Diagnostic Session
    ("", "could not send request for activediagnosticsession", "CBT Issue", "UDS Tool — Diagnostic Session Establishment Failure", "BENCH_DEGRADED"),
    ("", "valid session check failed",                  "CBT Issue", "UDS Tool — Session Validation Failure (Cascade)",         "BENCH_DEGRADED"),
    ("", "communicationerror",                          "CBT Issue", "CAN/Diagnostic — Communication Layer Error",              "BENCH_DEGRADED"),
    # ENVIRONMENT: CANoe / Test Framework
    ("", "canoe is not running",                        "CBT Issue", "CANoe — Test Environment Not Started",                    "BENCH_DOWN"),
    ("", "canoe could not be started",                  "CBT Issue", "CANoe — Application Launch Failure",                      "BENCH_DOWN"),
    ("", "measurement could not be started",            "CBT Issue", "CANoe — Measurement Start Failure",                       "BENCH_DOWN"),
    ("", "test environment initialization failed",      "CBT Issue", "Test Framework — Environment Init Failure",               "BENCH_DOWN"),
    ("", "license not available",                       "CBT Issue", "CANoe/Tool — License Server Unreachable",                 "BENCH_DOWN"),
    # ENVIRONMENT: Jenkins / CI Infra
    ("", "jenkins error",                               "CBT Issue", "Jenkins — CI Pipeline Execution Error",                   "BENCH_DEGRADED"),
    ("", "workspace not found",                         "CBT Issue", "Jenkins — Workspace Missing (Build Infra Issue)",         "BENCH_DEGRADED"),
    ("", "artifact download failed",                    "CBT Issue", "Jenkins — Software Artifact Download Failure",            "BENCH_DEGRADED"),
    ("", "python script failed to start",               "CBT Issue", "CBT Script — Python Test Script Launch Failure",          "BENCH_DEGRADED"),
]

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
    return f"""You are an Expert Automotive ECU Software Test Analyst. Classify the following CBT failure.

PROJECT CONTEXT:
- Build Number: {build_data.get("build_number", "N/A")}
- Project: {build_data.get("project", "N/A")}

CLASSIFICATION RULES:

[Category A] SOFTWARE DEFECT — ECU Logic Error
Select when logs show DIRECT ECU behavioral failures:
  - Sleep/Power Management: "ECU is not sleeping within timeout of" → ECU sleep state machine defect
  - ECU State: "ECU is not in Normal Operation", "Normal Operation Failed" → ECU boot/state-machine defect  
  - DTC Logic: "DTC [code] is not available", "DTC [code] not set" → Diagnostic handler defect
  - UDS Response: "Expected response code 01 was not found", "NRC received" → UDS service layer defect
  - CAN Timing: "Minimum cycle time violation for CAN message", "Maximum cycle time violation" → ECU CAN scheduler defect
  - CPU Performance: "CPU load exceeded", "Maneuver CPU Load" + "verdict" + "failed" → CPU budget exceeded defect
  - Feature Logic: "HWA did not rotate", "ABS maneuver not proceeding", "EPS torque not applied" → Feature control algorithm defect
  - Calibration: "Calibration status is not CAL_COMPLETE", "Calibration verification failed" → Calibration module defect
  - Memory: "NVRAM read failed", "ROM checksum mismatch" → Memory management defect
  - Watchdog: "Watchdog triggered", "Reset detected after" → Safety monitor defect

[Category B] SUSPECTED CBT ISSUE — MANUAL REVIEW REQUIRED
Select ONLY when:
  - ALL failed step text values are empty (cannot determine root cause)
  - The failure pattern is completely ambiguous with no recognizable ECU signature
  - The testcase step ident suggests tooling but text is empty

REASONING CHAIN (Think step by step before outputting JSON):
Step 1: List all unique non-empty failed step texts.
Step 2: Check each against Category A patterns above.
Step 3: If any Category A pattern matches → fault_category = "Software Issue — [specific type]"
Step 4: If no match and all texts empty → fault_category = "Suspected CBT Issue — Review Required"
Step 5: Write a 1-2 sentence root cause statement.

DEDUPLICATED LOGS:
{failed_logs_summary}

Respond ONLY with valid JSON. No preamble. No line breaks inside strings.
{{
  "fault_category": "Software Issue — [Type]" or "Suspected CBT Issue — Review Required",
  "root_cause_analysis": "1-2 sentences: identify the specific step that failed and the ECU defect it indicates.",
  "affected_component": "Name of component",
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
        steps = tc.get("failed_steps", [])
        
        if not steps:
            compressed_logs.append(f"Testcase: {title} | No detailed step logs (empty).")
            continue
            
        for step in steps:
            raw_text = step.get("text", "")
            sig = raw_text[:80].lower() 
            if sig not in unique_error_signatures:
                unique_error_signatures.add(sig)
                clean_log = raw_text[:250] + "..." if len(raw_text) > 250 else raw_text
                clean_log = clean_log.replace("\n", " ").replace("\r", " ").replace('"', "'")
                compressed_logs.append(f"Testcase: {title} | Step [{step.get('ident')}]: {clean_log}")
                if len(unique_error_signatures) >= 12:
                    break
        if len(unique_error_signatures) >= 12:
            break

    if not compressed_logs:
        return {"category": "Suspected CBT Issue — Review Required", "text": "All step logs are empty. Manual inspection required.", "confidence_score": 30, "analysis_stage": "review_required", "severity": "N/A"}
    
    failed_logs_summary = "\n".join(compressed_logs)
    prompt = _build_llm_prompt(build_data, failed_logs_summary)
    
    try:
        llm = get_llm()
        response = llm(prompt, max_tokens=pipeline_config.LLM_MAX_TOKENS, temperature=pipeline_config.LLM_TEMPERATURE, stop=["</s>", "```"])
        raw_text = response["choices"][0]["text"].strip()
        
        start_idx = raw_text.find('{')
        end_idx = raw_text.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = raw_text[start_idx:end_idx+1]
            json_str = re.sub(r'[\n\r]+', ' ', json_str)
            parsed = json.loads(json_str)
            
            cat = parsed.get("fault_category", "Review Required")
            conf = 82 if len(compressed_logs) >= 3 else 65
            if "Suspected" in cat or "Review" in cat: conf = 30
            
            return {
                "category": cat,
                "text": parsed.get("root_cause_analysis", "No analysis generated."),
                "confidence_score": conf,
                "analysis_stage": "llm",
                "severity": "N/A"
            }
        else:
            raise ValueError("No JSON brackets found.")
    except Exception as e:
        logger.error(f"[pipeline_llm] Inference failed: {e}", exc_info=True)
        return {"category": "Review Required", "text": "Inference engine failed.", "confidence_score": 0, "analysis_stage": "error", "severity": "N/A"}

def analyze_failure(build_data: dict) -> dict:
    try:
        if build_data.get("end_result", "N/A") not in ["FAIL", "TIMEOUT", "EXECUTION_ERROR"]:
            return {"category": "-", "text": "", "confidence_score": 100, "analysis_stage": "skip", "severity": "N/A"}
        
        failed_tcs = [tc for tc in build_data.get("testcases", []) if tc.get("result") in ["FAIL", "TIMEOUT", "EXECUTION_ERROR"]]
        if not failed_tcs:
            return {"category": "Review Required", "text": "Build marked failed but no failed testcases found.", "confidence_score": 0, "analysis_stage": "review_required", "severity": "N/A"}
            
        cbt_hit = None
        cbt_fail_idx = -1
        
        # Stage 0 & 1: Cascade Suppression & Deterministic Scan
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
            
        # Check cascade condition explicitly if >3 failed
        if cbt_hit and len(failed_tcs) > 3 and cbt_fail_idx == 0:
            cbt_fail_idx = 0 # Force cascade treatment

        if cbt_hit:
            cascade_count = len(failed_tcs) - 1 - cbt_fail_idx
            cbt_analysis = f"{cbt_hit['sub_category']} in '{cbt_hit['root_tc']}'. Evidence: \"{cbt_hit['trigger_text']}\"."
            if cascade_count > 0: cbt_analysis += f" {cascade_count} subsequent testcase(s) cascaded."
            
            conf = 97 if cbt_hit["severity"] == "BENCH_DOWN" else 85
            
            if cbt_fail_idx == 0:
                return {
                    "category": "CBT Issue",
                    "sub_category": cbt_hit["sub_category"],
                    "text": f"Root cause: {cbt_analysis} Action: Assign to bench maintenance.",
                    "confidence_score": conf,
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
                    "confidence_score": (conf + llm_res.get("confidence_score", 0)) // 2,
                    "analysis_stage": "mixed",
                    "severity": cbt_hit["severity"],
                    "trigger_step": cbt_hit["trigger_text"]
                }
                
        return _run_llm_on_testcases(build_data, failed_tcs)
    except Exception as e:
        logger.error(f"[pipeline_llm] Fatal error in analyze_failure: {e}", exc_info=True)
        return {"category": "Review Required", "text": "Analysis failed due to internal error.", "confidence_score": 0, "analysis_stage": "error", "severity": "N/A"}