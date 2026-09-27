"""Provider-neutral chat messages shared by text and voice."""
import json
from datetime import date, datetime
from pathlib import Path


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f'Unsupported evidence type: {type(value).__name__}')


MAX_CONTEXT_CHARS = 12000
_SOURCE_FIELDS = ('kind', 'id', 'snippet', 'confidence', 'score', 'created_at',
                  'occurred_at', 'decided_at', 'priority')
_PROMPT_PATH = Path(__file__).with_name('prompts') / 'chat_v1.md'


def _bounded_evidence(ctx: dict) -> str:
    evidence = {'type': 'untrusted_retrieval_evidence', 'sources': [], 'truncated': False}
    for source in ctx.get('sources', []):
        bounded = {}
        for key in _SOURCE_FIELDS:
            if key not in source:
                continue
            value = source[key]
            if isinstance(value, str):
                limit = 1000 if key == 'snippet' else 128
                evidence['truncated'] |= len(value) > limit
                value = value[:limit]
            elif not isinstance(value, (int, float, bool, date, type(None))):
                continue
            bounded[key] = value
        evidence['sources'].append(bounded)
        if len(json.dumps(evidence, default=_json_default)) > MAX_CONTEXT_CHARS:
            evidence['sources'].pop()
            evidence['truncated'] = True
            break
    return json.dumps(evidence, default=_json_default)


def build_messages(query: str, ctx: dict) -> list[dict[str, str]]:
    """Load JAX's versioned identity and preserve the actual query last."""
    return [
        {'role': 'system', 'content': _PROMPT_PATH.read_text(encoding='utf-8')},
        {'role': 'user', 'content': _bounded_evidence(ctx)},
        {'role': 'user', 'content': query},
    ]
