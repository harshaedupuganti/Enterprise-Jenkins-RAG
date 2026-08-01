from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict
import logging

from backend.rag_engine import get_ai_response

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
        # Pass the entire conversation history to the AI engine
        answer = get_ai_response(request.messages)
        return ChatResponse(answer=answer)
    except Exception as e:
        logger.error(f"Error processing chat: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error while processing the AI request.")