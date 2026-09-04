"""Password hashing and verification for the demo logins.

Stdlib only (`hashlib.scrypt`), no extra dependencies. Stored format: `scrypt$<salt>$<digest>`
in base64. `verify_password` uses `hmac.compare_digest` (constant-time comparison).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

_N, _R, _P = 2**14, 8, 1  # scrypt parameters (a sensible cost for a demo)


def hash_password(password: str) -> str:
    """Returns the storable hash of a password, with a random salt."""
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return (
        f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"
    )


def verify_password(password: str, hashed: str) -> bool:
    """`True` if the password matches the hash. False for any unexpected format."""
    try:
        scheme, salt_b64, digest_b64 = hashed.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    salt = base64.b64decode(salt_b64)
    expected = base64.b64decode(digest_b64)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return hmac.compare_digest(digest, expected)
