# 🤖 Enterprise Jenkins RAG Assistant

An enterprise-grade, 24/7 AI-powered Assistant designed to monitor, analyze, and report live statuses for Jenkins test benches, nodes, and infrastructure. Built with Next.js, FastAPI, Azure OpenAI, and PM2.

---

## 🌟 Key Features

* **Real-Time Infrastructure Monitoring:** Directly queries Jenkins API for live computer and bench metrics (Idle, Busy, Offline, Temporarily Offline).
* **IP Masking & Reverse Proxy Security:** Next.js reverse proxy routes all backend requests (`/api/*`) through `127.0.0.1:8000`, hiding internal backend IPs and ports from client browsers.
* **Formatted UI Output:** Markdown-rendered responses with styled bullet points, code blocks, and bold highlights for readable bench reports.
* **24/7 Production Deployment:** Background process management via PM2 with process auto-restart and system reboot persistence.
* **Corporate LAN & VPN Support:** Bound to `0.0.0.0` for network access via hostname or static IP across corporate networks and VPNs.

---

## 🏗️ Architecture Overview

    [ Client Browser (LAN / VPN) ]
                  │
                  ▼ (Port 3000)
        ┌───────────────────┐
        │  Next.js Frontend │  <-- Reverse Proxy (/api/* -> 127.0.0.1:8000)
        └─────────┬─────────┘
                  │ (Internal Localhost)
                  ▼ (Port 8000)
        ┌───────────────────┐
        │  FastAPI Backend  │
        └────┬─────────┬────┘
             │         │
             │         └──────► [ Azure OpenAI GPT-5.1 ]
             │
             └────────────────► [ Jenkins Master API ]

---

## 🚀 Quick Start (Development)

### Prerequisites
* **Node.js**: v18+ 
* **Python**: v3.10+
* **Jenkins Access**: Internal network access to Jenkins master API.

### 1. Backend Setup
Run these commands in your terminal:
> cd EnterpriseRAG
> .\venv\Scripts\activate
> pip install -r requirements.txt
> python run_backend.py

### 2. Frontend Setup
Open a second terminal and run:
> cd frontend
> npm install
> npm run dev

---

## ⚙️ Production Deployment (PM2 24/7)

The application uses a unified `ecosystem.config.js` to manage both frontend and backend processes via PM2.

### Launching the Application
From the project root (`EnterpriseRAG`):
> pm2 delete all
> pm2 start ecosystem.config.js
> pm2 status
> pm2 save

### Checking Application Logs
> pm2 logs rag-backend
> pm2 logs rag-frontend

---

## 🔗 Network Access Links

| Environment | Access Link | Description |
| :--- | :--- | :--- |
| **Host PC (Local)** | `http://localhost:3000` | Access directly on the host server. |
| **Corporate LAN / VPN** | `http://[HOSTNAME]:3000` | Accessible by team members on LAN/VPN using PC Hostname. |
| **IP Fallback** | `http://[HOST_IP]:3000` | Accessible via host IPv4 address. |
| **Backend API Docs** | `http://127.0.0.1:8000/docs` | FastAPI Swagger documentation (host machine only). |