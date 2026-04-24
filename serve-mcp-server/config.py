"""
SERVE MCP Server - Central Configuration
All environment variables and constants in one place.
Change SERVE_BASE_URL to point at any deployment (sandbox, staging, production).
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── Serve Platform Base URL ─────────────────────────────────────────────────
# Single base URL for all Serve platform services.
# Sandbox : https://serve-v1.evean.net
# Override with SERVE_BASE_URL env var for other deployments / adopters.
SERVE_BASE_URL = os.environ.get("SERVE_BASE_URL", "https://serve-v1.evean.net")

# ─── Service Path Prefixes ────────────────────────────────────────────────────
VOLUNTEERING_API_PATH = os.environ.get(
    "VOLUNTEERING_API_PATH", "/api/v1/serve-volunteering"
)
NEED_API_PATH = os.environ.get(
    "NEED_API_PATH", "/api/v1/serve-need"
)
FULFILL_API_PATH = os.environ.get(
    "FULFILL_API_PATH", "/api/v1/serve-fulfill"
)

# Fully resolved base URLs (used by registry clients)
VOLUNTEERING_SERVICE_URL = f"{SERVE_BASE_URL}{VOLUNTEERING_API_PATH}"
NEED_SERVICE_URL = f"{SERVE_BASE_URL}{NEED_API_PATH}"
FULFILL_SERVICE_URL = f"{SERVE_BASE_URL}{FULFILL_API_PATH}"

# ─── Auth ─────────────────────────────────────────────────────────────────────
# No auth required in current sandbox. Set SERVE_BEARER_TOKEN for auth-enabled
# deployments; an empty string means the Authorization header is omitted.
SERVE_BEARER_TOKEN = os.environ.get("SERVE_BEARER_TOKEN", "")

# Agency ID for volunteer registration
SERVE_AGENCY_ID = os.environ.get("SERVE_AGENCY_ID", "1-74f81200-dc16-4c65-bf7a-a3ab75952432")

# Static API key protecting the dashboard endpoints.
# Set DASHBOARD_API_KEY in .env — if empty, dashboard is unprotected (dev only).
DASHBOARD_API_KEY = os.environ.get("DASHBOARD_API_KEY", "")

# ─── HTTP Client Settings ─────────────────────────────────────────────────────
SERVE_REGISTRY_TIMEOUT = int(os.environ.get("SERVE_REGISTRY_TIMEOUT", "10"))
SERVE_REGISTRY_RETRIES = int(os.environ.get("SERVE_REGISTRY_RETRIES", "2"))

# ─── MCP Server ───────────────────────────────────────────────────────────────
MCP_PORT = int(os.environ.get("PORT", "8004"))
MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0")

# ─── Database ─────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://serve:servepassword@localhost:5432/serve_db"
)

# ─── Need Service Constants ───────────────────────────────────────────────────
# Fixed needTypeId for "Online Teaching" needs.
# Override with NEED_TYPE_ID env var if the platform uses a different type.
ONLINE_TEACHING_NEED_TYPE_ID = os.environ.get(
    "NEED_TYPE_ID", "e916a99a-554d-44a6-a714-44d227849ac0"
)

# Default need status on creation
DEFAULT_NEED_STATUS = os.environ.get("DEFAULT_NEED_STATUS", "New")

# ─── Actor Registry Cache TTL ─────────────────────────────────────────────────
# How many hours before we re-validate an actor against the Serve Registry.
ACTOR_CACHE_TTL_HOURS = int(os.environ.get("ACTOR_CACHE_TTL_HOURS", "24"))

# ─── User Roles ───────────────────────────────────────────────────────────────
VOLUNTEER_ROLE = "VOLUNTEER"
COORDINATOR_ROLE = "NEED_COORDINATOR"

# ─── User Types (S1-S5 classification) ───────────────────────────────────────
USER_TYPE_NEW = "new_user"                  # S1: brand new, not in Serve Registry
USER_TYPE_REGISTRY_KNOWN = "registry_known" # S2: in Serve Registry, new to AI
USER_TYPE_RETURNING = "returning_ai_user"   # S3: returning AI user
USER_TYPE_COORDINATOR = "coordinator"       # S4: need coordinator
USER_TYPE_ANONYMOUS = "anonymous"           # S5: no identity (web visitor)

# ─── Identity Types ───────────────────────────────────────────────────────────
IDENTITY_EMAIL = "email"
IDENTITY_PHONE = "phone"
IDENTITY_SESSION = "session_id"
IDENTITY_SYSTEM = "system"

# ─── Entity (School) User Roles ───────────────────────────────────────────────
ENTITY_COORDINATOR_ROLE = os.environ.get("ENTITY_COORDINATOR_ROLE", "Coordinator")
