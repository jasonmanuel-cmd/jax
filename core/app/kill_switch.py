"""Kill switch policy: blocks device event ingestion when active."""
from sqlalchemy import select
from .tables2 import kill_switch


def is_kill_active(db_conn, device_id: str | None = None) -> bool:
    """Return True if the global or device-specific kill switch is active."""
    stmt = select(kill_switch.c.id).where(
        kill_switch.c.deactivated_at.is_(None)
    )
    if device_id:
        stmt = stmt.where(
            (kill_switch.c.device_id == device_id) |
            (kill_switch.c.device_id.is_(None))
        )
    return db_conn.execute(stmt).first() is not None
