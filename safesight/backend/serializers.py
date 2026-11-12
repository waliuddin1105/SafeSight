from datetime import datetime
from safesight.storage.schema import Evidence


def serialize(row) -> dict:
    """Serialize public columns, excluding credentials and internal media paths."""
    hidden = {"access_token", "refresh_token", "path", "config", "worker_id"}
    result = {}
    for column in row.__table__.columns:
        if column.name in hidden:
            continue
        value = getattr(row, column.name)
        result[column.name] = value.isoformat() if isinstance(value, datetime) else value
    if isinstance(row, Evidence):
        result["url"] = f"/api/v1/evidence/{row.id}" if row.state == "ready" else None
    return result
