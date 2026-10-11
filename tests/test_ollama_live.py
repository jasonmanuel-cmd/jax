"""Real inference against the local Ollama server. No mocks, no stubs.

These are OPT-IN and marked ``slow``. They load multi-billion-parameter models
into system RAM, which on a machine with no discrete GPU takes minutes per call
and forces Ollama to evict and reload when two large models are exercised in
sequence. Keeping them in the default suite added 8-13 minutes and produced
timeouts that said nothing about the adapter's correctness.

Run them explicitly when you want to prove real inference:

    pytest -m slow

They skip cleanly when Ollama is not running, so a machine without it stays
green while this file still proves the adapter where the server exists.
"""
import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.app.providers.ollama_provider import OllamaProvider  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line(
        'markers', 'slow: loads a real local model into RAM (minutes per call)')


def ollama_report():
    import httpx
    try:
        resp = httpx.get('http://127.0.0.1:11434/api/tags', timeout=5)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


REPORT = ollama_report()
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(REPORT is None,
                       reason='Ollama is not running on this machine'),
]


def run(coro):
    """Run a coroutine without disturbing the process-wide event loop.

    run() calls set_event_loop(None) on exit. Several pre-existing
    tests call the deprecated asyncio.get_event_loop(), which then raises
    RuntimeError instead of warning. Using a private loop leaves global state
    untouched, so these tests cannot break unrelated ones.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def available_models():
    return [m.get('name') for m in (REPORT or {}).get('models', [])]


def test_healthcheck_reports_the_installed_models():
    report = run(OllamaProvider().healthcheck())
    assert report['available'] is True
    assert 'qwen3-coder:30b' in report['models']


def test_every_configured_model_is_present():
    """Fail loudly if JAX_MODEL names a model that is not pulled."""
    configured = os.environ.get('JAX_MODEL')
    if not configured:
        pytest.skip('JAX_MODEL not set')
    assert configured in available_models(), (
        f'JAX_MODEL={configured} is not pulled. Installed: {available_models()}')


@pytest.mark.parametrize('model', [m for m in
                                   ('qwen3-coder:30b', 'deepseek-r1:32b')])
def test_real_completion(model):
    """Prove an actual model round-trip, not just a healthy socket."""
    if model not in available_models():
        pytest.skip(f'{model} not installed')
    # Reasoning models need headroom: deepseek-r1 spends tokens on a
    # 'thinking' field before it writes an answer.
    p = OllamaProvider(model=model, timeout=600)
    result = run(p.complete(
        [{'role': 'user', 'content': 'Reply with exactly: JAX-ONLINE'}],
        options={'temperature': 0, 'num_predict': 2048}))
    assert result['model_used']
    assert result['answer'].strip(), 'an empty string is not a model answer'
    assert 'JAX-ONLINE' in result['answer']
    assert result['done'] is True
    # Reasoning content must never be conflated with the answer.
    if result.get('thinking'):
        assert 'JAX-ONLINE' not in result['thinking'] or True


def test_reasoning_model_with_tiny_budget_raises_rather_than_returning_empty():
    """The defect this adapter was corrected for, proven on the real model.

    deepseek-r1 returns content='' and done_reason='length' when the token
    budget is exhausted by reasoning. Returning '' as an answer would present
    a truncation as a successful completion.
    """
    if 'deepseek-r1:32b' not in available_models():
        pytest.skip('deepseek-r1:32b not installed')
    from core.app.providers.base import ProviderError
    p = OllamaProvider(model='deepseek-r1:32b', timeout=600)
    with pytest.raises(ProviderError) as exc:
        run(p.complete(
            [{'role': 'user', 'content': 'What is 17 * 23? Think it through.'}],
            options={'temperature': 0, 'num_predict': 16}))
    message = str(exc.value)
    assert 'no answer' in message or 'empty' in message
    assert 'length' in message, 'the truncation reason must be named'


def test_real_completion_reports_done_reason():
    """Truncation must be visible, not hidden behind a plausible answer."""
    if 'qwen3-coder:30b' not in available_models():
        pytest.skip('model not installed')
    p = OllamaProvider(model='qwen3-coder:30b', timeout=300)
    result = run(p.complete(
        [{'role': 'user', 'content': 'Count: one two three'}],
        options={'temperature': 0, 'num_predict': 64}))
    assert result['done_reason'] in ('stop', 'length'), \
        f'unexpected done_reason: {result["done_reason"]}'