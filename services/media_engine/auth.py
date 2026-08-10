"""Bearer-token auth for the engine API.

The engine binds to 127.0.0.1 only; the token stops anything else on the box
(e.g. a compromised web app) from driving renders and burning AI budget.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_config

_bearer = HTTPBearer(auto_error=False)


def require_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    cfg = get_config()
    if not cfg.engine_token:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "engine token not configured"
        )
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or credentials.credentials != cfg.engine_token
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing token")
