import os
import json
import datetime
from pymongo import MongoClient, errors
from bson import ObjectId
import re
import dateutil.parser

# --- CONFIGURATION ---
MONGO_URI = (
    "mongodb://cbt-reader:Dbg8638tgq0xFHGz2cWhpRPmwEhoeocCfi@frdv08121.zf-world.com:27017,frdv08122.zf-world.com:27017,frdv08123.zf-world.com:27017/adwd6_tools?authSource=adwd6_tools&readPreference=primary&replicaSet=FIII6_MongoDB_central_prod_RS"
)
DB_NAME = "adwd6_tools"
META_COLLECTION_NAME = "bms.stage.cbt.metadata.reports"
REPORTS_COLLECTION_NAME = "bms.stage.cbt.reports"

TESTCASE_PROJECTION = {
    "_id": 1,
    "metadataId": 1,
    "createdAt": 1,
    "data.testmodule.verdict": 1,
    "data.testmodule.testcase.title": 1,
    "data.testmodule.testcase.verdict": 1,
    "data.testmodule.testcase.ident": 1,
    "data.testmodule.testcase.miscinfo": 1,
}

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
    try:
        meta_col = get_meta_collection()
        reports_col = get_reports_collection()
        meta_col.create_index("build_number")
        meta_col.create_index("project")
        meta_col.create_index("customer")
        meta_col.create_index("product")
        meta_col.create_index("createdAt")
        meta_col.create_index([("project", 1), ("createdAt", -1)])
        meta_col.create_index([("project", 1), ("product", 1), ("customer", 1), ("createdAt", -1)])
        reports_col.create_index("metadataId")
        reports_col.create_index("createdAt")
        print("MongoDB CBT Two-Stage indexes verified.")
    except Exception as e:
        print(f"Warning: Could not create/verify MongoDB indexes: {e}")

def normalize_result(raw: str) -> str:
    if not raw: return "N/A"
    r = str(raw).strip().upper()
    if r in ("PASS", "PASSED", "SUCCESS"): return "PASS"
    if r in ("PASSEDWITHWARNING", "WARNING", "WARN"): return "WARNING"
    if r in ("FAIL", "FAILED", "PASSEDWITHFAILURE"): return "FAIL"
    if "TIMEOUT" in r: return "TIMEOUT"
    if "EXECUTION" in r or "JENKINS ERROR" in r: return "EXECUTION_ERROR"
    if "BOOTLOADER" in r: return "BOOTLOADER"
    return "N/A"

def format_metadata_doc(meta_doc: dict) -> dict:
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

def _extract_qg_and_comment(miscinfo_data) -> dict:
    extracted = {"qg_status": "N/A", "comment": "N/A"}
    if not miscinfo_data: return extracted
    queue = [miscinfo_data]
    while queue:
        current = queue.pop(0)
        if isinstance(current, dict):
            name_val = str(current.get("name", "")).strip().lower()
            desc_val = current.get("description")
            if name_val == "qg status" and desc_val is not None:
                extracted["qg_status"] = str(desc_val).strip()
            elif name_val == "comment" and desc_val is not None:
                clean_desc = str(desc_val).strip()
                if clean_desc.lower() not in ["null", "none", ""]:
                    extracted["comment"] = clean_desc
            queue.extend(current.values())
        elif isinstance(current, list):
            queue.extend(current)
    return extracted

def extract_testcases(report_doc: dict) -> list[dict]:
    if not report_doc: return []
    testcases = report_doc.get("data", {}).get("testmodule", {}).get("testcase", [])
    if not isinstance(testcases, list): return []
    
    summary = []
    for tc in testcases:
        res = tc.get("verdict", {}).get("result", "N/A")
        dur = tc.get("verdict", {}).get("testduration", "0:00:00")
        title = tc.get("title", "Unknown")
        ident = tc.get("ident", "")
        misc_data = _extract_qg_and_comment(tc.get("miscinfo"))
        summary.append({
            "title": title,
            "result": normalize_result(res),
            "duration": dur,
            "ident": ident,
            "qg_status": misc_data["qg_status"],
            "comment": misc_data["comment"]
        })
    return summary

