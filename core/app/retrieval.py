"""Retrieval engine: keyword-based search across memories, events,
decisions, and tasks.  No embeddings yet — deferred until pgvector.
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, or_, text
from .db import events
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
    """Return ranked context from memories, recent events, active
    decisions, and open tasks.  All results are dicts, not ORM objects.
    """
    tokens = _tokenize(query)
    candidates: list[dict] = []

    # --- Memories --------------------------------------------------------
    stmt = select(memories).where(memories.c.user_id == user_id)
    if project_id:
        stmt = stmt.where(memories.c.project_id == project_id)
    rows = db_conn.execute(stmt).mappings().all()
    for row in rows:
        s = _score(row['content'], tokens)
        candidates.append({'kind': 'memory', 'id': row['id'],
                           'snippet': row['content'][:300],
                           'confidence': row['confidence'],
                           'score': s, 'created_at': row['created_at']})

    # --- Recent events ---------------------------------------------------
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    estmt = select(events).where(events.c.device_id.in_(
        select(events.c.device_id).where(events.c.occurred_at >= cutoff)
    ))
    if project_id:
        estmt = estmt.where(
            events.c.payload['type'].as_string().in_(['git_context'])
        )
    erows = db_conn.execute(estmt).mappings().all()
    for row in erows:
        payload = row['payload']
        s = _score(payload.get('summary', ''), tokens)
        candidates.append({
            'kind': 'event', 'id': row['id'],
            'snippet': payload.get('summary', '')[:300],
            'score': s, 'occurred_at': row['occurred_at'],
        })

    # --- Active decisions ------------------------------------------------
    dstmt = select(decisions).where(decisions.c.user_id == user_id)
    if project_id:
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
    if project_id:
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
