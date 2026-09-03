from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import datetime
import logging
import re
from bson.objectid import ObjectId
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from backend.report_pipeline import pipeline_config

logger = logging.getLogger(__name__)

@dataclass
class PipelineFilters:
    lookback_hours: int = 24
    start_date: Optional[str] = None          
    end_date: Optional[str] = None
    projects: List[str] = field(default_factory=list)   
    customers: List[str] = field(default_factory=list)
    products: List[str] = field(default_factory=list)
    regions: List[str] = field(default_factory=list)
    domains: List[str] = field(default_factory=list)
    locations: List[str] = field(default_factory=list)
    test_benches: List[str] = field(default_factory=list)
    integration_branches: List[str] = field(default_factory=list)
    build_types: List[str] = field(default_factory=list)
    result_filter: List[str] = field(default_factory=list)  

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

        if filters.projects: query["project"] = {"$in": [re.compile(f"^{p}$", re.I) for p in filters.projects]}
        if filters.customers: query["customer"] = {"$in": filters.customers}
        if filters.products: query["product"] = {"$in": filters.products}
        if filters.regions: query["region"] = {"$in": filters.regions}
        if filters.domains: query["domain"] = {"$in": filters.domains}
        if filters.locations: query["location"] = {"$in": filters.locations}
        if filters.test_benches: query["test_bench"] = {"$in": filters.test_benches}
        if filters.integration_branches: query["integration_branch"] = {"$in": filters.integration_branches}
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
                                step_text = str(step.get("#text", "")).strip().replace("\n", " ")
                                
                                # NEW LOGIC: Catch NA/WARN steps if they contain actual error text from retry loops
                                text_lower = step_text.lower()
                                is_hard_fail = step_res in ["FAIL", "TIMEOUT", "EXECUTION_ERROR"]
                                is_hidden_error = step_res in ["N/A", "WARNING"] and any(kw in text_lower for kw in ["error", "fail", "timeout"])
                                
                                if is_hard_fail or is_hidden_error:
                                    failed_steps.append({
                                        "ident": step.get("ident", "Unknown_Step"),
                                        "text": step_text
                                    })
                        
                        build_info["testcases"].append({
                            "title": tc.get("title", "Unknown"),
                            "description": tc.get("description", ""), # EXTRACT TEST INTENT
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

def fetch_filter_options() -> Dict[str, Any]:
    import os
    import json
    
    CACHE_FILE = os.path.join("backend", "report_pipeline", "hierarchy_cache.json")
    
    # 1. Try to serve from lightning-fast cache first
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return {"hierarchy": json.load(f), "regions": ["AP", "EU", "NA", "MITSUBISHI"]}
        except Exception as e:
            logger.error(f"[pipeline_mongo] Cache read failed, falling back to DB: {e}")

    # 2. Enterprise Fallback: Build cache dynamically if missing
    try:
        logger.info("[pipeline_mongo] Building hierarchy cache dynamically from MongoDB...")
        
        # We reuse the existing `meta_coll` connection defined at the top of the file
        cursor = meta_coll.find({}, {
            "region": 1, "customer": 1, "project": 1, "product": 1, "test_bench": 1, "integration_branch": 1, "_id": 0
        })
        
        unique_tuples = set()
        for doc in cursor:
            reg = str(doc.get("region", "")).strip().upper()
            if reg in ["EU", "EUROPE"]: reg = "EU"
            elif reg in ["NA", "NORTHAMERICA", "NORTH AMERICA", "USA"]: reg = "NA"
            elif reg in ["AP", "ASIAPACIFIC", "ASIA PACIFIC", "ASIA", "INDIA"]: reg = "AP"
            elif "MITSUBISHI" in reg: reg = "MITSUBISHI"
            else: reg = reg or "OTHER"

            cust = str(doc.get("customer", "")).strip().upper()
            proj = str(doc.get("project", "")).strip()
            if proj.lower().startswith("project:"): proj = proj[8:].strip()
            
            prod = str(doc.get("product", "")).strip().upper()
            bench = str(doc.get("test_bench", "")).strip()
            branch = str(doc.get("integration_branch", "")).strip()

            # Safely capture customers even if project/product fields are blank in MongoDB
            if cust and cust != "NONE":
                unique_tuples.add((
                    reg, 
                    cust, 
                    proj if proj else "N/A", 
                    prod if prod else "N/A", 
                    bench if bench else "N/A", 
                    branch if branch else "N/A"
                ))

        hierarchy = [
            {"region": t[0], "customer": t[1], "project": t[2], "product": t[3], "test_bench": t[4], "integration_branch": t[5]}
            for t in sorted(unique_tuples)
        ]

        # Save the new cache file automatically so the next API call is instant
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(hierarchy, f)

        return {"hierarchy": hierarchy, "regions": ["AP", "EU", "NA", "MITSUBISHI"]}
        
    except PyMongoError as e:
        logger.error(f"[pipeline_mongo] Error building hierarchy: {e}", exc_info=True)
        return {"hierarchy": [], "regions": ["AP", "EU", "NA", "MITSUBISHI"]}