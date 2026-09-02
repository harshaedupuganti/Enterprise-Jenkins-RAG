# =============================================================================
# DEFAULT CONFIGURATION — All values can be overridden via API request body
# =============================================================================

MONGO_URI = "mongodb://cbt-reader:Dbg8638tgq0xFHGz2cWhpRPmwEhoeocCfi@frdv08121.zf-world.com:27017,frdv08122.zf-world.com:27017,frdv08123.zf-world.com:27017/adwd6_tools?authSource=adwd6_tools&readPreference=primary&replicaSet=FIII6_MongoDB_central_prod_RS"
DB_NAME = "adwd6_tools"
META_COLLECTION = "bms.stage.cbt.metadata.reports"
REPORTS_COLLECTION = "bms.stage.cbt.reports"

# Default lookback window in hours
DEFAULT_LOOKBACK_HOURS = 48

# LLM — local GGUF model
GGUF_MODEL_PATH = r"C:\models\AI LOCAL\Meta-Llama-3-8B-Instruct.Q4_K_M.gguf"
LLM_N_CTX = 2048
LLM_N_THREADS = 6
LLM_N_GPU_LAYERS = 28     # -1 = offload all possible layers to GPU (RTX A3000 6GB)
LLM_MAX_TOKENS = 400
LLM_TEMPERATURE = 0.0

# Output directory for generated Excel files
OUTPUT_DIR = "./report_outputs"