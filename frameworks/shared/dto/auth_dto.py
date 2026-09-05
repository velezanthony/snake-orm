"""DTOs for the auth domain (API tokens and login sessions).

It REDACTS the secret: the token value (`ApiToken.token`) is NEVER serialized; only its label and
metadata. A debug panel that leaked the token would be a hole, not a demo.
"""

from __future__ import annotations

from shared.dto import iso
from shared.dto.accounts_dto import login_session_dict as login_session_dict
from shared.models import ApiToken


def token_dict(token: ApiToken) -> dict[str, object]:
    """An API token as a dict, WITHOUT its secret value (only label, state and dates)."""
    return {
        "id": token.id,
        "label": token.label,
        "revoked": token.revoked,
        "user_id": token.user_id,
        "created_at": iso(token.created_at),
        "expires_at": iso(token.expires_at),
    }