def search_by_build_number(build_number: str) -> dict | None:
    try:
        meta_col = get_meta_collection()
        reports_col = get_reports_collection()
        build_number_str = str(build_number).strip()
        
        meta_query_conditions = [{"build_number": build_number_str}]
        if build_number_str.isdigit():
            meta_query_conditions.append({"build_number": int(build_number_str)})

        meta_doc = meta_col.find_one({"$or": meta_query_conditions}, max_time_ms=10000)

        if not meta_doc:
            return _search_legacy_by_build_number(build_number_str)

        meta_formatted = format_metadata_doc(meta_doc)
        meta_id = meta_doc["_id"]

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
    try:
        meta_col = get_meta_collection()
        reports_col = get_reports_collection()

        clean_term = search_term
        for term in ["latest", "project", "report", "show", "me", "for", "the"]:
            clean_term = re.sub(f'(?i)\\b{term}\\b', '', clean_term).strip()
        if not clean_term:
            clean_term = search_term.strip()

        six_months_ago = datetime.datetime.utcnow() - datetime.timedelta(days=180)
        time_bound_id = ObjectId.from_datetime(six_months_ago)

        words = [w for w in clean_term.split() if len(w) >= 2]
        
        and_conditions = []
        for word in words:
            word_regex = {"$regex": word, "$options": "i"}
            and_conditions.append({
                "$or": [
                    {"project": word_regex},
                    {"product": word_regex},
                    {"customer": word_regex}
                ]
            })

        meta_query = {"_id": {"$gte": time_bound_id}}
        if and_conditions:
            meta_query["$and"] = and_conditions

        meta_doc = meta_col.find_one(meta_query, sort=[("_id", -1)], max_time_ms=15000)

        if not meta_doc:
            return _search_legacy_by_project(clean_term)

        meta_formatted = format_metadata_doc(meta_doc)
        meta_id = meta_doc["_id"]

        report_doc = reports_col.find_one(
            {"metadataId": meta_id}, 
            projection=TESTCASE_PROJECTION, 
            max_time_ms=15000
        )

        testcases = extract_testcases(report_doc)
        return {
            "report_id": str(report_doc.get("_id")) if report_doc else meta_formatted["metadata_id"],
            "metadata": meta_formatted,
            "overall_result": normalize_result(meta_formatted.get("total_result", "N/A")),
            "test_duration": report_doc.get("data", {}).get("testmodule", {}).get("verdict", {}).get("testduration", "0:00:00") if report_doc else "0:00:00",
            "testcases": testcases
        }

    except errors.PyMongoError as e:
        print(f"MongoDB Error in get_latest: {e}")
        return {"error": "MongoDB query timed out or failed. Please retry."}

def _search_legacy_by_project(project_name: str) -> dict | None:
    try:
        reports_col = get_reports_collection()
        six_months_ago = datetime.datetime.utcnow() - datetime.timedelta(days=180)
        time_bound_id = ObjectId.from_datetime(six_months_ago)

        words = [w for w in project_name.split() if len(w) >= 2]
        and_conditions = []
        for word in words:
            word_regex = {"$regex": word, "$options": "i"}
            and_conditions.append({
                "$or": [
                    {"metadata.project": word_regex},
                    {"metadata.customer": word_regex},
                    {"metadata.product": word_regex},
                    {"data.testmodule.sut.info": {"$elemMatch": {"name": "Project", "description": word_regex}}}
                ]
            })

        query = {"_id": {"$gte": time_bound_id}}
        if and_conditions:
            query["$and"] = and_conditions

        doc = reports_col.find_one(query, projection=TESTCASE_PROJECTION, sort=[("_id", -1)], max_time_ms=15000)
        
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
    except Exception:
        return None

def get_summary_last_24h(hours: int = 24, start_date: str = None, end_date: str = None, project: str = None) -> dict:
    try:
        meta_col = get_meta_collection()
        query = {}
        if project: query["project"] = project
            
        if start_date and end_date:
            query["createdAt"] = {
                "$gte": dateutil.parser.parse(start_date),
                "$lte": dateutil.parser.parse(end_date)
            }
        else:
            cutoff_time = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
            query["createdAt"] = {"$gte": cutoff_time}

        cursor = meta_col.find(query, max_time_ms=10000)
        
        total_builds = 0
        statuses = {}
        projects_active = set()
        recent_builds = [] 

        for meta_doc in cursor:
            total_builds += 1
            meta = format_metadata_doc(meta_doc)
            res = normalize_result(meta["total_result"])
            statuses[res] = statuses.get(res, 0) + 1
            proj = meta.get("project")
            if proj: projects_active.add(proj)
            recent_builds.append({
                "project": proj,
                "build_number": meta.get("build_number", "Unknown"),
                "result": res,
                "date": meta.get("created_at")
            })
            
        period_str = f"{start_date} to {end_date}" if start_date and end_date else f"Last {hours} Hours"

        return {
            "period": period_str,
            "total_builds": total_builds,
            "status_breakdown": statuses,
            "active_projects": list(projects_active),
            "recent_builds": recent_builds 
        }
    except errors.PyMongoError:
        return {"error": "MongoDB query timed out. Please retry."}
    except Exception as e:
        return {"error": f"Error parsing parameters: {str(e)}"}

