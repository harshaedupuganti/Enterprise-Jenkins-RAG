import os
import json
import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from langchain_community.callbacks import get_openai_callback

from backend.rag_engine import get_ai_response
from backend.token_tracker import log_token_usage
from backend.mongo_cbt_client import ensure_indexes
from backend.report_pipeline.pipeline_mongo import fetch_filter_options, fetch_builds, PipelineFilters
from backend.report_pipeline.pipeline_orchestrator import run_pipeline, EmailConfig
from backend.report_pipeline.pipeline_llm import is_llm_loaded

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Enterprise CBT Intelligence")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PIPELINE_JOBS: Dict[str, dict] = {}
scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def startup_event():
    scheduler.start()
    try:
        print("Initializing CBT MongoDB indexes...")
        ensure_indexes()
    except Exception as e:
        print(f"Warning: Failed to ensure CBT MongoDB indexes on startup. Jenkins features will still work. Error: {e}")

class ChatRequest(BaseModel):
    messages: List[Dict[str, str]]

class ChatResponse(BaseModel):
    answer: str

@app.get("/")
def health_check():
    return {"status": "Backend is running flawlessly!"}

# =============================================================================
# EXISTING RAG CHATBOT ENDPOINT
# =============================================================================
@app.post("/api/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest):
    logger.info(f"Received conversation with {len(request.messages)} messages.")
    try:
        with get_openai_callback() as cb:
            answer = get_ai_response(request.messages)
            last_message = request.messages[-1]
            user_query = last_message.content if hasattr(last_message, 'content') else last_message.get("content", "N/A")      
            log_token_usage(cb, user_query)
        return ChatResponse(answer=answer)
    except Exception as e:
        logger.error(f"Error processing chat: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error while processing the AI request.")

# =============================================================================
# REPORT PIPELINE ENDPOINTS
# =============================================================================
@app.get("/api/report/filter-options")
async def get_filter_options():
    return fetch_filter_options()

@app.post("/api/report/preview")
async def preview_report(payload: dict):
    filters = PipelineFilters(**payload)
    builds = fetch_builds(filters)
    total = len(builds)
    passed = sum(1 for b in builds if b.get("end_result") == "PASS")
    failed = sum(1 for b in builds if b.get("end_result") in ["FAIL", "TIMEOUT", "EXECUTION_ERROR"])
    warnings = sum(1 for b in builds if b.get("end_result") == "WARNING")
    projects = list(set([b.get("project") for b in builds if b.get("project")]))
    
    preview_data = [{"build_number": b.get("build_number"), "project": b.get("project"), 
                     "result": b.get("end_result"), "date": str(b.get("start_time"))} for b in builds[:100]]
                     
    return {
        "total_builds": total,
        "status_breakdown": {"PASS": passed, "FAIL": failed, "WARNING": warnings},
        "active_projects": projects,
        "build_preview": preview_data
    }

async def _background_pipeline_task(job_id: str, filters: PipelineFilters, email_config: EmailConfig):
    try:
        result = await run_pipeline(filters, email_config, PIPELINE_JOBS, job_id)
        PIPELINE_JOBS[job_id]["status"] = "completed" if result.success else "failed"
        PIPELINE_JOBS[job_id]["result"] = result.__dict__
        PIPELINE_JOBS[job_id]["completed_at"] = datetime.now().isoformat()
    except Exception as e:
        PIPELINE_JOBS[job_id]["status"] = "failed"
        PIPELINE_JOBS[job_id]["result"] = {"error": str(e)}

@app.post("/api/report/generate", status_code=202)
async def generate_report(payload: dict, background_tasks: BackgroundTasks):
    filters = PipelineFilters(**payload.get("filters", {}))
    email_data = payload.get("email", {})
    email_config = EmailConfig(to_addresses=email_data.get("to_addresses", []), cc_addresses=email_data.get("cc_addresses", []))
    
    if not email_config.to_addresses:
        raise HTTPException(status_code=400, detail="to_addresses required")
        
    job_id = f"rpt_{int(datetime.now().timestamp())}_{os.urandom(3).hex()}"
    PIPELINE_JOBS[job_id] = {
        "job_id": job_id,
        "status": "running",
        "progress_message": "Initializing pipeline...",
        "started_at": datetime.now().isoformat(),
        "completed_at": None,
        "result": None
    }
    
    background_tasks.add_task(_background_pipeline_task, job_id, filters, email_config)
    return {"job_id": job_id, "status": "queued", "message": f"Pipeline started. Check /api/report/status/{job_id}"}

@app.get("/api/report/status/{job_id}")
async def get_job_status(job_id: str):
    if job_id not in PIPELINE_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    return PIPELINE_JOBS[job_id]

@app.get("/api/report/download/{job_id}")
async def download_report(job_id: str):
    if job_id not in PIPELINE_JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    job = PIPELINE_JOBS[job_id]
    if job["status"] != "completed" or not job["result"] or not job["result"].get("excel_path"):
        raise HTTPException(status_code=400, detail="File not ready or failed to generate")
    file_path = job["result"]["excel_path"]
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File deleted from server")
    return FileResponse(path=file_path, filename=os.path.basename(file_path))

@app.get("/api/report/llm-status")
async def get_llm_status():
    from backend.report_pipeline import pipeline_config
    return {
        "llm_loaded": is_llm_loaded(),
        "model_path": pipeline_config.GGUF_MODEL_PATH,
        "model_exists": os.path.exists(pipeline_config.GGUF_MODEL_PATH)
    }

@app.post("/api/report/schedule")
async def schedule_report(payload: dict):
    try:
        with open("report_schedule.json", "w") as f:
            json.dump(payload, f)
        return {"status": "success", "message": "Schedule updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/report/history")
async def get_history():
    if os.path.exists("report_history.json"):
        with open("report_history.json", "r") as f:
            return json.load(f)
    return []

@app.get("/api/report/bench-health")
async def get_bench_health():
    # Provide metrics for your new UI widget
    return {
        "idle": 17, 
        "busy": 14, 
        "offline": 12, 
        "temporarily_offline": 13, 
        "last_updated": datetime.now().strftime("%H:%M:%S")
    }