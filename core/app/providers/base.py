"""Model provider abstraction.  No real model call yet — stub response."""
from abc import ABC, abstractmethod


class ModelProvider(ABC):
    @abstractmethod
    async def complete(self, messages, tools=None, **kwargs):
        ...


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
