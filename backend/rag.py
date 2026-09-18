import hashlib
import logging
import re
from pathlib import Path
from typing import Any

import chromadb
from docx import Document
from fastapi import UploadFile
from pypdf import PdfReader

from config import (
    CHROMA_DIR,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    COLLECTION_NAME,
    DOCUMENTS_DIR,
    KNOWLEDGE_PATH,
    MAX_UPLOAD_SIZE,
    TOP_K,
)
from ollama_client import OllamaClient, OllamaError

logger = logging.getLogger(__name__)
ALLOWED_EXTENSIONS = {".txt", ".pdf", ".docx"}


class IngestionError(ValueError):
    pass


class DocumentNotFoundError(ValueError):
    pass


class DocumentProtectedError(ValueError):
    pass


class DocumentDeleteError(RuntimeError):
    pass


class RAGService:
    def __init__(self, ollama: OllamaClient):
        DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        self.ollama = ollama
        self.client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"description": "Local document chunks"},
        )

    @property
    def chunk_count(self) -> int:
        return self.collection.count()

    async def ingest_upload(self, upload: UploadFile) -> dict[str, Any]:
        original_filename = upload.filename or ""
        if not original_filename or any(character in original_filename for character in ("/", "\\", "\x00")):
            raise IngestionError("Filename must be a simple file name without path separators.")
        filename = Path(original_filename).name
        extension = Path(filename).suffix.lower()
        if not filename or extension not in ALLOWED_EXTENSIONS:
            raise IngestionError("Only .txt, .pdf, and .docx files are supported.")

        content = await upload.read(MAX_UPLOAD_SIZE + 1)
        if len(content) > MAX_UPLOAD_SIZE:
            raise IngestionError(f"File exceeds the {MAX_UPLOAD_SIZE // (1024 * 1024)} MB limit.")
        if not content:
            raise IngestionError("The uploaded file is empty.")

        document_hash = hashlib.sha256(content).hexdigest()
        existing = self.collection.get(
            where={"document_hash": document_hash},
            include=["metadatas"],
        )
        if existing.get("ids"):
            return {
                "status": "skipped",
                "filename": filename,
                "document_hash": document_hash,
                "chunks_added": 0,
                "message": "This document is already indexed.",
            }

        destination = DOCUMENTS_DIR / filename
        previous_content = destination.read_bytes() if destination.exists() else None
        destination.write_bytes(content)
        try:
            chunks = self._build_chunks(destination, content, document_hash, extension)
            if not chunks:
                raise IngestionError("No readable text was found in the uploaded file.")
            await self._add_chunks(chunks)
            old_chunks = self.collection.get(
                where={"source_path": str(destination)},
                include=["metadatas"],
            )
            old_ids = [chunk_id for chunk_id in old_chunks.get("ids", []) if chunk_id not in {chunk["id"] for chunk in chunks}]
            if old_ids:
                self.collection.delete(ids=old_ids)
        except Exception:
            if previous_content is None:
                destination.unlink(missing_ok=True)
            else:
                destination.write_bytes(previous_content)
            raise

        return {
            "status": "indexed",
            "filename": filename,
            "document_hash": document_hash,
            "chunks_added": len(chunks),
        }

    async def ensure_knowledge_indexed(self) -> None:
        if not KNOWLEDGE_PATH.exists():
            return
        content = KNOWLEDGE_PATH.read_bytes()
        document_hash = hashlib.sha256(content).hexdigest()
        existing = self.collection.get(where={"document_hash": document_hash}, include=["metadatas"])
        if existing.get("ids"):
            return
        chunks = self._build_chunks(KNOWLEDGE_PATH, content, document_hash, ".txt")
        if chunks:
            await self._add_chunks(chunks)
            old_chunks = self.collection.get(
                where={"source_path": str(KNOWLEDGE_PATH)},
                include=["metadatas"],
            )
            old_ids = [chunk_id for chunk_id in old_chunks.get("ids", []) if chunk_id not in {chunk["id"] for chunk in chunks}]
            if old_ids:
                self.collection.delete(ids=old_ids)
            logger.info("Indexed legacy knowledge.txt into ChromaDB (%d chunks)", len(chunks))

    async def search(self, query: str) -> list[dict[str, Any]]:
        await self.ensure_knowledge_indexed()
        if self.collection.count() == 0:
            return []
        query_embedding = (await self.ollama.embed([query]))[0]
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=TOP_K,
            include=["documents", "metadatas", "distances"],
        )
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        return [
            {
                "text": text,
                "metadata": metadata,
                "distance": distance,
            }
            for text, metadata, distance in zip(documents, metadatas, distances)
        ]

    def list_documents(self) -> list[dict[str, Any]]:
        result = self.collection.get(include=["metadatas"])
        documents: dict[str, dict[str, Any]] = {}
        for metadata in result.get("metadatas", []):
            document_hash = metadata.get("document_hash", "")
            if document_hash and document_hash not in documents:
                source = Path(metadata.get("source_path", ""))
                is_builtin = source.resolve() == KNOWLEDGE_PATH.resolve()
                size_bytes = metadata.get("size_bytes")
                if size_bytes is None and source.is_file():
                    size_bytes = source.stat().st_size
                documents[document_hash] = {
                    "id": document_hash,
                    "filename": metadata.get("filename", ""),
                    "file_type": metadata.get("file_type", ""),
                    "source_path": metadata.get("source_path", ""),
                    "document_hash": document_hash,
                    "chunk_count": 0,
                    "size_bytes": size_bytes,
                    "status": "built-in" if is_builtin else "indexed",
                    "is_builtin": is_builtin,
                }
            if document_hash:
                documents[document_hash]["chunk_count"] += 1
        return list(documents.values())

    def delete_document(self, document_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{64}", document_id):
            raise DocumentNotFoundError("Document was not found.")

        stored = self.collection.get(where={"document_hash": document_id}, include=["metadatas"])
        ids = stored.get("ids", [])
        metadatas = stored.get("metadatas", [])
        if not ids or not metadatas:
            raise DocumentNotFoundError("Document was not found.")

        source_path = Path(metadatas[0].get("source_path", "")).resolve()
        documents_root = DOCUMENTS_DIR.resolve()
        if source_path == KNOWLEDGE_PATH.resolve() or documents_root not in source_path.parents:
            raise DocumentProtectedError("This document is protected and cannot be deleted.")
        if not source_path.is_file():
            raise DocumentNotFoundError("The document file was not found.")

        try:
            self.collection.delete(ids=ids)
        except Exception as error:
            logger.exception("Could not delete Chroma chunks for document %s", document_id)
            raise DocumentDeleteError("Could not remove the document from the search index.") from error

        try:
            source_path.unlink()
        except OSError as error:
            logger.exception("Could not delete source file %s", source_path)
            raise DocumentDeleteError("The search index was updated, but the document file could not be deleted.") from error

        return {"success": True, "message": "Document deleted", "document_id": document_id}

    def _build_chunks(
        self,
        path: Path,
        content: bytes,
        document_hash: str,
        extension: str,
    ) -> list[dict[str, Any]]:
        sections = self._extract_sections(path, content, extension)
        chunks: list[dict[str, Any]] = []
        for section_text, page_number in sections:
            for index, text in enumerate(self._chunk_text(section_text)):
                chunk_id = f"{document_hash[:16]}-{len(chunks):06d}"
                metadata: dict[str, Any] = {
                    "filename": path.name,
                    "file_type": extension.lstrip("."),
                    "source_path": str(path),
                    "document_hash": document_hash,
                    "chunk_id": chunk_id,
                    "size_bytes": len(content),
                }
                if page_number is not None:
                    metadata["page_number"] = page_number
                chunks.append({"id": chunk_id, "text": text, "metadata": metadata})
        return chunks

    async def _add_chunks(self, chunks: list[dict[str, Any]]) -> None:
        embeddings = await self.ollama.embed([chunk["text"] for chunk in chunks])
        self.collection.add(
            ids=[chunk["id"] for chunk in chunks],
            documents=[chunk["text"] for chunk in chunks],
            embeddings=embeddings,
            metadatas=[chunk["metadata"] for chunk in chunks],
        )

    @staticmethod
    def _extract_sections(path: Path, content: bytes, extension: str) -> list[tuple[str, int | None]]:
        if extension == ".txt":
            return [(content.decode("utf-8", errors="replace"), None)]
        if extension == ".pdf":
            reader = PdfReader(str(path))
            return [(page.extract_text() or "", page_number) for page_number, page in enumerate(reader.pages, 1)]
        document = Document(str(path))
        return [("\n".join(paragraph.text for paragraph in document.paragraphs), None)]

    @staticmethod
    def _chunk_text(text: str) -> list[str]:
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return []
        chunks = []
        start = 0
        while start < len(normalized):
            end = min(start + CHUNK_SIZE, len(normalized))
            if end < len(normalized):
                boundary = normalized.rfind(" ", start, end)
                if boundary > start + CHUNK_SIZE // 2:
                    end = boundary
            chunk = normalized[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(normalized):
                break
            start = max(end - CHUNK_OVERLAP, start + 1)
        return chunks
