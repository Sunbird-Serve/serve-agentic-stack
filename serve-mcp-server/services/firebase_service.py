"""
SERVE MCP Server - Firebase Auth Service

Handles Firebase user creation and password reset email during volunteer registration.
Uses Firebase REST API via httpx — no firebase-admin SDK needed.

Required env vars:
  FIREBASE_API_KEY — Firebase Web API Key (from Firebase Console → Project Settings)
"""
import logging
import os
import secrets
import string
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

FIREBASE_API_KEY = os.environ.get("FIREBASE_API_KEY", "")
_FIREBASE_BASE = "https://identitytoolkit.googleapis.com/v1"
_TIMEOUT = 10


def _random_password(length: int = 16) -> str:
    chars = string.ascii_letters + string.digits + "!@#$%"
    return "".join(secrets.choice(chars) for _ in range(length))


async def email_exists(email: str) -> Dict[str, Any]:
    """Check if a Firebase user exists by email."""
    if not FIREBASE_API_KEY:
        logger.warning("FIREBASE_API_KEY not set — skipping Firebase email check")
        return {"status": "error", "exists": False, "errors": ["FIREBASE_API_KEY not configured"]}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            # Use fetchProviders to check if email exists
            resp = await client.post(
                f"{_FIREBASE_BASE}/accounts:createAuthUri?key={FIREBASE_API_KEY}",
                json={"identifier": email, "continueUri": "https://serve.net.in"},
            )
            data = resp.json()

            if resp.status_code == 200:
                registered = data.get("registered", False)
                return {
                    "status": "ok",
                    "exists": registered,
                    "message": f"Email {'exists' if registered else 'not found'} in Firebase",
                    "errors": [],
                }
            else:
                error_msg = data.get("error", {}).get("message", "Unknown error")
                return {"status": "error", "exists": False, "errors": [error_msg]}

    except Exception as e:
        logger.error(f"Firebase email_exists failed: {e}")
        return {"status": "error", "exists": False, "errors": [str(e)]}


async def ensure_user(
    email: str,
    display_name: str = "",
    create_if_missing: bool = True,
    generate_reset_link: bool = True,
) -> Dict[str, Any]:
    """
    Idempotently ensure a Firebase email/password user exists.
    Creates user if missing, sends password reset email.
    """
    if not FIREBASE_API_KEY:
        logger.warning("FIREBASE_API_KEY not set — skipping Firebase user creation")
        return {"status": "failed", "errors": ["FIREBASE_API_KEY not configured"]}

    try:
        # Step 1: Check if user exists
        check = await email_exists(email)
        if check.get("exists"):
            firebase_uid = check.get("firebase_uid")
            result = {
                "status": "existing",
                "firebase_uid": firebase_uid,
                "reset_link": None,
                "reset_email_sent": False,
                "message": f"User already exists in Firebase",
                "errors": [],
            }
            # Still send password reset if requested
            if generate_reset_link:
                reset_ok = await _send_password_reset(email)
                result["reset_email_sent"] = reset_ok
                if reset_ok:
                    result["message"] += " (reset email sent)"
            return result

        if not create_if_missing:
            return {
                "status": "failed",
                "message": "User not found and create_if_missing=False",
                "errors": [],
            }

        # Step 2: Create user with random password
        password = _random_password()
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{_FIREBASE_BASE}/accounts:signUp?key={FIREBASE_API_KEY}",
                json={
                    "email": email,
                    "password": password,
                    "displayName": display_name or email.split("@")[0],
                    "returnSecureToken": False,
                },
            )
            data = resp.json()

        if resp.status_code != 200:
            error_msg = data.get("error", {}).get("message", "Unknown error")
            # EMAIL_EXISTS means user was created between our check and create — treat as existing
            if "EMAIL_EXISTS" in error_msg:
                result = {
                    "status": "existing",
                    "firebase_uid": None,
                    "reset_link": None,
                    "reset_email_sent": False,
                    "message": "User already exists (race condition)",
                    "errors": [],
                }
                if generate_reset_link:
                    result["reset_email_sent"] = await _send_password_reset(email)
                return result
            return {"status": "failed", "errors": [error_msg]}

        firebase_uid = data.get("localId")
        logger.info(f"Firebase user created: {email} → uid={firebase_uid}")

        # Step 3: Send password reset email
        reset_sent = False
        if generate_reset_link:
            reset_sent = await _send_password_reset(email)

        return {
            "status": "created",
            "firebase_uid": firebase_uid,
            "reset_link": None,
            "reset_email_sent": reset_sent,
            "message": f"User created successfully (uid: {firebase_uid})"
                       + (" (reset email sent)" if reset_sent else ""),
            "errors": [],
        }

    except Exception as e:
        logger.error(f"Firebase ensure_user failed: {e}")
        return {"status": "failed", "errors": [str(e)]}


async def _send_password_reset(email: str) -> bool:
    """Send password reset email via Firebase REST API."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{_FIREBASE_BASE}/accounts:sendOobCode?key={FIREBASE_API_KEY}",
                json={"requestType": "PASSWORD_RESET", "email": email},
            )
            if resp.status_code == 200:
                logger.info(f"Password reset email sent to {email}")
                return True
            else:
                error = resp.json().get("error", {}).get("message", "Unknown")
                logger.warning(f"Password reset email failed for {email}: {error}")
                return False
    except Exception as e:
        logger.warning(f"Password reset email failed for {email}: {e}")
        return False
