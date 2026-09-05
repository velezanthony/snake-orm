"""DTOs for the accounts domain (roles). Flat and JSON-able."""

from __future__ import annotations

from shared.dto import iso
from shared.models import LoginSession, Role


def role_dict(role: Role) -> dict[str, object]:
    """A role as a dict: id and name."""
    return {"id": role.id, "name": role.name}


def login_session_dict(session: LoginSession) -> dict[str, object]:
    """A login session as a dict (auth reuses it): no sensitive data."""
    return {
        "id": session.id,
        "user_id": session.user_id,
        "ip": session.ip,
        "user_agent": session.user_agent,
        "created_at": iso(session.created_at),
        "last_seen_at": iso(session.last_seen_at),
    }
