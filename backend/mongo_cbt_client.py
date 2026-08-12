import os
import json
import datetime
from pymongo import MongoClient, errors
from bson import ObjectId

# --- CONFIGURATION ---
MONGO_URI = (
    "mongodb://cbt-reader:Dbg8638tgq0xFHGz2cWhpRPmwEhoeocCfi@frdv08121.zf-world.com:27017,frdv08122.zf-world.com:27017,frdv08123.zf-world.com:27017/adwd6_tools?authSource=adwd6_tools&readPreference=primary&replicaSet=FIII6_MongoDB_central_prod_RS"
)
DB_NAME = "adwd6_tools"
META_COLLECTION_NAME = "bms.stage.cbt.metadata.reports"
REPORTS_COLLECTION_NAME = "bms.stage.cbt.reports"

# --- PROJECTIONS ---
# Projection to isolate testcases and avoid fetching heavy nested teststep arrays
TESTCASE_PROJECTION = {
    "_id": 1,
    "metadataId": 1,
    "createdAt": 1,
    "data.testmodule.verdict": 1,
    "data.testmodule.testcase.title": 1,
    "data.testmodule.testcase.verdict": 1,
    "data.testmodule.testcase.ident": 1,
}

# --- SINGLETON DATABASE CONNECTION ---
_client = None

def get_db():
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URI)
    return _client[DB_NAME]

def get_meta_collection():
    return get_db()[META_COLLECTION_NAME]

def get_reports_collection():
    return get_db()[REPORTS_COLLECTION_NAME]

def ensure_indexes(db=None):
    """Creates indexes on both metadata and reports collections."""
    try:
        meta_col = get_meta_collection()
        reports_col = get_reports_collection()
        
        # Indexes for Stage 1 (Metadata)
        meta_col.create_index("build_number")
        meta_col.create_index("project")
        meta_col.create_index("customer")
        meta_col.create_index("product")
        meta_col.create_index("createdAt")
        meta_col.create_index([("project", 1), ("createdAt", -1)])
        meta_col.create_index([("project", 1), ("product", 1), ("customer", 1), ("createdAt", -1)])
        
        # Indexes for Stage 2 (Reports)
        reports_col.create_index("metadataId")
        reports_col.create_index("createdAt")
        
        print("MongoDB CBT Two-Stage indexes verified.")
    except Exception as e:
        print(f"Warning: Could not create/verify MongoDB indexes: {e}")

# --- HELPERS ---
def normalize_result(raw: str) -> str:
    if not raw:
        return "N/A"
    r = str(raw).strip().upper()
    if r in ("PASS", "PASSED", "SUCCESS"): return "PASS"
    if r in ("PASSEDWITHWARNING", "WARNING", "WARN"): return "WARNING"
    if r in ("FAIL", "FAILED", "PASSEDWITHFAILURE"): return "FAIL"
    if "TIMEOUT" in r: return "TIMEOUT"
    if "EXECUTION" in r or "JENKINS ERROR" in r: return "EXECUTION_ERROR"
    if "BOOTLOADER" in r: return "BOOTLOADER"
    return "N/A"

def format_metadata_doc(meta_doc: dict) -> dict:
    """Extracts metadata fields from bms.stage.cbt.metadata.reports document."""
    created_at = meta_doc.get("createdAt")
    if isinstance(created_at, datetime.datetime):
        created_at = created_at.isoformat()
    elif isinstance(created_at, dict) and "$date" in created_at:
        created_at = created_at["$date"]

    return {
        "metadata_id": str(meta_doc.get("_id", "")),
        "build_number": str(meta_doc.get("build_number", "")),
        "project": meta_doc.get("project", ""),
        "customer": meta_doc.get("customer", ""),
        "product": meta_doc.get("product", ""),
        "region": meta_doc.get("region", ""),
        "total_result": meta_doc.get("end_result") or meta_doc.get("total_results") or "N/A",
        "test_bench": meta_doc.get("test_bench", ""),
        "build_type": meta_doc.get("build_type", ""),
        "integration_branch": meta_doc.get("integration_branch", ""),
        "start_time": str(meta_doc.get("start_time", "")),
        "overall_runtime": meta_doc.get("overall_runtime", 0),
        "created_at": created_at,
    }

