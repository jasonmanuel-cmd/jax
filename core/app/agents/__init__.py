"""Agent adapter registry.

Availability is probed, never assumed, and unavailable adapters are omitted
from the launchable set rather than being advertised and failing later.
"""
from __future__ import annotations

from .base import AgentAdapter, AgentResult, AgentSession, BaseAdapter, SessionBrief
from .claude import ClaudeAdapter
from .generic_cli import GenericCliAdapter
from .hermes import HermesAdapter

__all__ = [
    'AgentAdapter', 'AgentResult', 'AgentSession', 'BaseAdapter', 'SessionBrief',
    'ClaudeAdapter', 'HermesAdapter', 'GenericCliAdapter',
    'build_registry', 'AdapterRegistry',
]


class AdapterRegistry:
    def __init__(self, adapters: list[AgentAdapter] | None = None):
        self._adapters: dict[str, AgentAdapter] = {}
        for adapter in adapters or []:
            self.register(adapter)

    def register(self, adapter: AgentAdapter) -> AgentAdapter:
        if adapter.name in self._adapters:
            raise ValueError(f'adapter already registered: {adapter.name}')
        self._adapters[adapter.name] = adapter
        return adapter

    def get(self, name: str) -> AgentAdapter:
        try:
            return self._adapters[name]
        except KeyError:
            raise KeyError(f'no such adapter: {name}') from None

    def names(self) -> list[str]:
        return sorted(self._adapters)

    def available(self) -> list[AgentAdapter]:
        """Adapters that can actually run right now."""
        return [a for a in self._adapters.values() if a.available()]

    def healthcheck(self) -> list[dict]:
        return [a.healthcheck() for a in self._adapters.values()]


def build_registry() -> AdapterRegistry:
    return AdapterRegistry([
        ClaudeAdapter(),
        HermesAdapter(),
        GenericCliAdapter(),
    ])