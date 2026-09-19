from typing import Any

import httpx


class OllamaError(RuntimeError):
    """Raised when Ollama cannot provide an embedding or chat response."""


class OllamaClient:
    def __init__(self, base_url: str, model: str, embed_model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.embed_model = embed_model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": self.embed_model, "input": texts}
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(f"{self.base_url}/api/embed", json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.ConnectError as error:
            raise OllamaError("Could not connect to Ollama on the host PC.") from error
        except httpx.TimeoutException as error:
            raise OllamaError("Ollama took too long to create embeddings.") from error
        except httpx.HTTPStatusError as error:
            raise OllamaError(f"Ollama embedding error: {error.response.text}") from error
        except (httpx.RequestError, ValueError) as error:
            raise OllamaError("Ollama returned an invalid embedding response.") from error

        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise OllamaError("Ollama returned an unexpected number of embeddings.")
        return embeddings

    async def chat(self, messages: list[dict[str, str]]) -> str:
        payload = {"model": self.model, "stream": False, "think": False, "messages": messages}
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                data: dict[str, Any] = response.json()
        except httpx.ConnectError as error:
            raise OllamaError("Could not connect to Ollama on the host PC.") from error
        except httpx.TimeoutException as error:
            raise OllamaError("Ollama took too long to respond.") from error
        except httpx.HTTPStatusError as error:
            raise OllamaError(f"Ollama chat error: {error.response.text}") from error
        except (httpx.RequestError, ValueError) as error:
            raise OllamaError("Ollama returned an invalid chat response.") from error

        reply = data.get("message", {}).get("content", "").strip()
        if not reply:
            raise OllamaError("Ollama returned an empty response.")
        return reply
