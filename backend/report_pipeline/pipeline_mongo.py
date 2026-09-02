from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import datetime
import logging
from bson.objectid import ObjectId
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from backend.report_pipeline import pipeline_config
import re

logger = logging.getLogger(__name__)

@dataclass
class PipelineFilters:
    lookback_hours: int = 24
    start_date: Optional[str] = None          # ISO string e.g. "2026-08-20"
    end_date: Optional[str] = None
    projects: List[str] = field(default_factory=list)   # multi-select list
    customers: List[str] = field(default_factory=list)
    products: List[str] = field(default_factory=list)
    regions: List[str] = field(default_factory=list)
    domains: List[str] = field(default_factory=list)
    locations: List[str] = field(default_factory=list)
    test_benches: List[str] = field(default_factory=list)
    build_types: List[str] = field(default_factory=list)
    result_filter: List[str] = field(default_factory=list)  # e.g. ["FAIL","TIMEOUT"]

try:
    client = MongoClient(pipeline_config.MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client[pipeline_config.DB_NAME]
    meta_coll = db[pipeline_config.META_COLLECTION]
    reports_coll = db[pipeline_config.REPORTS_COLLECTION]
except PyMongoError as e:
    logger.error(f"[pipeline_mongo] Critical Error: Failed to initialize MongoDB client: {e}")

def normalize_result(raw_result: str) -> str:
    if not raw_result: return "N/A"
    val = str(raw_result).strip().upper()
    if "TIMEOUT" in val: return "TIMEOUT"
    if "EXECUTION" in val or "JENKINS ERROR" in val: return "EXECUTION_ERROR"
    if "BOOTLOADER" in val: return "BOOTLOADER"
    if val in ["PASS", "PASSED", "SUCCESS"]: return "PASS"
    if val in ["PASSEDWITHWARNING", "WARNING", "WARN"]: return "WARNING"
    if val in ["FAIL", "FAILED", "PASSEDWITHFAILURE"]: return "FAIL"
    return "N/A"

def extract_project(project_str: str) -> str:
    if not project_str: return "Unknown"
    project_str = str(project_str).strip()
    if project_str.lower().startswith("project:"):
        return project_str[8:].strip()
    return project_str

def _extract_qg_and_comment(miscinfo_data) -> tuple[str, str]:
    extracted_qg = "N/A"
    extracted_comment = ""
    if not miscinfo_data:
        return extracted_qg, extracted_comment
        
    queue = [miscinfo_data]
    while queue:
        current = queue.pop(0)
        if isinstance(current, dict):
            name_val = str(current.get("name", "")).strip().lower()
            desc_val = current.get("description")
            if name_val in ["qg status", "qg_status"] and desc_val is not None:
                extracted_qg = str(desc_val).strip()
            elif name_val == "comment" and desc_val is not None:
                clean_desc = str(desc_val).strip()
                if clean_desc.lower() not in ["null", "none", ""]:
                    extracted_comment = clean_desc
            queue.extend(current.values())
        elif isinstance(current, list):
            queue.extend(current)
    return extracted_qg, extracted_comment

def fetch_builds(filters: PipelineFilters) -> List[Dict[str, Any]]:
    builds_data = []
    try:
        query = {}
        
        # Time bounding
        if filters.start_date and filters.end_date:
            start_dt = datetime.datetime.fromisoformat(filters.start_date.replace('Z', '+00:00'))
            end_dt = datetime.datetime.fromisoformat(filters.end_date.replace('Z', '+00:00'))
            query["createdAt"] = {"$gte": start_dt, "$lte": end_dt}
            query["_id"] = {"$gte": ObjectId.from_datetime(start_dt)}
        else:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            lookback_time = now_utc - datetime.timedelta(hours=filters.lookback_hours)
            query["createdAt"] = {"$gte": lookback_time}
            query["_id"] = {"$gte": ObjectId.from_datetime(lookback_time)}

        # Array filters
        if filters.projects: query["project"] = {"$in": [re.compile(f"^{p}$", re.I) for p in filters.projects]}
        if filters.customers: query["customer"] = {"$in": filters.customers}
        if filters.products: query["product"] = {"$in": filters.products}
        if filters.regions: query["region"] = {"$in": filters.regions}
        if filters.domains: query["domain"] = {"$in": filters.domains}
        if filters.locations: query["location"] = {"$in": filters.locations}
        if filters.test_benches: query["test_bench"] = {"$in": filters.test_benches}
        if filters.build_types: query["build_type"] = {"$in": filters.build_types}

        cursor = meta_coll.find(query).sort("createdAt", -1).max_time_ms(15000)
        
        for meta in cursor:
            end_res = normalize_result(meta.get("end_result", ""))
            if filters.result_filter and end_res not in filters.result_filter:
                continue

            build_info = {
                "metadataId": meta.get("_id"),
                "build_number": meta.get("build_number", "N/A"),
                "project": extract_project(meta.get("project", "")),
                "customer": meta.get("customer", "N/A"),
                "product": meta.get("product", "N/A"),
                "region": meta.get("region", "N/A"),
                "domain": meta.get("domain", "N/A"),
                "location": meta.get("location", "N/A"),
                "test_bench": meta.get("test_bench", "N/A"),
                "build_type": meta.get("build_type", "N/A"),
                "integration_branch": meta.get("integration_branch", "N/A"),
                "start_time": meta.get("start_time", ""),
                "overall_runtime": meta.get("overall_runtime", 0),
                "end_result": end_res,
                "createdAt": meta.get("createdAt"),
                "testcases": []
            }
            
            report_query = {"metadataId": build_info["metadataId"]}
            try:
                report_doc = reports_coll.find_one(report_query, max_time_ms=15000)
                if report_doc and "data" in report_doc:
                    testmodule = report_doc["data"].get("testmodule", {})
                    testcases_raw = testmodule.get("testcase", [])
                    if isinstance(testcases_raw, dict): testcases_raw = [testcases_raw]
                        
                    for tc in testcases_raw:
                        verdict = tc.get("verdict", {})
                        misc_info = tc.get("miscinfo", {})
                        qg_status, comment = _extract_qg_and_comment(misc_info)
                        tc_result = normalize_result(verdict.get("result", ""))
                        
                        failed_steps = []
                        if tc_result in ["FAIL", "TIMEOUT", "EXECUTION_ERROR"]:
                            teststeps = tc.get("teststep", [])
                            if isinstance(teststeps, dict): teststeps = [teststeps]
                            for step in teststeps:
                                step_res = normalize_result(step.get("result", ""))
                                if step_res in ["FAIL", "TIMEOUT", "EXECUTION_ERROR"]:
                                    step_text = str(step.get("#text", "")).strip().replace("\n", " ")
                                    failed_steps.append({
                                        "ident": step.get("ident", "Unknown_Step"),
                                        "text": step_text
                                    })
                        
                        build_info["testcases"].append({
                            "title": tc.get("title", "Unknown"),
                            "result": tc_result,
                            "testduration": verdict.get("testduration", "0:00:00"),
                            "ident": tc.get("ident", ""),
                            "qg_status": qg_status,
                            "comment": comment,
                            "failed_steps": failed_steps
                        })
            except PyMongoError as e:
                logger.error(f"[pipeline_mongo] Details fetch timeout for {build_info['build_number']}: {e}")
                
            builds_data.append(build_info)
            
    except PyMongoError as e:
        logger.error(f"[pipeline_mongo] Error fetching builds: {e}", exc_info=True)
        
    return builds_data

def fetch_filter_options() -> Dict[str, List[str]]:
    try:
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        lookback_time = now_utc - datetime.timedelta(days=180)
        dummy_id = ObjectId.from_datetime(lookback_time)
        query = {"_id": {"$gte": dummy_id}}

        return {
            "projects": meta_coll.distinct("project", query, maxTimeMS=15000),
            "customers": meta_coll.distinct("customer", query, maxTimeMS=15000),
            "products": meta_coll.distinct("product", query, maxTimeMS=15000),
            "regions": meta_coll.distinct("region", query, maxTimeMS=15000),
            "domains": meta_coll.distinct("domain", query, maxTimeMS=15000),
            "locations": meta_coll.distinct("location", query, maxTimeMS=15000),
            "test_benches": meta_coll.distinct("test_bench", query, maxTimeMS=15000),
            "build_types": meta_coll.distinct("build_type", query, maxTimeMS=15000)
        }
    except PyMongoError as e:
        logger.error(f"[pipeline_mongo] Error fetching filter options: {e}", exc_info=True)
        return {"projects": [], "customers": [], "products": [], "regions": [], "domains": [], "locations": [], "test_benches": [], "build_types": []}