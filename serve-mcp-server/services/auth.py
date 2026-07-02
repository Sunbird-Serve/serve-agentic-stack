"""
JWT Authentication Utilities for SERVE MCP Server
Validates Keycloak-issued JWTs using JWKS (RS256).

This module is framework-agnostic (no FastAPI dependency).
Used by the dashboard HTTP endpoints for JWT-based role checking.
"""
import os
import time
import logging
from typing import List, Optional

import httpx
import jwt
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────────

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "sunbird-serve")

JWKS_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"
ISSUER = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}"

# JWKS cache
_jwks_cache: dict = {}
_jwks_fetched_at: float = 0
_JWKS_CACHE_TTL = 3600  # 1 hour


# ── Models ─────────────────────────────────────────────────────────────────────

class UserClaims(BaseModel):
    """Decoded JWT claims relevant to the application."""
    sub: str
    email: Optional[str] = None
    preferred_username: Optional[str] = None
    name: Optional[str] = None
    roles: List[str] = []
    agency_id: Optional[str] = None
    agency_type: Optional[str] = None
    rc_osid: Optional[str] = None


# ── JWKS Fetching ──────────────────────────────────────────────────────────────

async def _fetch_jwks() -> dict:
    global _jwks_cache, _jwks_fetched_at
    now = time.time()
    if _jwks_cache and (now - _jwks_fetched_at) < _JWKS_CACHE_TTL:
        return _jwks_cache
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(JWKS_URL)
            resp.raise_for_status()
            _jwks_cache = resp.json()
            _jwks_fetched_at = now
            return _jwks_cache
    except Exception as e:
        logger.error("Failed to fetch JWKS: %s", e)
        if _jwks_cache:
            return _jwks_cache
        raise RuntimeError("JWKS unavailable")


async def _get_signing_key(token: str):
    jwks_data = await _fetch_jwks()
    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.exceptions.DecodeError:
        raise ValueError("Invalid token format")

    kid = unverified_header.get("kid")
    if not kid:
        raise ValueError("Token missing kid")

    for key_data in jwks_data.get("keys", []):
        if key_data.get("kid") == kid:
            return jwt.algorithms.RSAAlgorithm.from_jwk(key_data)

    # Force refresh and retry
    global _jwks_fetched_at
    _jwks_fetched_at = 0
    jwks_data = await _fetch_jwks()
    for key_data in jwks_data.get("keys", []):
        if key_data.get("kid") == kid:
            return jwt.algorithms.RSAAlgorithm.from_jwk(key_data)

    raise ValueError("Signing key not found")


# ── Token Validation ───────────────────────────────────────────────────────────

def _extract_bearer_token(auth_header: str) -> str:
    """Extract token from 'Bearer <token>' header value."""
    if not auth_header.startswith("Bearer "):
        raise ValueError("Missing or invalid Authorization header")
    return auth_header[7:]


async def _decode_token(token: str) -> dict:
    """Validate and decode a JWT token. Raises on failure."""
    public_key = await _get_signing_key(token)
    payload = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        issuer=ISSUER,
        options={"verify_aud": False, "verify_exp": True, "verify_iss": True},
    )
    return payload


def _extract_claims(payload: dict) -> UserClaims:
    """Extract application-relevant claims from decoded JWT payload."""
    realm_roles = payload.get("realm_access", {}).get("roles", [])
    return UserClaims(
        sub=payload.get("sub", ""),
        email=payload.get("email"),
        preferred_username=payload.get("preferred_username"),
        name=payload.get("name"),
        roles=realm_roles,
        agency_id=payload.get("agencyId"),
        agency_type=payload.get("agencyType"),
        rc_osid=payload.get("rcOsid"),
    )


async def validate_token(auth_header: str) -> UserClaims:
    """
    Full validation pipeline: extract → decode → claims.
    Raises ValueError or jwt exceptions on failure.
    """
    token = _extract_bearer_token(auth_header)
    payload = await _decode_token(token)
    return _extract_claims(payload)
