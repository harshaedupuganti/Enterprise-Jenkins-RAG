# CBT Intelligence Pipeline: Remote GPU Node Setup Guide

**Architecture Overview:**
The CBT Report Generator operates on a decoupled client-server model. The main website and database orchestrator run on a 24/7 office server. To process complex test failure logs quickly, it offloads AI inference to a dedicated GPU PC on the same local network. 

This guide explains how to set up your PC to act as the "Remote GPU Node."

---

## PART 1: Instructions for the GPU Host (Your Colleague)

Your machine will not run the website or the database. It will only run a lightweight, background API microservice that holds the AI model in VRAM and waits for HTTP POST requests from the 24/7 server.

### Prerequisites
* **Python 3.10, 3.11, or 3.12** installed and added to Windows PATH.
* **NVIDIA GPU** with at least 6GB VRAM (e.g., RTX 3060, A3000).
* **Corporate Network Connection:** You must be on the same office LAN/VPN as the 24/7 server.

### Step 1: Download the Model
You need the 4GB instruction-tuned model file.
1. Download the model file: `Meta-Llama-3-8B-Instruct.Q4_K_M.gguf` (Ask the pipeline admin for the exact download link or shared drive location).
2. Save it to a dedicated folder on your C: drive, for example: `C:\models\Meta-Llama-3-8B-Instruct.Q4_K_M.gguf`.

### Step 2: Install the API Server
Open PowerShell and install the required streaming and server dependencies:
```powershell
pip install uvicorn fastapi pydantic-settings sse-starlette starlette-context
```

*Note on Corporate Proxies:* If your company proxy blocks the download of `llama-cpp-python` via terminal, download the pre-compiled `.whl` file via your browser first:
1. Go to: `https://github.com/abetlen/llama-cpp-python/releases`
2. Download the Vulkan wheel for your Python version (e.g., `llama_cpp_python-0.3.35-cp311-cp311-win_amd64.whl`).
3. Install it locally:
```powershell
pip install C:\Users\<Your_User>\Downloads\llama_cpp_python-0.3.35-cp311-cp311-win_amd64.whl --force-reinstall
```

### Step 3: Open the Windows Firewall (Critical)
By default, Windows blocks inbound requests from other PCs. You must open port `8001` so the 24/7 server can ping your GPU.
Open **PowerShell as Administrator** and run:
```powershell
New-NetFirewallRule -DisplayName "Allow LLaMA Server" -Direction Inbound -LocalPort 8001 -Protocol TCP -Action Allow
```

### Step 4: Start the GPU Server
Run this command in PowerShell to load the model into your GPU. Make sure to update the `--model` path to wherever you saved the file in Step 1.
```powershell
python -m llama_cpp.server --model "C:\models\Meta-Llama-3-8B-Instruct.Q4_K_M.gguf" --host 0.0.0.0 --port 8001 --n_gpu_layers -1
```
*Success criteria: The terminal will say `Uvicorn running on http://0.0.0.0:8001`. Do not close this terminal window while you want the AI to remain accessible.*

### Step 5: Send your Hostname to the Admin
Open a new PowerShell tab and type:
```powershell
hostname
```
Send the resulting PC name (e.g., `HDRC12345`) to the CBT Pipeline Admin so they can route traffic to your machine.

---

## PART 2: Instructions for the Pipeline Admin (You)

Once your colleague has completed Part 1 and given you their Hostname (or IPv4 address), you need to update the 24/7 Office Server to point to them instead of your own laptop.

### Step 1: Update the Environment Variables
1. Log into the 24/7 Office PC (e.g., `hdrc50209`).
2. Open the `backend/.env` file.
3. Change the `REMOTE_LLM_URL` to point to your colleague's machine on port 8001:
```env
REMOTE_LLM_URL=http://<COLLEAGUES_HOSTNAME_OR_IP>:8001
```

### Step 2: Restart the Backend Orchestrator
To apply the new environment variable, you must restart the FastAPI server.
1. Open the terminal running `uvicorn` on the 24/7 PC.
2. Press `Ctrl + C` to kill the server.
3. Start it again:
```powershell
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### Step 3: Verify Connection
1. Open the Next.js frontend in your browser.
2. The "Local LLaMA Ready" status indicator in the top right corner of the dashboard will automatically ping your colleague's PC. If it glows green, the pipeline has successfully bridged the network and is utilizing their GPU.