def extract_testcases(report_doc: dict) -> list[dict]:
    """Extracts testcase summaries from bms.stage.cbt.reports document."""
    if not report_doc:
        return []
    
    testcases = report_doc.get("data", {}).get("testmodule", {}).get("testcase", [])
    if not isinstance(testcases, list):
        return []
    
    summary = []
    for tc in testcases:
        res = tc.get("verdict", {}).get("result", "N/A")
        dur = tc.get("verdict", {}).get("testduration", "0:00:00")
        summary.append({
            "title": tc.get("title", "Unknown"),
            "result": normalize_result(res),
            "duration": dur,
            "ident": tc.get("ident", "")
        })
    return summary

# --- TWO-STAGE RETRIEVAL IMPLEMENTATION ---

def search_by_build_number(build_number: str) -> dict | None:
    """
    STAGE 1: Query bms.stage.cbt.metadata.reports by build_number.
    STAGE 2: Query bms.stage.cbt.reports by metadataId for detailed testcases.
    """
    try:
        meta_col = get_meta_collection()
        reports_col = get_reports_collection()
        build_number_str = str(build_number).strip()
        
        # --- STAGE 1: METADATA SEARCH ---
        meta_query_conditions = [{"build_number": build_number_str}]
        if build_number_str.isdigit():
            meta_query_conditions.append({"build_number": int(build_number_str)})

        meta_doc = meta_col.find_one({"$or": meta_query_conditions}, max_time_ms=10000)

        # Fallback to Legacy Single Collection if missing from metadata collection
        if not meta_doc:
            return _search_legacy_by_build_number(build_number_str)

        meta_formatted = format_metadata_doc(meta_doc)
        meta_id = meta_doc["_id"] # ObjectId

        # --- STAGE 2: REPORT DETAILS SEARCH ---
        report_doc = reports_col.find_one(
            {"metadataId": meta_id}, 
            projection=TESTCASE_PROJECTION, 
            max_time_ms=10000
        )

        testcases = extract_testcases(report_doc)
        overall_res = normalize_result(meta_formatted["total_result"])
        
        test_duration = "0:00:00"
        if report_doc:
            test_duration = report_doc.get("data", {}).get("testmodule", {}).get("verdict", {}).get("testduration", "0:00:00")

        return {
            "report_id": str(report_doc.get("_id")) if report_doc else meta_formatted["metadata_id"],
            "metadata": meta_formatted,
            "overall_result": overall_res,
            "test_duration": test_duration,
            "testcases": testcases
        }

    except errors.PyMongoError:
        return {"error": "MongoDB query timed out. Please retry."}

def get_latest_report_for_project(search_term: str) -> dict | None:
    """
    Optimized to query the project field directly without heavy multi-field regex scans,
    preventing timeouts in read-only enterprise environments where indexes cannot be created.
    """
    try:
        meta_col = get_meta_collection()
        reports_col = get_reports_collection()

        boosting_terms = ["latest", "project", "report", "show", "me"]
        clean_term = search_term
        for term in boosting_terms:
            clean_term = clean_term.replace(term, "").strip()
        
        # Fallback if everything was stripped
        if not clean_term:
            clean_term = search_term.strip()

        # Target the project field directly to leverage any existing cluster optimization
        meta_query = {"project": {"$regex": f"{clean_term}", "$options": "i"}}
        
        # Sort by createdAt descending (-1) to grab the most recent up-to-date report
        meta_doc = meta_col.find_one(meta_query, sort=[("createdAt", -1)], max_time_ms=10000)

        if not meta_doc:
            return _search_legacy_by_project(clean_term)

        meta_formatted = format_metadata_doc(meta_doc)
        meta_id = meta_doc["_id"]

        # --- STAGE 2: REPORT DETAILS SEARCH ---
        report_doc = reports_col.find_one(
            {"metadataId": meta_id}, 
            projection=TESTCASE_PROJECTION, 
            max_time_ms=10000
        )

        testcases = extract_testcases(report_doc)
        overall_res = normalize_result(meta_formatted["total_result"])
        
        test_duration = "0:00:00"
        if report_doc:
            test_duration = report_doc.get("data", {}).get("testmodule", {}).get("verdict", {}).get("testduration", "0:00:00")

        return {
            "report_id": str(report_doc.get("_id")) if report_doc else meta_formatted["metadata_id"],
            "metadata": meta_formatted,
            "overall_result": overall_res,
            "test_duration": test_duration,
            "testcases": testcases
        }

    except errors.PyMongoError:
        return {"error": "MongoDB query timed out. Please retry."}

