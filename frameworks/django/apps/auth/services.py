"""Services of the auth domain: re-exports the ones from the SHARED package (`shared.services`)."""

from __future__ import annotations

from shared.services.auth_services import issue_token as issue_token
from shared.services.auth_services import revoke_token as revoke_token
from shared.services.auth_services import open_login_session as open_login_session
