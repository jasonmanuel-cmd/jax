"""Model provider abstraction.

A provider failure must never be indistinguishable from a model answer. The
original stubs returned ``{'answer': 'Model provider not yet configured.'}``,
which a caller cannot tell apart from a real (bad) reply, so failures silently
propagated as successful chat turns (SPEC_AUDIT R9).

Providers therefore raise:

* :class:`ProviderUnavailable` — the backend cannot be reached at all.
* :class:`ProviderError` — the backend was reached and refused or misbehaved.

Callers decide what to do; the provider never invents an answer to paper over a
failure.
"""
from abc import ABC, abstractmethod


class ProviderError(RuntimeError):
    """The backend was reachable but the call failed."""


class ProviderUnavailable(ProviderError):
    """The backend could not be reached (not running, wrong host, refused)."""


class ModelProvider(ABC):
    @abstractmethod
    async def complete(self, messages, tools=None, **kwargs):
        ...

    async def healthcheck(self) -> dict:
        """Report backend availability. Never raises."""
        return {'available': None, 'note': 'provider does not implement healthcheck'}


class LocalProvider(ModelProvider):
    """Stub that returns a structured placeholder answer.  Replace with
    Ollama / LM Studio adapter when the model layer is wired up.
    """
    async def complete(self, messages, tools=None, **kwargs):
        return {
            'answer': 'Model provider not yet configured.  Connect a local or cloud model.',
            'model_used': 'stub',
            'tokens': None,
        }


class CloudProvider(ModelProvider):
    """Stub for cloud models.  Wire API key from env, never from memory."""
    async def complete(self, messages, tools=None, **kwargs):
        return {
            'answer': 'Cloud provider not yet configured.',
            'model_used': 'stub',
            'tokens': None,
        }
