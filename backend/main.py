import os
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


app = FastAPI(title="My AI Assistant API")

# The frontend is opened locally during development, so allow local browser origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_CHAT_URL = f"{OLLAMA_URL}/api/chat"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
KNOWLEDGE_PATH = Path(__file__).parent / "data" / "knowledge.txt"
FRONTEND_PATH = Path(__file__).parent.parent / "frontend"

SYSTEM_PROMPT = """You are a chatbot that answers questions using the provided knowledge.
Use the provided knowledge as the primary source.
If the answer cannot be found in the knowledge, clearly say that the information is not available instead of inventing an answer.
Keep answers concise and helpful.

Provided knowledge:
{knowledge}
"""


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


def load_knowledge() -> str:
    """Read the current knowledge file on every request so edits take effect immediately."""
    try:
        return KNOWLEDGE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "No local knowledge is available."
    except OSError:
        return "The local knowledge file could not be read."


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse(FRONTEND_PATH / "index.html")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    message = request.message.strip()
    if not message:
        return JSONResponse(
            status_code=400,
            content={"detail": "Message cannot be empty."},
        )

    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT.format(knowledge=load_knowledge()),
            },
            {"role": "user", "content": message},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            ollama_response = await client.post(OLLAMA_CHAT_URL, json=payload)
            ollama_response.raise_for_status()
    except httpx.ConnectError:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Could not connect to Ollama. Make sure Ollama is running on the host PC."
            },
        )
    except httpx.TimeoutException:
        return JSONResponse(
            status_code=504,
            content={"detail": "Ollama took too long to respond."},
        )
    except httpx.HTTPStatusError as error:
        return JSONResponse(
            status_code=502,
            content={"detail": f"Ollama returned an error: {error.response.text}"},
        )
    except httpx.RequestError:
        return JSONResponse(
            status_code=502,
            content={"detail": "The request to Ollama failed."},
        )

    response_data = ollama_response.json()
    reply = response_data.get("message", {}).get("content", "").strip()
    if not reply:
        return JSONResponse(
            status_code=502,
            content={"detail": "Ollama returned an empty response."},
        )

    return ChatResponse(reply=reply)


app.mount("/", StaticFiles(directory=FRONTEND_PATH), name="frontend")
