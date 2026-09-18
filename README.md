# My AI Assistant

A small self-hosted chatbot. The FastAPI backend runs in Docker and sends questions to Ollama running locally on the Windows host. The frontend is plain HTML, CSS, and JavaScript.

## Required software

- Windows 10 or 11
- Docker Desktop with Linux containers enabled
- Ollama for Windows
- A modern web browser

## Start and check Ollama

Install Ollama from [ollama.com](https://ollama.com/), then start the Ollama application. Ollama normally listens on `http://localhost:11434`.

Check the installed models:

```powershell
ollama list
```

Verify it is running in PowerShell:

```powershell
Invoke-RestMethod http://localhost:11434/api/tags
```

If `qwen3:8b` is not listed, download it:

```powershell
ollama pull qwen3:8b
```

You can also run it interactively to confirm the model works:

```powershell
ollama run qwen3:8b
```

Type a test question, then use `Ctrl+C` to exit. Keep the Ollama application running while using the chatbot.

## Exact Windows startup steps

Open PowerShell in this project directory and run:

```powershell
Set-Location "C:\Users\mohan\Documents\mohan apps\jntuweb"

ollama list

docker compose up -d
```

The backend and website are available at `http://localhost:8000`. Check the backend with:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

The data directory is mounted into the container, so changes to `backend/data/knowledge.txt` are used on the next chat request without rebuilding.

## Open the website

Open `http://localhost:8000/`. FastAPI serves `index.html`, `style.css`, and `app.js` directly, so no separate frontend server or port is needed.

## Test the complete chatbot

1. Run `ollama list` and confirm `qwen3:8b` is available.
2. Run `docker compose up -d`.
3. Check `http://localhost:8000/` and `http://localhost:8000/health`.
4. Open `http://localhost:8000/` and ask: `When does the library close?`.
5. The answer should come from `backend/data/knowledge.txt`.
6. Ask a question unrelated to the file and confirm the assistant says the information is not available instead of inventing an answer.

You can also test the API directly:

```powershell
Invoke-RestMethod `
  -Uri http://localhost:8000/chat `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"message":"When does the library close?"}'
```

## Stop the application

To stop the backend and remove its container and network, run:

```powershell
docker compose down
```

## Architecture

```text
Browser (frontend served by FastAPI at http://localhost:8000/)
        |
        | POST http://localhost:8000/chat
        v
FastAPI backend (Docker container)
        |
        | http://host.docker.internal:11434/api/chat
        v
Ollama (Windows host, qwen3:8b)
```

The backend reads `backend/data/knowledge.txt` and includes its contents in the system prompt sent to Ollama. Ollama is not exposed by this project; only the FastAPI port is published. There are no cloud AI services, API keys, database, RAG system, or authentication in this first version.

## Windows and Docker notes

Docker Desktop must be running, and the backend container must use Linux containers. `host.docker.internal` is the Docker Desktop hostname that lets a container reach services on the Windows host. The Compose file also includes a host-gateway mapping for compatibility.

Do not publish Ollama's port through your router or tunnel. If the application is made public later, expose only the backend through a properly secured reverse proxy or tunnel, and add authentication and rate limiting before doing so.