def get_summary_last_24h() -> dict:
    """
    Executes fast aggregations directly on the light metadata collection.
    """
    try:
        meta_col = get_meta_collection()
        yesterday = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
        
        cursor = meta_col.find({"createdAt": {"$gte": yesterday}}, max_time_ms=10000)
        
        total_builds = 0
        statuses = {}
        projects_active = set()
        recent_failures = []

        for meta_doc in cursor:
            total_builds += 1
            meta = format_metadata_doc(meta_doc)
            res = normalize_result(meta["total_result"])
            
            statuses[res] = statuses.get(res, 0) + 1
            
            proj = meta.get("project")
            if proj:
                projects_active.add(proj)
                
            if res in ("FAIL", "TIMEOUT", "EXECUTION_ERROR"):
                recent_failures.append({
                    "project": proj,
                    "build_number": meta.get("build_number", "Unknown"),
                    "result": res,
                    "date": meta.get("created_at")
                })

        return {
            "period": "Last 24 Hours",
            "total_builds": total_builds,
            "status_breakdown": statuses,
            "active_projects": list(projects_active),
            "recent_failures": recent_failures[:15]
        }
    except errors.PyMongoError:
        return {"error": "MongoDB query timed out. Please retry."}

# --- FALLBACK FOR LEGACY DOCUMENTS ---
def _search_legacy_by_build_number(build_number: str) -> dict | None:
    reports_col = get_reports_collection()
    query_conditions = [
        {"metadata.build_number": int(build_number) if build_number.isdigit() else build_number},
        {"data.testmodule.sut.info": {"$elemMatch": {"name": "BMS_BUILD_NUMBER", "description": build_number}}}
    ]
    doc = reports_col.find_one({"$or": query_conditions}, projection=TESTCASE_PROJECTION, max_time_ms=10000)
    if not doc:
        return None
    
    embedded = doc.get("metadata", {}) or {}
    return {
        "report_id": str(doc.get("_id")),
        "metadata": {
            "build_number": str(embedded.get("build_number", build_number)),
            "project": embedded.get("project", ""),
            "customer": embedded.get("customer", ""),
            "product": embedded.get("product", ""),
            "total_result": embedded.get("end_result", "N/A"),
            "created_at": str(doc.get("createdAt", ""))
        },
        "overall_result": normalize_result(embedded.get("end_result", "N/A")),
        "test_duration": "N/A",
        "testcases": extract_testcases(doc)
    }

def _search_legacy_by_project(project_name: str) -> dict | None:
    reports_col = get_reports_collection()
    query = {"$or": [
        {"metadata.project": {"$regex": f"^{project_name}$", "$options": "i"}},
        {"data.testmodule.sut.info": {"$elemMatch": {"name": "Project", "description": {"$regex": f"^{project_name}$", "$options": "i"}}}}
    ]}
    doc = reports_col.find_one(query, projection=TESTCASE_PROJECTION, sort=[("createdAt", -1)], max_time_ms=10000)
    if not doc:
        return None
    
    embedded = doc.get("metadata", {}) or {}
    return {
        "report_id": str(doc.get("_id")),
        "metadata": {
            "build_number": str(embedded.get("build_number", "")),
            "project": embedded.get("project", project_name),
            "customer": embedded.get("customer", ""),
            "product": embedded.get("product", ""),
            "total_result": embedded.get("end_result", "N/A"),
            "created_at": str(doc.get("createdAt", ""))
        },
        "overall_result": normalize_result(embedded.get("end_result", "N/A")),
        "test_duration": "N/A",
        "testcases": extract_testcases(doc)
    }
# --- DEEP METRIC EXTRACTION ENGINE ---

DEEP_PROJECTION = {
    "metadataId": 1,
    "data.testmodule.testcase.title": 1,
    "data.testmodule.testcase.ident": 1,
    "data.testmodule.testcase.teststep.ident": 1,
    "data.testmodule.testcase.teststep.result": 1,
    "data.testmodule.testcase.teststep.#text": 1,
    "data.testmodule.testcase.teststep.tabularinfo": 1
}

