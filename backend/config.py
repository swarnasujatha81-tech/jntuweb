import os
from pathlib import Path


BACKEND_DIR = Path(__file__).parent
DATA_DIR = BACKEND_DIR / "data"
DOCUMENTS_DIR = DATA_DIR / "documents"
CHROMA_DIR = DATA_DIR / "chroma"
KNOWLEDGE_PATH = DATA_DIR / "knowledge.txt"
FRONTEND_PATH = BACKEND_DIR.parent / "frontend"

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1000"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))
TOP_K = int(os.getenv("TOP_K", "4"))
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", "20"))
MAX_UPLOAD_SIZE = MAX_UPLOAD_SIZE_MB * 1024 * 1024
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION", "local_documents")
MAX_CONCURRENT_GENERATIONS = int(os.getenv("MAX_CONCURRENT_GENERATIONS", "2"))
CHAT_RATE_LIMIT = int(os.getenv("CHAT_RATE_LIMIT", "20"))
CHAT_RATE_WINDOW_SECONDS = int(os.getenv("CHAT_RATE_WINDOW_SECONDS", "60"))
MAX_CHAT_MESSAGE_LENGTH = int(os.getenv("MAX_CHAT_MESSAGE_LENGTH", "4000"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
ADMIN_COOKIE_SECURE = os.getenv("ADMIN_COOKIE_SECURE", "false").lower() == "true"


def validate_settings() -> None:
    if CHUNK_SIZE <= 0:
        raise ValueError("CHUNK_SIZE must be greater than zero")
    if CHUNK_OVERLAP < 0 or CHUNK_OVERLAP >= CHUNK_SIZE:
        raise ValueError("CHUNK_OVERLAP must be zero or smaller than CHUNK_SIZE")
    if TOP_K <= 0:
        raise ValueError("TOP_K must be greater than zero")
    if MAX_CONCURRENT_GENERATIONS <= 0:
        raise ValueError("MAX_CONCURRENT_GENERATIONS must be greater than zero")
    if CHAT_RATE_LIMIT <= 0:
        raise ValueError("CHAT_RATE_LIMIT must be greater than zero")
    if CHAT_RATE_WINDOW_SECONDS <= 0:
        raise ValueError("CHAT_RATE_WINDOW_SECONDS must be greater than zero")
    if MAX_CHAT_MESSAGE_LENGTH <= 0:
        raise ValueError("MAX_CHAT_MESSAGE_LENGTH must be greater than zero")
    if not ADMIN_USERNAME or not ADMIN_PASSWORD:
        raise ValueError("ADMIN_USERNAME and ADMIN_PASSWORD must be configured")
