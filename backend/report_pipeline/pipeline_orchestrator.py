from dataclasses import dataclass, field
from typing import List, Optional, Dict
import datetime
import json
import logging
import asyncio
import os
from backend.report_pipeline.pipeline_mongo import fetch_builds, PipelineFilters
from backend.report_pipeline.pipeline_llm import analyze_failure
from backend.report_pipeline.pipeline_excel import generate_report
from backend.report_pipeline.pipeline_email_builder import build_email
from backend.report_pipeline.pipeline_email_sender import send_email

logger = logging.getLogger(__name__)

@dataclass
class EmailConfig:
    to_addresses: List[str]
    cc_addresses: List[str] = field(default_factory=list)

@dataclass
class PipelineResult:
    success: bool
    builds_processed: int
    failed_builds: int
    excel_path: Optional[str]
    email_sent: bool
    error: Optional[str]
    kpis: dict
    analysis_summary: dict

def _calculate_kpis(builds: list[dict]) -> dict:
    total = len(builds)
    passed = sum(1 for b in builds if b.get("end_result") == "PASS")
    failed = sum(1 for b in builds if b.get("end_result") in ["FAIL", "TIMEOUT", "EXECUTION_ERROR"])
    warnings = sum(1 for b in builds if b.get("end_result") == "WARNING")
    pass_rate = f"{(passed / total * 100):.1f}%" if total > 0 else "0.0%"
    return {"total": total, "passed": passed, "failed": failed, "warnings": warnings, "pass_rate": pass_rate}

def _append_to_history(result: PipelineResult, filters: PipelineFilters):
    try:
        history_file = "report_history.json"
        history = []
        if os.path.exists(history_file):
            with open(history_file, "r") as f:
                history = json.load(f)
        
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "scope": f"Last {filters.lookback_hours}h",
            "builds": result.builds_processed,
            "success": result.success,
            "email_sent": result.email_sent,
            "error": result.error
        }
        history.insert(0, entry)
        with open(history_file, "w") as f:
            json.dump(history[:20], f, indent=2)
    except Exception as e:
        logger.error(f"Failed to write report history: {e}")

async def run_pipeline(filters: PipelineFilters, email_config: EmailConfig, job_status_dict: dict = None, job_id: str = None) -> PipelineResult:
    try:
        if job_status_dict and job_id:
            job_status_dict[job_id]["progress_message"] = "Fetching builds from MongoDB..."
            
        builds = await asyncio.to_thread(fetch_builds, filters)
        if not builds:
            res = PipelineResult(True, 0, 0, None, False, "No builds found matching criteria", {}, {})
            _append_to_history(res, filters)
            return res

        kpis = _calculate_kpis(builds)
        failed_builds = [b for b in builds if b.get("end_result") in ["FAIL", "TIMEOUT", "EXECUTION_ERROR"]]
        failure_analyses = {}
        analysis_summary = {"CBT Issue": 0, "Software Issue": 0, "Review Required": 0, "Multiple Issues (SW + CBT)": 0}

        total_failed = len(failed_builds)
        for idx, build in enumerate(failed_builds, 1):
            if job_status_dict and job_id:
                job_status_dict[job_id]["progress_message"] = f"Running AI analysis on {total_failed} failed builds ({idx}/{total_failed})..."
            
            analysis = await asyncio.to_thread(analyze_failure, build)
            failure_analyses[str(build.get("build_number"))] = analysis
            cat = analysis.get("category", "Review Required")
            if "Multiple Issues" in cat: analysis_summary["Multiple Issues (SW + CBT)"] += 1
            elif "CBT Issue" in cat: analysis_summary["CBT Issue"] += 1
            elif "Software Issue" in cat: analysis_summary["Software Issue"] += 1
            else: analysis_summary["Review Required"] += 1

        if job_status_dict and job_id:
            job_status_dict[job_id]["progress_message"] = "Generating Excel report..."
        excel_path = await asyncio.to_thread(generate_report, builds, failure_analyses)

        if job_status_dict and job_id:
            job_status_dict[job_id]["progress_message"] = "Building HTML email..."
        html_body, subject = build_email(builds, kpis, failure_analyses, filters.__dict__)

        if job_status_dict and job_id:
            job_status_dict[job_id]["progress_message"] = "Sending email via Outlook..."
        send_res = await asyncio.to_thread(send_email, subject, html_body, excel_path, email_config.to_addresses, email_config.cc_addresses)

        res = PipelineResult(
            success=send_res["success"],
            builds_processed=len(builds),
            failed_builds=total_failed,
            excel_path=excel_path,
            email_sent=send_res["success"],
            error=send_res["error"],
            kpis=kpis,
            analysis_summary=analysis_summary
        )
        _append_to_history(res, filters)
        return res
    except Exception as e:
        logger.error(f"[pipeline_orchestrator] Pipeline failed: {e}", exc_info=True)
        res = PipelineResult(False, 0, 0, None, False, str(e), {}, {})
        _append_to_history(res, filters)
        return res