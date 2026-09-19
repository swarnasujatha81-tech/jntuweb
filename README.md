# My AI Assistant

A self-hosted local RAG chatbot. FastAPI and ChromaDB run in Docker, while Ollama runs on the Windows host. There are no cloud AI APIs, API keys, databases outside ChromaDB, or authentication in this version.

## Architecture

```text
Browser
  |
  | GET / and POST /chat
  v
FastAPI in Docker
  |-- reads/writes backend/data/documents/
  |-- persists ChromaDB in backend/data/chroma/
  |-- calls Ollama at http://host.docker.internal:11434
  v
Ollama on Windows host
  |-- qwen3:8b for answers
  |-- nomic-embed-text for local embeddings
```

Uploaded TXT, PDF, and DOCX files are parsed, split into overlapping chunks, embedded locally by Ollama, and stored in ChromaDB. Chat retrieves only the configured top-k chunks and sends those chunks to Qwen. The full document collection is never sent to the generation model.

The existing `backend/data/knowledge.txt` is automatically indexed on the first chat request. It remains a valid source and is never discarded.

## Requirements

- Windows 10 or 11
- Docker Desktop using Linux containers
- Ollama for Windows
- Ollama models `qwen3:8b` and `nomic-embed-text`

Install and start Ollama, then run these in PowerShell:

```powershell
ollama pull qwen3:8b
ollama pull nomic-embed-text
ollama list
Invoke-RestMethod http://localhost:11434/api/tags
```

Ollama must remain running on Windows. Do not put Ollama or either model in Docker, and do not expose Ollama directly to the internet.

## Installation and startup

From PowerShell:

```powershell
Set-Location "C:\Users\mohan\Documents\mohan apps\jntuweb"
Copy-Item .env.example .env
docker compose build
docker compose up -d
Invoke-RestMethod http://localhost:8000/health
```

Open the website at:

```text
http://localhost:8000/
```

FastAPI serves the HTML, CSS, and JavaScript, so no separate frontend server is needed.

## Configuration

Copy `.env.example` to `.env` and edit values before starting Compose:

| Variable | Default | Purpose |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Ollama host URL from Docker |
| `OLLAMA_MODEL` | `qwen3:8b` | Generation model |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Local embedding model |
| `CHUNK_SIZE` | `1000` | Approximate chunk size in characters |
| `CHUNK_OVERLAP` | `150` | Character overlap between chunks |
| `TOP_K` | `4` | Number of retrieved chunks per chat request |
| `MAX_UPLOAD_SIZE_MB` | `20` | Maximum upload size |
| `CHROMA_COLLECTION` | `local_documents` | Chroma collection name |
| `MAX_CONCURRENT_GENERATIONS` | `2` | Maximum simultaneous Ollama answer generations |
| `CHAT_RATE_LIMIT` | `20` | Maximum chat requests per client IP in the rate window |
| `CHAT_RATE_WINDOW_SECONDS` | `60` | Per-IP chat rate-limit window |
| `MAX_CHAT_MESSAGE_LENGTH` | `4000` | Maximum chat message length in characters |
| `ADMIN_USERNAME` | required | Admin username for document management |
| `ADMIN_PASSWORD` | required | Admin password for document management |
| `ADMIN_COOKIE_SECURE` | `false` | Set `true` when serving through HTTPS |

Chat requests are public and do not require authentication or a user ID. Conversations are not stored by the backend. The in-memory per-IP rate limiter and generation queue apply to the running FastAPI process; use shared rate limiting and a coordinated worker strategy if deploying multiple backend replicas.

Document management requires the admin session created by `POST /admin/login`. `POST /admin/logout` clears the session, and `GET /admin/me` checks it. `POST /ingest`, `GET /documents`, and `DELETE /documents/{document_id}` return `401` without an authenticated admin session. Chat, health, and static frontend files remain public.

`backend/data/` is bind-mounted into the container. Therefore `documents/` and `chroma/` survive container recreation and can be backed up with the project data. Do not delete `backend/data/chroma/` unless you intend to rebuild the index.

## Ingestion

Use the API to upload a document:

```powershell
Invoke-RestMethod `
  -Uri http://localhost:8000/ingest `
  -Method Post `
  -Form @{ file = Get-Item .\path\to\document.pdf }
```

