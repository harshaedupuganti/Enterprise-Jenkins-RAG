# Enterprise Jenkins RAG & CBT Intelligence Pipeline

An enterprise-grade, dual-engine AI system for Automotive Continuous Build & Test (CBT) environments. This project integrates a **Live Jenkins/MongoDB RAG Chatbot** (powered by Azure OpenAI) with an **Automated Daily Intelligence Report Pipeline** (powered by a local, on-premises LLaMA 3 model).

## 🌟 What This Project Does

This application serves as a unified command center for software and test engineers:

1. **RAG Chatbot Mode (Live Assistant):**
   * Conversational interface to query real-time test bench status via Jenkins.
   * Search and compare historical CBT build metrics across MongoDB.
   * Compare multiple builds side-by-side (e.g., CPU loads, Sleep times, Cycle times).
2. **Report Generator Mode (Daily Intelligence):**
   * Aggregates recent CBT builds from MongoDB using a highly configurable filter UI.
   * Uses a deterministic Pre-Scanner to instantly identify hardware/bench crashes (CBT Issues) and suppress cascading downstream failures.
   * Routes complex, independent software failures to a **local LLaMA 3 8B AI** to diagnose the exact ECU logic defect.
   * Generates a multi-sheet Excel summary and an enterprise-styled HTML email.
   * Dispatches the report directly through the local Windows Microsoft Outlook client.

---

## 🏗️ System Architecture

*   **Frontend:** Next.js (React) + Tailwind CSS. Features a sliding UI toggle between Chat Mode and Report Mode.
*   **Backend API:** FastAPI (Python). Handles chatbot orchestration and background report generation.
*   **Chatbot AI Engine:** LangChain + Azure OpenAI (GPT-4) with custom tooling for Jenkins/MongoDB retrieval.
*   **Report AI Engine:** `llama-cpp-python` running Meta-Llama-3-8B-Instruct (GGUF) locally on GPU/CPU for secure, zero-cloud log analysis.
*   **Database:** MongoDB (Two-stage retrieval pattern for CBT metadata and deeply nested test step logs).
*   **Email Dispatch:** `win32com.client` interfacing natively with the host machine's Microsoft Outlook application.

---

## 📋 Prerequisites

Because of its enterprise integration requirements, this system has specific dependencies:
*   **OS:** Windows 10/11 (Required for `win32com` Outlook automation).
*   **Email:** Microsoft Outlook desktop client installed and logged in.
*   **Runtime:** Python 3.10+ and Node.js 18+.
*   **Local LLM:** A local copy of the `Meta-Llama-3-8B-Instruct.Q4_K_M.gguf` model.
*   **Hardware:** An NVIDIA GPU (e.g., RTX A3000) is highly recommended for LLaMA 3 inference acceleration, though CPU-only fallback is supported.

---

## 🚀 Installation & Setup

### 1. Clone & Environment
Clone the repository and set up a Python virtual environment:
git clone <repository-url>
cd EnterpriseRAG
python -m venv venv
venv\Scripts\activate

### 2. Backend Dependencies
Install standard Python dependencies:
pip install -r requirements.txt

**Install Local LLM Engine (llama-cpp-python):**
*For NVIDIA GPU Acceleration (cuBLAS):*
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
or 
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/vulkan --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host abetlen.github.io --force-reinstall --no-cache-dir --only-binary=llama-cpp-python

*For CPU Only:*
pip install llama-cpp-python

### 3. Download the Local Model
1. Download Meta-Llama-3-8B-Instruct.Q4_K_M.gguf from HuggingFace (QuantFactory).
2. Place it in a directory on your machine (e.g., C:\models\AI LOCAL\Meta-Llama-3-8B-Instruct.Q4_K_M.gguf).

### 4. Frontend Dependencies
cd frontend
npm install
cd ..

### 5. Environment Variables
Create a .env file in the root directory based on the provided .env.example:
# Azure OpenAI config for the Chatbot
AZURE_DEPLOYMENT_NAME=gpt-4
AZURE_OPENAI_API_VERSION=2023-05-15
AZURE_OPENAI_ENDPOINT=https://your-endpoint.openai.azure.com/
AZURE_OPENAI_API_KEY=your-key-here

# Set to true to mock Outlook (saves email as HTML locally instead of sending)
MOCK_OUTLOOK=false

# Set to true to mock the local LLaMA 3 model (for faster UI testing)
MOCK_LLM=false

# Path to your downloaded GGUF model
GGUF_MODEL_PATH=C:\models\AI LOCAL\Meta-Llama-3-8B-Instruct.Q4_K_M.gguf

---

## 💻 How to Run

You will need two terminal windows.

**Terminal 1: Start the FastAPI Backend**
venv\Scripts\activate
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
or
uvicorn backend.main:app --reload --reload-dir backend 

**Terminal 2: Start the Next.js Frontend**
cd frontend
npm run dev

The application will be available at http://localhost:3000.

---

## 🛠️ Usage Guide

### 💬 Chat Mode (Default)
*   **Bench Status:** Ask "What is the status of bench HDRC01586?" The agent will query Jenkins and respond.
*   **Multi-Build Comparison:** Ask "Compare CPU load between builds 1466646 and 1466284." The AI will fetch the specific metric from MongoDB and generate a markdown comparison table identifying the "Winner."

### 📊 Report Mode
1. Click the **"Switch to Report Mode"** toggle button below the ZF logo on the left sidebar.
2. **Configure Scope:** Select domains, projects, date ranges, and test benches from the dropdowns (populated dynamically from MongoDB).
3. **Preview:** Click "Preview Builds" to see exactly how many builds match your criteria.
4. **Recipients:** Enter the target email addresses in the "To" and "CC" tag inputs.
5. **Generate & Send:** Click the blue generate button. The pipeline will run asynchronously in the background:
    *   Fetching logs.
    *   Running the Pre-Scanner to find hardware failures.
    *   Running LLaMA 3 to diagnose ECU software defects.
    *   Building the Excel workbook and inline HTML email.
    *   Triggering your local Outlook client to dispatch the message.
6. **Download:** Once successful, you can download the generated Excel directly from the UI.

---

## 📁 Key File Structure

EnterpriseRAG/
├── backend/
│   ├── main.py                     # FastAPI entry point & API routes
│   ├── rag_engine.py               # Chatbot logic, LangChain agent, tools
│   ├── mongo_cbt_client.py         # Chatbot MongoDB search utilities
│   └── report_pipeline/            # 📦 Automated Reporting Engine
│       ├── pipeline_config.py      # Pipeline constants & defaults
│       ├── pipeline_mongo.py       # Two-stage MongoDB log extraction
│       ├── pipeline_llm.py         # LLaMA 3 inference & deterministic pre-scanner
│       ├── pipeline_excel.py       # openpyxl workbook generator
│       ├── pipeline_email_builder.py # HTML email template builder
│       ├── pipeline_email_sender.py  # win32com Outlook dispatcher
│       └── pipeline_orchestrator.py  # Async pipeline coordinator
├── frontend/
│   ├── components/
│   │   ├── ChatInterface.jsx       # Main Chat UI & toggle switch
│   │   └── ReportModePanel.jsx     # Grafana-style dashboard for report config
├── .env.example
└── requirements.txt