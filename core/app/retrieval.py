"""Scoped keyword retrieval across memories, decisions, and tasks.
Unowned device events are excluded. No embeddings yet — deferred until pgvector.
"""
from datetime import datetime, timezone
from sqlalchemy import select, or_
from .tables2 import memories, decisions, tasks


def _tokenize(query: str) -> list[str]:
    """Split and normalise a query into search tokens."""
    return [t.lower() for t in query.split() if len(t) >= 2]


def _score(text: str | None, tokens: list[str]) -> int:
    if not text:
        return 0
    lower = text.lower()
    return sum(1 for t in tokens if t in lower)


def retrieve_context(
    query: str,
    *,
    project_id: str | None = None,
    user_id: str | None = None,
    db_conn=None,
    hours: int = 24,
    token_budget: int = 6000,
) -> dict:
    """Return ranked context for exactly one user and project scope.

    No project means personal (NULL-project) records, not all projects.
    Expired memories are excluded. Events lack scoped ownership and are omitted;
    ``hours`` remains accepted for caller compatibility until events can be scoped.
    ``token_budget`` is the legacy character budget, not a tokenizer-based limit.
    All results are dicts, not ORM objects.
    """
    tokens = _tokenize(query)
    candidates: list[dict] = []

    # --- Memories --------------------------------------------------------
    stmt = select(memories).where(
        memories.c.user_id == user_id,
        or_(memories.c.expires_at.is_(None),
            memories.c.expires_at > datetime.now(timezone.utc)),
    )
    stmt = stmt.where(memories.c.project_id == project_id)
    rows = db_conn.execute(stmt).mappings().all()
    for row in rows:
        s = _score(row['content'], tokens)
        candidates.append({'kind': 'memory', 'id': row['id'],
                           'snippet': row['content'][:300],
                           'confidence': row['confidence'],
                           'score': s, 'created_at': row['created_at']})

    # Events currently have neither a trusted user nor project binding (nor do
    # devices). Fail closed: git_context type, payload claims, and device recency
    # cannot establish authorization. Re-enable only with verified scoped ownership.

    # --- Active decisions ------------------------------------------------
    dstmt = select(decisions).where(decisions.c.user_id == user_id)
    dstmt = dstmt.where(decisions.c.project_id == project_id)
    drows = db_conn.execute(dstmt).mappings().all()
    for row in drows:
        s = _score(row['decision'], tokens)
        s += _score(row.get('rationale'), tokens)
        candidates.append({
            'kind': 'decision', 'id': row['id'],
            'snippet': row['decision'][:300],
            'score': s, 'decided_at': row['decided_at'],
        })

    # --- Open tasks ------------------------------------------------------
    tstmt = select(tasks).where(
        tasks.c.user_id == user_id,
        tasks.c.status == 'open',
    )
    tstmt = tstmt.where(tasks.c.project_id == project_id)
    trows = db_conn.execute(tstmt).mappings().all()
    for row in trows:
        s = _score(row['title'], tokens)
        candidates.append({
            'kind': 'task', 'id': row['id'],
            'snippet': row['title'],
            'score': s, 'priority': row['priority'],
        })

    # --- Rank & trim -----------------------------------------------------
    candidates.sort(key=lambda c: c['score'], reverse=True)
    total = 0
    trimmed = []
    for c in candidates:
        chunk = len(c.get('snippet', ''))
        if total + chunk > token_budget:
            break
        trimmed.append(c)
        total += chunk

    return {
        'query': query,
        'project_id': project_id,
        'total_candidates': len(candidates),
        'returned': len(trimmed),
        'sources': trimmed,
    }
