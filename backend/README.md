# RAG Engine Backend (FastAPI & LangChain)

This directory contains the Python FastAPI backend that powers the Enterprise RAG Assistant. It utilizes LangChain to route queries to Azure OpenAI and a suite of specialized infrastructure tools.

## Core Components
* FastAPI Server (main.py): Exposes the /api/chat endpoint and handles CORS middleware.
* RAG Engine (rag_engine.py): Manages the LLM system prompt, tool routing, and context window optimization.
* Token Tracker (token_tracker.py): Silently logs OpenAI token usage (prompt/completion) and cost to a CSV file (token_usage_log.csv).

## AI Tools & Routing
The AI agent is equipped with six specialized tools:
1. get_live_jenkins_inventory: Fetches real-time node states directly from the Jenkins API.
2. get_cbt_report_by_build_number: Retrieves a specific test report via its BMS build number.
3. get_latest_cbt_report_for_project: Retrieves the most recent report for a specific project name.
4. get_cbt_build_summary_last_24h: Aggregates statistics for CBT builds over any specified timeframe (hours or dates).
5. get_cbt_deep_metric: Extracts specific nested data like CPU load, power consumption, or failures.
6. get_cbt_knowledge_base: Queries static local JSON files for architectural definitions and dashboards.

## Environment Variables (.env)
The backend requires a .env file in the root backend directory to authenticate with Azure OpenAI and Jenkins. Required keys typically include:
* AZURE_DEPLOYMENT_NAME
* AZURE_OPENAI_API_VERSION
* AZURE_OPENAI_ENDPOINT
* AZURE_OPENAI_API_KEY

## Virtual Environment (venv)
It is strictly recommended to run the backend inside a Python Virtual Environment to prevent dependency conflicts with other enterprise tools on the host machine.
* Create: python -m venv venv
* Activate (Windows): .\venv\Scripts\activate
* Install Dependencies: pip install -r requirements.txt

## Local Development
To run the backend locally without PM2:
pip install -r requirements.txt
(uvicorn main:app --host 0.0.0.0 --port 8000) or (uvicorn backend.main:app --reload --reload-dir backend)