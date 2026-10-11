"""Kill switch policy: blocks device event ingestion when active."""
from sqlalchemy import select
from .tables2 import kill_switch


def is_kill_active(db_conn, device_id: str | None = None,
                   global_only: bool = False) -> bool:
    """Return True if the kill switch blocks this caller.

    Scope rules:
    - ``device_id`` given: that device's own switch OR a global switch applies.
    - ``device_id=None`` and ``global_only``: only a global switch applies, so
      a device-scoped incident does not halt unrelated work.
    - ``device_id=None`` and not ``global_only``: any active switch applies.
    """
    stmt = select(kill_switch.c.id).where(
        kill_switch.c.deactivated_at.is_(None)
    )
    if device_id:
        stmt = stmt.where(
            (kill_switch.c.device_id == device_id) |
            (kill_switch.c.device_id.is_(None))
        )
    elif global_only:
        stmt = stmt.where(kill_switch.c.device_id.is_(None))
    return db_conn.execute(stmt).first() is not None
