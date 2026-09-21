"""Shared SQLAlchemy metadata. Imported by both db.py and tables2.py to
avoid circular imports."""
from sqlalchemy import MetaData

metadata = MetaData()
