from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict
import logging
from .mongo_cbt_client import ensure_indexes
from backend.rag_engine import get_ai_response
from langchain_community.callbacks import get_openai_callback
from backend.token_tracker import log_token_usage
# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Enterprise RAG Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
try:
    print("Initializing CBT MongoDB indexes...")
    ensure_indexes()
except Exception as e:
    print(f"Warning: Failed to ensure CBT MongoDB indexes on startup. Jenkins features will still work. Error: {e}")

# 1. Update our data model to accept a list of messages instead of a single string
class ChatRequest(BaseModel):
    messages: List[Dict[str, str]]

class ChatResponse(BaseModel):
    answer: str

@app.get("/")
def health_check():
    return {"status": "Backend is running flawlessly!"}

@app.post("/api/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest):
    logger.info(f"Received conversation with {len(request.messages)} messages.")
    try:
        with get_openai_callback() as cb:
            
            # Pass the entire conversation history to the AI engine
            answer = get_ai_response(request.messages)
            # 2. Extract the user's latest query
            last_message = request.messages[-1]
            user_query = last_message.content if hasattr(last_message, 'content') else last_message.get("content", "N/A")      
            # 3. Call separate tracker file silently
            log_token_usage(cb, user_query)
        # 4. Return the answer
        return ChatResponse(answer=answer)
    except Exception as e:
        logger.error(f"Error processing chat: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error while processing the AI request.")