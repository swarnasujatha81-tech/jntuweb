import os
import asyncio
import hmac
import logging
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from fastapi import Cookie, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import (
    CHAT_RATE_LIMIT,
    CHAT_RATE_WINDOW_SECONDS,
    ADMIN_COOKIE_SECURE,
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    FRONTEND_PATH,
    MAX_CHAT_MESSAGE_LENGTH,
    MAX_CONCURRENT_GENERATIONS,
    OLLAMA_BASE_URL,
    OLLAMA_EMBED_MODEL,
    OLLAMA_MODEL,
    validate_settings,
)
from ollama_client import OllamaClient, OllamaError
from rag import DocumentDeleteError, DocumentNotFoundError, DocumentProtectedError, IngestionError, RAGService


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)
validate_settings()

app = FastAPI(title="My AI Assistant API")

# The frontend is opened locally during development, so allow local browser origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

ollama = OllamaClient(OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_EMBED_MODEL)
rag_service = RAGService(ollama)
generation_slots = asyncio.Semaphore(MAX_CONCURRENT_GENERATIONS)


class ChatRateLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self.requests: dict[str, deque[float]] = defaultdict(deque)
        self.lock = asyncio.Lock()

    async def allow(self, client_ip: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        async with self.lock:
            timestamps = self.requests[client_ip]
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= self.limit:
                return False
            timestamps.append(now)
            return True


chat_rate_limiter = ChatRateLimiter(CHAT_RATE_LIMIT, CHAT_RATE_WINDOW_SECONDS)
admin_sessions: dict[str, str] = {}
ADMIN_SESSION_COOKIE = "admin_session"
ADMIN_SESSION_MAX_AGE = 8 * 60 * 60

SYSTEM_PROMPT = """You answer questions using only the retrieved local knowledge below.
Treat the retrieved knowledge as the primary source. If the answer cannot be found there,
clearly say that the information is not available instead of inventing an answer.
Do not claim to have searched any other source. Keep the answer concise and helpful.

Retrieved knowledge:
{context}
"""


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_CHAT_MESSAGE_LENGTH)


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class ChatResponse(BaseModel):
    reply: str
    sources: list[dict[str, Any]] = Field(default_factory=list)


class IngestResponse(BaseModel):
    status: str
    filename: str
    document_hash: str
    chunks_added: int
    message: str | None = None


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse(FRONTEND_PATH / "index.html")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


def require_admin(admin_session: str | None = Cookie(default=None, alias=ADMIN_SESSION_COOKIE)) -> str:
    username = admin_sessions.get(admin_session or "")
    if username is None:
        raise HTTPException(status_code=401, detail="Admin authentication required.")
    return username


@app.post("/admin/login")
async def admin_login(login: AdminLoginRequest) -> JSONResponse:
    valid_username = hmac.compare_digest(login.username, ADMIN_USERNAME)
    valid_password = hmac.compare_digest(login.password, ADMIN_PASSWORD)
    if not (valid_username and valid_password):
        logger.warning("Rejected admin login for username %s", login.username)
        return JSONResponse(status_code=401, content={"detail": "Invalid admin credentials."})

    session_token = secrets.token_urlsafe(32)
    admin_sessions[session_token] = ADMIN_USERNAME
    response = JSONResponse(content={"authenticated": True, "username": ADMIN_USERNAME})
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        session_token,
        max_age=ADMIN_SESSION_MAX_AGE,
        httponly=True,
        secure=ADMIN_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return response


@app.post("/admin/logout")
async def admin_logout(admin_session: str | None = Cookie(default=None, alias=ADMIN_SESSION_COOKIE)) -> JSONResponse:
    if admin_session:
        admin_sessions.pop(admin_session, None)
    response = JSONResponse(content={"authenticated": False})
    response.delete_cookie(ADMIN_SESSION_COOKIE, path="/")
    return response


@app.get("/admin/me")
def admin_me(admin: str = Depends(require_admin)) -> dict[str, str | bool]:
    return {"authenticated": True, "username": admin}


@app.post("/ingest", response_model=IngestResponse)
async def ingest(file: UploadFile = File(...), _: str = Depends(require_admin)) -> IngestResponse:
    try:
        result = await rag_service.ingest_upload(file)
    except IngestionError as error:
        return JSONResponse(status_code=400, content={"detail": str(error)})
    except OllamaError as error:
        logger.exception("Embedding failed during ingestion")
        return JSONResponse(status_code=503, content={"detail": str(error)})
    except Exception:
        logger.exception("Unexpected ingestion failure")
        return JSONResponse(status_code=500, content={"detail": "Document ingestion failed."})
    logger.info("Ingestion result: %s", result)
    return IngestResponse(**result)


@app.get("/documents")
def documents(_: str = Depends(require_admin)) -> dict[str, Any]:
    return {"documents": rag_service.list_documents()}


@app.delete("/documents/{document_id}")
def delete_document(document_id: str, _: str = Depends(require_admin)) -> dict[str, Any]:
    try:
        return rag_service.delete_document(document_id)
    except DocumentNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except DocumentProtectedError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except DocumentDeleteError as error:
        logger.exception("Document deletion failed for %s", document_id)
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.post("/chat", response_model=ChatResponse)
async def chat(request: Request, chat_request: ChatRequest):
    client_ip = request.client.host if request.client else "unknown"
    logger.info("Chat request received from %s", client_ip)
    message = chat_request.message.strip()
    if not message:
        return JSONResponse(
            status_code=400,
            content={"detail": "Message cannot be empty."},
        )
    if not await chat_rate_limiter.allow(client_ip):
        logger.warning("Chat rate limit rejected for %s", client_ip)
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many chat requests. Please wait before trying again."},
            headers={"Retry-After": str(CHAT_RATE_WINDOW_SECONDS)},
        )

    try:
        matches = await rag_service.search(message)
        context = "\n\n".join(
            f"[{match['metadata'].get('filename', 'unknown')}] {match['text']}"
            for match in matches
        )
        if generation_slots.locked():
            logger.info("Chat request waiting for generation slot from %s", client_ip)
        async with generation_slots:
            logger.info("Generation started for %s", client_ip)
            reply = await ollama.chat(
                [
                    {"role": "system", "content": SYSTEM_PROMPT.format(context=context or "No matching local knowledge was found.")},
                    {"role": "user", "content": message},
                ]
            )
            logger.info("Generation completed for %s", client_ip)
    except OllamaError as error:
        logger.warning("Generation failed for %s: %s", client_ip, error)
        return JSONResponse(
            status_code=503,
            content={"detail": "The assistant is temporarily unavailable. Please try again shortly."},
        )
    except Exception:
        logger.exception("Unexpected chat failure for %s", client_ip)
        return JSONResponse(
            status_code=500,
            content={"detail": "The chat request failed."},
        )

    sources = [
        {
            "filename": match["metadata"].get("filename", ""),
            "file_type": match["metadata"].get("file_type", ""),
            "page_number": match["metadata"].get("page_number"),
            "chunk_id": match["metadata"].get("chunk_id", ""),
            "source_path": match["metadata"].get("source_path", ""),
            "distance": match.get("distance"),
        }
        for match in matches
    ]
    return ChatResponse(reply=reply, sources=sources)


app.mount("/", StaticFiles(directory=FRONTEND_PATH), name="frontend")