Supported formats are `.txt`, `.pdf`, and `.docx`. Files are saved under `backend/data/documents/`. SHA-256 document hashes prevent re-indexing the same content. Re-uploading the same filename with changed content replaces its old chunks. Duplicate chunk IDs are not added.

List indexed documents:

```powershell
Invoke-RestMethod http://localhost:8000/documents
```

## Document management UI

Open `http://localhost:8000/` and use the `Documents` tab to manage the local knowledge base. The UI supports PDF, DOCX, and TXT files, multiple selection, drag-and-drop, file sizes, per-file processing results, refresh, and an empty state.

Each selected file is sent independently to the existing `POST /ingest` endpoint. A failure for one file is shown beside that file while other files continue processing. Identical content is skipped using its document hash.

Indexed uploaded files appear with their type, size, chunk count, and status. The Delete action asks for confirmation and calls `DELETE /documents/{document_id}` using the stable SHA-256 document ID. The API removes both the file in `backend/data/documents/` and its Chroma chunks. The built-in `backend/data/knowledge.txt` source is labeled and cannot be deleted from the UI.

The browser receives metadata only; document contents remain on the backend. Chat source citations continue to show filenames and PDF page numbers when available.

## API endpoints

### `GET /`

Serves the chatbot webpage.

### `GET /health`

Returns:

```json
{"status":"ok"}
```

### `POST /ingest`

Multipart upload with field name `file`. Returns the indexing status, hash, and chunk count.

### `GET /documents`

Returns indexed filenames, types, source paths, hashes, chunk counts, sizes, stable IDs, and status. Existing response fields remain available.

### `DELETE /documents/{document_id}`

Deletes one uploaded document by its 64-character SHA-256 document ID. Built-in `knowledge.txt` and arbitrary paths are rejected. A failed Chroma or filesystem deletion returns an error instead of falsely reporting success.

### `POST /chat`

Request:

```json
{"message":"When does the library close?"}
```

Response:

```json
{
  "reply": "...",
  "sources": [
    {
      "filename": "knowledge.txt",
      "file_type": "txt",
      "chunk_id": "...",
      "source_path": "/app/backend/data/knowledge.txt",
      "distance": 0.2
    }
  ]
}
```

The frontend displays source filenames and page numbers when available.

## Testing

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/documents
Invoke-RestMethod `
  -Uri http://localhost:8000/chat `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"message":"When does the library close?"}'
```

To test retrieval, create a small TXT file with a unique fact, upload it using `/ingest`, then ask a question containing that fact. Confirm the response includes the uploaded filename in `sources`.

## Troubleshooting

- **Ollama connection error:** Confirm the Ollama desktop application is running and test `Invoke-RestMethod http://localhost:11434/api/tags` on Windows.
- **Model not found:** Run `ollama pull qwen3:8b` and `ollama pull nomic-embed-text`.
- **Embedding error during ingestion:** Check `OLLAMA_EMBED_MODEL` and make sure that model supports embeddings.
- **Upload rejected:** Only TXT, PDF, and DOCX files up to `MAX_UPLOAD_SIZE_MB` are accepted.
- **Old answers after editing a document:** Re-upload the changed file. Changed content replaces chunks for the same source path; identical content is skipped.
- **Chroma data missing:** Check that `backend/data/chroma/` exists and that Docker has access to the project directory.
- **Port already in use:** Stop the other service using port 8000 or change the published port in `docker-compose.yml` and the frontend `BACKEND_URL`.
- **Documents tab cannot load:** Check `docker compose logs -f backend` and confirm the container is running at `http://localhost:8000`.

View backend logs with:

```powershell
docker compose logs -f backend
```

## Production considerations

Before exposing this application through a tunnel or reverse proxy, add authentication, rate limiting, request size limits at the proxy, HTTPS, backups for `backend/data/`, and a restricted upload policy. Expose only FastAPI. Never expose Ollama's port directly. Review source-path disclosure in API responses before making the service public.

Document upload and deletion are intentionally unauthenticated for local-only use. They must be protected with authentication and authorization before any public deployment.

## Stop the application

```powershell
docker compose down
```
