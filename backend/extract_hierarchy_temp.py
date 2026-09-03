import json
import os
from pymongo import MongoClient

# Database connection
MONGO_URI = (
    "mongodb://cbt-reader:Dbg8638tgq0xFHGz2cWhpRPmwEhoeocCfi@"
    "frdv08121.zf-world.com:27017,frdv08122.zf-world.com:27017,frdv08123.zf-world.com:27017/"
    "adwd6_tools?authSource=adwd6_tools&readPreference=primary&replicaSet=FIII6_MongoDB_central_prod_RS"
)
DB_NAME = "adwd6_tools"
COLLECTION_NAME = "bms.stage.cbt.metadata.reports"
OUTPUT_FILE = os.path.join("backend", "report_pipeline", "hierarchy_data.json")

def normalize_region(raw: str) -> str:
    if not raw: return "OTHER"
    r = str(raw).strip().upper()
    if r in ["EU", "EUROPE"]: return "EU"
    if r in ["NA", "NORTHAMERICA", "NORTH AMERICA", "USA"]: return "NA"
    if r in ["AP", "ASIAPACIFIC", "ASIA PACIFIC", "ASIA", "INDIA"]: return "AP"
    if "MITSUBISHI" in r: return "MITSUBISHI"
    return r

def extract_clean_project(proj: str) -> str:
    if not proj: return "Unknown"
    p = str(proj).strip()
    if p.lower().startswith("project:"): return p[8:].strip()
    return p

def main():
    print("⏳ Connecting to MongoDB...")
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
    db = client[DB_NAME]
    coll = db[COLLECTION_NAME]

    print("🔍 Fetching unique Region -> Customer -> Project -> Product -> Bench -> Branch tuples...")
    cursor = coll.find(
        {},
        {"region": 1, "customer": 1, "project": 1, "product": 1, "test_bench": 1, "integration_branch": 1, "_id": 0}
    ).max_time_ms(60000)

    unique_tuples = set()
    total_count = 0

    for doc in cursor:
        total_count += 1
        reg = normalize_region(doc.get("region", ""))
        cust = str(doc.get("customer", "")).strip().upper()
        proj = extract_clean_project(doc.get("project", ""))
        prod = str(doc.get("product", "")).strip().upper()
        tb = str(doc.get("test_bench", "")).strip()
        branch = str(doc.get("integration_branch", "")).strip()

        if cust and cust != "NONE" and proj and proj != "Unknown":
            unique_tuples.add((
                reg, cust, proj, 
                prod if prod else "N/A", 
                tb if tb else "N/A", 
                branch if branch else "N/A"
            ))

    print(f"✅ Processed {total_count} documents. Found {len(unique_tuples)} unique combinations.")

    records = [
        {
            "region": t[0], "customer": t[1], "project": t[2], 
            "product": t[3], "test_bench": t[4], "integration_branch": t[5]
        }
        for t in sorted(unique_tuples)
    ]

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    print(f"🎉 Static hierarchy saved to: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()