def _search_legacy_by_build_number(build_number: str) -> dict | None:
    reports_col = get_reports_collection()
    query_conditions = [
        {"metadata.build_number": int(build_number) if build_number.isdigit() else build_number},
        {"data.testmodule.sut.info": {"$elemMatch": {"name": "BMS_BUILD_NUMBER", "description": build_number}}}
    ]
    doc = reports_col.find_one({"$or": query_conditions}, projection=TESTCASE_PROJECTION, max_time_ms=10000)
    if not doc: return None
    
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

DEEP_PROJECTION = {
    "metadataId": 1,
    "data.testmodule.testcase.title": 1,
    "data.testmodule.testcase.ident": 1,
    "data.testmodule.testcase.teststep.ident": 1,
    "data.testmodule.testcase.teststep.result": 1,
    "data.testmodule.testcase.teststep.#text": 1,
    "data.testmodule.testcase.teststep.tabularinfo": 1,
    "data.testmodule.testcase.miscinfo": 1
}

def _parse_tabular_info(tab_info):
    if not isinstance(tab_info, dict): return None
    parsed = {"description": str(tab_info.get("description", ""))}
    
    headers = []
    heading_obj = tab_info.get("heading", {})
    if isinstance(heading_obj, dict):
        cell_data = heading_obj.get("cell", [])
        if isinstance(cell_data, list): headers = [str(c) if c is not None else "" for c in cell_data]
        elif cell_data is not None: headers = [str(cell_data)]
            
    rows = []
    row_data = tab_info.get("row", [])
    if isinstance(row_data, dict): row_data = [row_data]
        
    if isinstance(row_data, list):
        for r in row_data:
            if isinstance(r, dict):
                cells = r.get("cell", [])
                if isinstance(cells, list): rows.append([str(c) if c is not None else "" for c in cells])
                elif cells is not None: rows.append([str(cells)])
            elif isinstance(r, list):
                rows.append([str(c) if c is not None else "" for c in r])
                
    max_row_len = max([len(r) for r in rows]) if rows else 0
    if len(headers) < max_row_len:
        for i in range(len(headers), max_row_len):
            if i == 0: headers.append("Metric / Parameter")
            else: headers.append(f"Value_{i}")
                
    parsed["headers"] = headers
    parsed["rows"] = rows
    return parsed

def search_deep_metric(build_number: str, metric_query: str) -> dict:
    try:
        build_number_str = str(build_number).strip()
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

        if not report_doc: return {"error": f"Build {build_number_str} not found."}

        is_failure_search = metric_query.strip().lower() in ["failures", "fail", "error", "root cause"]
        query_words = [w.lower() for w in metric_query.split()]
        matches = []
        
        testcases = report_doc.get("data", {}).get("testmodule", {}).get("testcase", [])
        if not isinstance(testcases, list): testcases = [testcases]

        for tc in testcases:
            tc_title = str(tc.get("title", ""))
            teststeps = tc.get("teststep", [])
            if not isinstance(teststeps, list): teststeps = [teststeps]
                
            for step in teststeps:
                step_ident = str(step.get("ident", ""))
                step_result = normalize_result(step.get("result"))
                is_match = False
                
                if is_failure_search:
                    if step_result in ["FAIL", "EXECUTION_ERROR", "TIMEOUT"]:
                        is_match = True
                else:
                    search_text = f"{tc_title} {step_ident}".lower()
                    if all(w in search_text for w in query_words):
                        is_match = True
                        
                if is_match:
                    match_data = {
                        "testcase_title": tc_title,
                        "step_identifier": step_ident,
                        "result": step_result
                    }
                    if "#text" in step: match_data["extracted_text"] = str(step["#text"])
                    if "tabularinfo" in step: match_data["extracted_table"] = _parse_tabular_info(step["tabularinfo"])
                        
                    matches.append(match_data)
                    if len(matches) >= 40: break
            if len(matches) >= 40: break

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