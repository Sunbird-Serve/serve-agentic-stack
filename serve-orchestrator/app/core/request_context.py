"""
Request-scoped context for threading auth tokens and user info
through the orchestration pipeline without changing every function signature.

Usage:
    # In the route handler:
    from app.core.request_context import auth_token_var
    auth_token_var.set(request.headers.get("Authorization", ""))

    # Anywhere downstream:
    from app.core.request_context import auth_token_var
    token = auth_token_var.get("")
"""
from contextvars import ContextVar

# The full Authorization header value (e.g., "Bearer eyJ...")
auth_token_var: ContextVar[str] = ContextVar("auth_token", default="")