def _parse_tabular_info(tab_info):
    """Robustly flattens complex XML-to-JSON tabularinfo, auto-padding missing headers."""
    if not isinstance(tab_info, dict):
        return None
    
    parsed = {"description": str(tab_info.get("description", ""))}
    
    # 1. Extract Headers Safely
    headers = []
    heading_obj = tab_info.get("heading", {})
    if isinstance(heading_obj, dict):
        cell_data = heading_obj.get("cell", [])
        if isinstance(cell_data, list):
            headers = [str(c) if c is not None else "" for c in cell_data]
        elif cell_data is not None:
            headers = [str(cell_data)]
            
    # 2. Extract Rows Safely
    rows = []
    row_data = tab_info.get("row", [])
    if isinstance(row_data, dict):
        row_data = [row_data] # Normalize single row to list
        
    if isinstance(row_data, list):
        for r in row_data:
            if isinstance(r, dict):
                cells = r.get("cell", [])
                if isinstance(cells, list):
                    rows.append([str(c) if c is not None else "" for c in cells])
                elif cells is not None:
                    rows.append([str(cells)])
            elif isinstance(r, list):
                rows.append([str(c) if c is not None else "" for c in r])
                
    # 3. Enterprise Fix: Align header length with the maximum row length
    max_row_len = max([len(r) for r in rows]) if rows else 0
    if len(headers) < max_row_len:
        for i in range(len(headers), max_row_len):
            if i == 0: 
                headers.append("Metric / Parameter")
            else: 
                # If we don't have a header, default to Core 1, Core 2, etc., or Value 1, Value 2
                headers.append(f"Value_{i}")
                
    parsed["headers"] = headers
    parsed["rows"] = rows
    return parsed

def search_deep_metric(build_number: str, metric_query: str) -> dict:
    """
    Dynamically searches through all testcases and teststeps.
    Supports a special "failures" mode for root cause analysis.
    """
    try:
        build_number_str = str(build_number).strip()
        
        # Resolve Document
        meta_col = get_meta_collection()
        reports_col = get_reports_collection()
        
        meta_query = {"$or": [{"build_number": build_number_str}]}
        if build_number_str.isdigit():
            meta_query["$or"].append({"build_number": int(build_number_str)})
            
        meta_doc = meta_col.find_one(meta_query)
        
        if meta_doc:
            report_doc = reports_col.find_one({"metadataId": meta_doc["_id"]}, projection=DEEP_PROJECTION)
        else:
            query_conds = [
                {"metadata.build_number": int(build_number_str) if build_number_str.isdigit() else build_number_str},
                {"data.testmodule.sut.info": {"$elemMatch": {"name": "BMS_BUILD_NUMBER", "description": build_number_str}}}
            ]
            report_doc = reports_col.find_one({"$or": query_conds}, projection=DEEP_PROJECTION)

        if not report_doc:
            return {"error": f"Build {build_number_str} not found."}

        # Determine Search Mode
        is_failure_search = metric_query.strip().lower() in ["failures", "fail", "error", "root cause"]
        query_words = [w.lower() for w in metric_query.split()]
        matches = []
        
        testcases = report_doc.get("data", {}).get("testmodule", {}).get("testcase", [])
        if not isinstance(testcases, list):
            testcases = [testcases]

        for tc in testcases:
            tc_title = str(tc.get("title", ""))
            teststeps = tc.get("teststep", [])
            if not isinstance(teststeps, list):
                teststeps = [teststeps]
                
            for step in teststeps:
                step_ident = str(step.get("ident", ""))
                step_result = normalize_result(step.get("result"))
                
                is_match = False
                
                if is_failure_search:
                    # Root Cause Analysis Mode: Catch all failures
                    if step_result in ["FAIL", "EXECUTION_ERROR", "TIMEOUT"]:
                        is_match = True
                else:
                    # Deep Extraction Mode: Fuzzy Keyword Match
                    search_text = f"{tc_title} {step_ident}".lower()
                    if all(w in search_text for w in query_words):
                        is_match = True
                        
                if is_match:
                    match_data = {
                        "testcase_title": tc_title,
                        "step_identifier": step_ident,
                        "result": step_result
                    }
                    if "#text" in step:
                        match_data["extracted_text"] = str(step["#text"])
                    if "tabularinfo" in step:
                        match_data["extracted_table"] = _parse_tabular_info(step["tabularinfo"])
                        
                    matches.append(match_data)
                    
                    # Increased payload limit to 40 to prevent truncation on heavy metrics
                    if len(matches) >= 40: 
                        break
            if len(matches) >= 40:
                break

        if not matches:
            if is_failure_search:
                return {"message": f"Good news: No failed test steps were found in build {build_number_str}."}
            return {"error": f"Could not find any test steps matching '{metric_query}' in build {build_number_str}."}

        return {
            "build_number": build_number_str, 
            "search_type": "Root Cause Analysis" if is_failure_search else "Deep Metric Extraction", 
            "matches_found": len(matches),
            "data": matches
        }

    except errors.PyMongoError:
        return {"error": "MongoDB query timed out. Please retry."}