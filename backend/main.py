import os
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import FRONTEND_PATH, OLLAMA_BASE_URL, OLLAMA_EMBED_MODEL, OLLAMA_MODEL, validate_settings
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

SYSTEM_PROMPT = """You answer questions using only the retrieved local knowledge below.
Treat the retrieved knowledge as the primary source. If the answer cannot be found there,
clearly say that the information is not available instead of inventing an answer.
Do not claim to have searched any other source. Keep the answer concise and helpful.

Retrieved knowledge:
{context}
"""


class ChatRequest(BaseModel):
    message: str


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


@app.post("/ingest", response_model=IngestResponse)
async def ingest(file: UploadFile = File(...)) -> IngestResponse:
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
def documents() -> dict[str, Any]:
    return {"documents": rag_service.list_documents()}


@app.delete("/documents/{document_id}")
def delete_document(document_id: str) -> dict[str, Any]:
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
async def chat(request: ChatRequest):
    message = request.message.strip()
    if not message:
        return JSONResponse(
            status_code=400,
            content={"detail": "Message cannot be empty."},
        )

    try:
        matches = await rag_service.search(message)
        context = "\n\n".join(
            f"[{match['metadata'].get('filename', 'unknown')}] {match['text']}"
            for match in matches
        )
        reply = await ollama.chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT.format(context=context or "No matching local knowledge was found.")},
                {"role": "user", "content": message},
            ]
        )
    except OllamaError as error:
        logger.exception("Ollama request failed")
        return JSONResponse(
            status_code=503,
            content={"detail": str(error)},
        )
    except Exception:
        logger.exception("Unexpected chat failure")
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
