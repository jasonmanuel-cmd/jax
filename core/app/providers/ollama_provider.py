"""Ollama provider — local inference, no API key, nothing leaves the machine.

Two things this adapter is deliberate about:

1. Failures are raised, not disguised. The cloud adapters return an ordinary
   answer when the key is missing or the API errors, so a caller cannot tell a
   model response from a failure (SPEC_AUDIT R9). Here a missing server or a
   failed generation raises ProviderUnavailable/ProviderError instead.

2. Bind to loopback only. Ollama has no auth of its own, so an exposed port is
   an open inference endpoint for anyone who can reach it.
"""
from __future__ import annotations

import os

import httpx

from .base import ModelProvider, ProviderError, ProviderUnavailable

# Local inference can be slow to load a 30B model; be generous but bounded.
DEFAULT_TIMEOUT = 600.0


class OllamaProvider(ModelProvider):
    """Chat completions via Ollama's OpenAI-compatible endpoint."""

    def __init__(self, model: str | None = None,
                 base_url: str | None = None,
                 timeout: float = DEFAULT_TIMEOUT):
        self.model = model or os.environ.get('JAX_MODEL', 'qwen3-coder:30b')
        self.base_url = (base_url
                         or os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434')
                         ).rstrip('/')
        self.timeout = timeout

    def _headers(self) -> dict:
        # An optional key for a fronted/proxied Ollama. Never required here.
        key = os.environ.get('OLLAMA_API_KEY', '')
        headers = {'Content-Type': 'application/json'}
        if key:
            headers['Authorization'] = f'Bearer {key}'
        return headers

    async def healthcheck(self) -> dict:
        """Probe the server. Returns a report; never raises."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f'{self.base_url}/api/tags',
                                        headers=self._headers())
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            return {'available': False, 'base_url': self.base_url,
                    'model': self.model,
                    'error': f'{type(exc).__name__}: {exc}'}
        models = [m.get('name') for m in data.get('models', [])]
        return {'available': True, 'base_url': self.base_url,
                'model': self.model, 'model_present': self.model in models,
                'models': models}

    async def complete(self, messages, tools=None, **kwargs):
        payload = {
            'model': self.model,
            'messages': messages,
            'stream': False,
            # Deterministic-ish: temperature is opt-out, not opt-in.
            'options': kwargs.get('options') or {'temperature': 0.2},
        }
        if tools:
            payload['tools'] = tools

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f'{self.base_url}/api/chat',
                                         headers=self._headers(),
                                         json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.ConnectError as exc:
            # The common case: Ollama is not running.
            raise ProviderUnavailable(
                f'Ollama is not reachable at {self.base_url}. Start it with '
                f'`ollama serve`, or set OLLAMA_HOST. ({type(exc).__name__})') from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f'Ollama did not respond within {self.timeout:.0f}s. A large '
                'model may still be loading into memory.') from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f'Ollama returned {exc.response.status_code}: '
                f'{exc.response.text[:200]}') from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f'Ollama request failed: {type(exc).__name__}') from exc

        message = data.get('message') or {}
        content = message.get('content')
        thinking = message.get('thinking')

        # Reasoning models (deepseek-r1 and friends) emit a separate
        # 'thinking' field. When the token budget is consumed by reasoning,
        # they return done_reason='length' with content='' — an empty answer
        # that is NOT a model reply. Returning that as 'answer' would present
        # a truncation as a successful completion.
        if content is None or not str(content).strip():
            if thinking:
                raise ProviderError(
                    f'{data.get("model", self.model)} spent its entire token '
                    f'budget reasoning and returned no answer '
                    f'(done_reason={data.get("done_reason")!r}, '
                    f'{data.get("eval_count")} tokens). Reasoning models need a '
                    'larger num_predict. Partial reasoning is available via '
                    'healthcheck(); nothing was answered.')
            raise ProviderError(
                f'Ollama returned an empty completion '
                f'(done_reason={data.get("done_reason")!r}): {str(data)[:200]}')

        return {
            'answer': content,
            'model_used': data.get('model', self.model),
            'tokens': (data.get('eval_count')
                       if data.get('eval_count') is not None else None),
            'tool_calls': message.get('tool_calls'),
            # Reasoning content, kept separate from the answer so a caller can
            # audit the reasoning without it being mistaken for the response.
            'thinking': thinking or None,
            # Honest accounting: a model that stopped on its own length limit
            # did not finish, and the caller should be able to see that.
            'done_reason': data.get('done_reason'),
            'done': data.get('done'),
        }