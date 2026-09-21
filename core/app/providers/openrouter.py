"""OpenRouter model provider — real LLM calls via OpenRouter API."""
import os
import httpx
from .base import ModelProvider


class OpenRouterProvider(ModelProvider):
    """OpenRouter provider — supports multiple models via one API."""

    def __init__(self, api_key=None, model="openai/gpt-4o-mini"):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.model = model
        self.base_url = "https://openrouter.ai/api/v1"

    async def complete(self, messages, tools=None, **kwargs):
        if not self.api_key:
            return {
                "answer": "OpenRouter API key not configured. Set OPENROUTER_API_KEY.",
                "model_used": "none",
                "tokens": None,
            }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": messages,
        }

        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        message = choice["message"]
        usage = data.get("usage", {})

        return {
            "answer": message.get("content", ""),
            "model_used": self.model,
            "tokens": usage.get("total_tokens"),
            "tool_calls": message.get("tool_calls"),
        }
