"""
SERVE MCP Server - Serve Registry & Need Service Client
HTTP client for all calls to external Serve platform services.

Two logical clients:
  VolunteeringClient  → Serve Volunteering Service (users, profiles)
  NeedServiceClient   → Serve Need Service (needs, entities/schools)

Base URL is configurable via SERVE_BASE_URL env var so any adopter
can point at their own deployment without code changes.
"""
import asyncio
import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import httpx

from config import (
    VOLUNTEERING_SERVICE_URL,
    NEED_SERVICE_URL,
    SERVE_BEARER_TOKEN,
    SERVE_REGISTRY_TIMEOUT,
    SERVE_REGISTRY_RETRIES,
    ONLINE_TEACHING_NEED_TYPE_ID,
    DEFAULT_NEED_STATUS,
    ENTITY_COORDINATOR_ROLE,
)

logger = logging.getLogger(__name__)


# ─── HTTP helper ──────────────────────────────────────────────────────────────

def _build_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if SERVE_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {SERVE_BEARER_TOKEN}"
    return headers


async def _request(
    method: str,
    url: str,
    *,
    params: Optional[Dict] = None,
    json: Optional[Dict] = None,
) -> Optional[Dict]:
    """
    Execute an HTTP request with retry on transient failures.
    Returns the parsed JSON body, or None on 404 / repeated failure.
    """
    last_error: Exception | None = None
    for attempt in range(SERVE_REGISTRY_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=SERVE_REGISTRY_TIMEOUT) as client:
                response = await client.request(
                    method,
                    url,
                    headers=_build_headers(),
                    params=params,
                    json=json,
                )
            if response.status_code == 404:
                return None
            if response.status_code >= 400:
                logger.warning(
                    f"[serve_registry] {method} {url} returned {response.status_code}: {response.text}"
                )
            if response.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"Server error {response.status_code}",
                    request=response.request,
                    response=response,
                )
            response.raise_for_status()
            return response.json() if response.content else {}
        except Exception as exc:
            last_error = exc
            if attempt < SERVE_REGISTRY_RETRIES:
                wait = 0.5 * (2 ** attempt)
                logger.warning(
                    f"[serve_registry] {method} {url} attempt {attempt+1} failed: {exc}. "
                    f"Retrying in {wait}s…"
                )
                await asyncio.sleep(wait)

    logger.error(f"[serve_registry] {method} {url} failed after {SERVE_REGISTRY_RETRIES+1} attempts: {last_error}")
    return None


# ─── Volunteering Service Client ──────────────────────────────────────────────

class VolunteeringClient:
    """
    Calls the Serve Volunteering Service.
    Handles user lookup, creation, and profile read/write.
    """

    # ── Identity Lookup ──────────────────────────────────────────────────────

    async def lookup_by_email(self, email: str) -> Optional[Dict]:
        """
        GET /user/email?email={email}
        Returns the full user object on success, None if not found.
        The `osid` field is the Serve Registry volunteer ID.
        """
        url = f"{VOLUNTEERING_SERVICE_URL}/user/email"
        data = await _request("GET", url, params={"email": email})
        if data and data.get("osid"):
            return self._normalise_user(data)
        return None

    async def lookup_by_mobile(self, phone: str) -> Optional[Dict]:
        """
        GET /user/mobile?mobile={phone}
        Strips country code prefix (+91 / 91) before calling — API expects 10-digit mobile.
        Returns the full user object on success, None if not found.
        """
        # Normalise to 10-digit Indian mobile
        digits = phone.strip().lstrip("+")
        if digits.startswith("91") and len(digits) == 12:
            digits = digits[2:]
        url = f"{VOLUNTEERING_SERVICE_URL}/user/mobile"
        data = await _request("GET", url, params={"mobile": digits})
        if data and data.get("osid"):
            return self._normalise_user(data)
        return None

    async def lookup_by_status(self, status: str = "ACTIVE") -> List[Dict]:
        """GET /user/status?status={status}"""
        url = f"{VOLUNTEERING_SERVICE_URL}/user/status"
        data = await _request("GET", url, params={"status": status})
        if isinstance(data, list):
            return [self._normalise_user(u) for u in data]
        return []

    # ── User Creation ─────────────────────────────────────────────────────────

    async def create_volunteer(
        self,
        full_name: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        country: str = "India",
    ) -> Optional[str]:
        """
        POST /user/
        Creates a volunteer stub in Serve Registry.
        Returns the new volunteer osid, or None on failure.
        """
        url = f"{VOLUNTEERING_SERVICE_URL}/user/"
        payload: Dict[str, Any] = {
            "role": ["VOLUNTEER"],
            "identityDetails": {
                "fullname": full_name,
                "name": full_name.split()[0] if full_name else "",
            },
            "contactDetails": {},
            "status": "ACTIVE",
        }
        if email:
            payload["contactDetails"]["email"] = email
        if phone:
            payload["contactDetails"]["mobile"] = phone
        if city or state:
            payload["contactDetails"]["address"] = {
                "city": city or "",
                "state": state or "",
                "country": country,
            }

        data = await _request("POST", url, json=payload)
        if data:
            # POST /user/ → { result: { Users: { osid: "..." } }, ... }
            osid = (
                data.get("result", {})
                    .get("Users", {})
                    .get("osid")
            )
            return osid
        return None

    async def create_coordinator(
        self,
        name: str,
        phone: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Optional[str]:
        """
        POST /user/ with role NEED_COORDINATOR.
        Returns the new coordinator osid.
        """
        url = f"{VOLUNTEERING_SERVICE_URL}/user/"
        payload: Dict[str, Any] = {
            "role": ["NEED_COORDINATOR"],
            "identityDetails": {
                "fullname": name,
                "name": name.split()[0] if name else "",
            },
            "contactDetails": {},
            "status": "ACTIVE",
        }
        if email:
            payload["contactDetails"]["email"] = email
        if phone:
            payload["contactDetails"]["mobile"] = phone

        data = await _request("POST", url, json=payload)
        if data:
            return (
                data.get("result", {})
                    .get("Users", {})
                    .get("osid")
            )
        return None

    # ── Profile Read / Write ──────────────────────────────────────────────────

    async def get_user_profile(self, user_id: str) -> Optional[Dict]:
        """
        GET /user/user-profile?userId={user_id}
        Returns the full user profile (skills, preferences, onboarding details).
        """
        url = f"{VOLUNTEERING_SERVICE_URL}/user/user-profile"
        data = await _request("GET", url, params={"userId": user_id})
        if data:
            return self._normalise_profile(data)
        return None

    async def save_volunteer_profile(
        self,
        volunteer_id: str,
        profile_data: Dict[str, Any],
        existing_profile_id: Optional[str] = None,
    ) -> bool:
        """
        Push collected volunteer fields back to Serve Registry.
        If existing_profile_id is given → PUT /user/user-profile/{id}
        Otherwise → POST /user/user-profile (first time)
        Returns True on success.
        """
        payload = self._build_profile_payload(volunteer_id, profile_data)

        if existing_profile_id:
            url = f"{VOLUNTEERING_SERVICE_URL}/user/user-profile/{existing_profile_id}"
            result = await _request("PUT", url, json=payload)
        else:
            url = f"{VOLUNTEERING_SERVICE_URL}/user/user-profile"
            result = await _request("POST", url, json=payload)

        return result is not None

    async def update_user(
        self,
        volunteer_id: str,
        profile_data: Dict[str, Any],
    ) -> bool:
        """
        PUT /user/{volunteer_id}
        Updates contactDetails and identityDetails on the user record.
        """
        payload: Dict[str, Any] = {
            "role": ["VOLUNTEER"],
            "contactDetails": {},
            "identityDetails": {},
        }
        if profile_data.get("full_name"):
            payload["identityDetails"]["fullname"] = profile_data["full_name"]
        if profile_data.get("first_name"):
            payload["identityDetails"]["name"] = profile_data["first_name"]
        if profile_data.get("email"):
            payload["contactDetails"]["email"] = profile_data["email"]
        if profile_data.get("phone"):
            payload["contactDetails"]["mobile"] = profile_data["phone"]
        if profile_data.get("location"):
            payload["contactDetails"]["address"] = {"city": profile_data["location"]}

        url = f"{VOLUNTEERING_SERVICE_URL}/user/{volunteer_id}"
        result = await _request("PUT", url, json=payload)
        return result is not None

    # ── Normalisation helpers ─────────────────────────────────────────────────

    def _normalise_user(self, raw: Dict) -> Dict:
        """Extract clean fields from the Sunbird RC user envelope."""
        contact = raw.get("contactDetails", {})
        address = contact.get("address", {})
        identity = raw.get("identityDetails", {})
        return {
            "osid":       raw.get("osid"),
            "role":       raw.get("role", []),
            "status":     raw.get("status"),
            "full_name":  identity.get("fullname"),
            "first_name": identity.get("name"),
            "gender":     identity.get("gender"),
            "dob":        identity.get("dob"),
            "email":      contact.get("email"),
            "phone":      contact.get("mobile"),
            "city":       address.get("city"),
            "state":      address.get("state"),
            "country":    address.get("country"),
        }

    def _normalise_profile(self, raw: Dict) -> Dict:
        """Extract clean fields from a user-profile response."""
        generic   = raw.get("genericDetails", {})
        pref      = raw.get("userPreference", {})
        onboard   = raw.get("onboardDetails", {})
        vol_hours = raw.get("volunteeringHours", {})
        skills_raw = raw.get("skills", [])

        skill_names  = [s.get("skillName") for s in skills_raw if s.get("skillName")]
        skill_levels = {s.get("skillName"): s.get("skillLevel") for s in skills_raw if s.get("skillName")}

        onboard_steps = onboard.get("onboardStatus", [])
        is_complete = any(
            s.get("status") == "COMPLETED"
            for s in onboard_steps
        )

        return {
            "profile_id":           raw.get("osid") or raw.get("id"),
            "user_id":              raw.get("userId"),
            "skills":               skill_names,
            "skill_levels":         skill_levels,
            "interests":            pref.get("interestArea", []),
            "languages":            pref.get("language", []),
            "days_preferred":       pref.get("dayPreferred", []),
            "time_preferred":       pref.get("timePreferred", []),
            "qualification":        generic.get("qualification"),
            "years_of_experience":  generic.get("yearsOfExperience"),
            "employment_status":    generic.get("employmentStatus"),
            "profile_completion_pct": int(onboard.get("profileCompletion", 0)),
            "onboarding_completed": is_complete,
            "total_hours":          vol_hours.get("totalHours"),
            "hours_per_week":       vol_hours.get("hoursPerWeek"),
        }

    def _build_profile_payload(self, volunteer_id: str, data: Dict) -> Dict:
        """Build the POST/PUT user-profile payload from MCP profile data."""
        skills_list = []
        skill_levels = data.get("skill_levels") or {}
        for skill in (data.get("skills") or []):
            skills_list.append({
                "skillName":  skill,
                "skillLevel": skill_levels.get(skill, "Beginner"),
            })

        days = data.get("days_preferred") or []
        times = data.get("time_preferred") or []
        # Legacy: if availability is a plain string, use it directly
        if not days and data.get("availability"):
            days = [data["availability"]]

        completion = data.get("profile_completion_pct", 0)

        payload: Dict[str, Any] = {
            "userId": volunteer_id,
            "genericDetails": {
                "qualification":     data.get("qualification", ""),
                "employmentStatus":  data.get("employment_status", ""),
                "yearsOfExperience": str(data.get("years_of_experience", "")),
            },
            "userPreference": {
                "language":     data.get("languages") or [],
                "dayPreferred": days,
                "timePreferred": times,
                "interestArea": data.get("interests") or [],
            },
            "skills": skills_list,
            "onboardDetails": {
                "onboardStatus": [
                    {"onboardStep": "PROFILE", "status": "COMPLETED"}
                ],
                "profileCompletion": str(completion),
            },
        }
        return payload


# ─── Need Service Client ──────────────────────────────────────────────────────

class NeedServiceClient:
    """
    Calls the Serve Need Service.
    Handles entity (school) lookup/creation and need lifecycle.
    """

    # ── Entity (School) Operations ────────────────────────────────────────────

    async def get_entities_for_user(self, user_id: str) -> List[Dict]:
        """
        GET /entityDetails/{userId}
        Returns all entities (schools) associated with a coordinator.
        """
        url = f"{NEED_SERVICE_URL}/entityDetails/{user_id}"
        data = await _request("GET", url, params={"page": 0, "size": 100})
        if data:
            content = data.get("content", data) if isinstance(data, dict) else data
            if isinstance(content, list):
                return [self._normalise_entity(e) for e in content]
        return []

    async def get_entity(self, entity_id: str) -> Optional[Dict]:
        """GET /entity/{entityId}"""
        url = f"{NEED_SERVICE_URL}/entity/{entity_id}"
        data = await _request("GET", url)
        return self._normalise_entity(data) if data else None

    async def search_entities(
        self,
        status: str = "Active",
        page: int = 0,
        size: int = 100,
    ) -> List[Dict]:
        """GET /entity/all — returns all entities for client-side filtering."""
        url = f"{NEED_SERVICE_URL}/entity/all"
        data = await _request("GET", url, params={"page": page, "size": size})
        if data:
            content = data.get("content", []) if isinstance(data, dict) else data
            return [self._normalise_entity(e) for e in content]
        return []

    async def create_entity(
        self,
        name: str,
        location: str,
        contact_number: Optional[str] = None,
        district: Optional[str] = None,
        state: Optional[str] = None,
        category: str = "School",
    ) -> Optional[Dict]:
        """
        POST /entity/create
        Returns normalised entity dict with `id` on success.
        """
        url = f"{NEED_SERVICE_URL}/entity/create"
        payload: Dict[str, Any] = {
            "name":     name,
            "district": district or location,
            "state":    state or "",
            "category": category,
            "status":   "Active",
        }
        if contact_number:
            payload["mobile"] = contact_number
        data = await _request("POST", url, json=payload)
        return self._normalise_entity(data) if data else None

    async def assign_user_to_entity(
        self,
        entity_id: str,
        user_id: str,
        user_role: str = ENTITY_COORDINATOR_ROLE,
    ) -> bool:
        """
        POST /entity/assign
        Links a coordinator (userId) to an entity (school).
        """
        url = f"{NEED_SERVICE_URL}/entity/assign"
        payload = {
            "entityId": entity_id,
            "userId":   user_id,
            "userRole": user_role,
        }
        result = await _request("POST", url, json=payload)
        return result is not None

    # ── Need Operations ───────────────────────────────────────────────────────

    async def get_needs_for_entity(
        self,
        entity_id: str,
        page: int = 0,
        size: int = 20,
    ) -> List[Dict]:
        """GET /need/entity/{entityId}"""
        url = f"{NEED_SERVICE_URL}/need/entity/{entity_id}"
        data = await _request("GET", url, params={"page": page, "size": size})
        if data:
            content = data.get("content", []) if isinstance(data, dict) else data
            return content if isinstance(content, list) else []
        return []

    async def get_need(self, need_id: str) -> Optional[Dict]:
        """GET /need/{needId}"""
        url = f"{NEED_SERVICE_URL}/need/{need_id}"
        return await _request("GET", url)

    async def raise_need(
        self,
        coordinator_osid: str,
        entity_id: str,
        need_draft: Dict[str, Any],
        need_name: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        POST /need/raise
        Submits a completed need draft to the Serve Need Service.
        Returns the created Need object (including its id).
        """
        url = f"{NEED_SERVICE_URL}/need/raise"

        # Compute end date from start_date + duration_weeks; default to March 31, 2027
        start_date = need_draft.get("start_date", "")
        end_date = need_draft.get("end_date", "")
        if start_date and not end_date and need_draft.get("duration_weeks"):
            try:
                sd = date.fromisoformat(start_date)
                ed = sd + timedelta(weeks=int(need_draft["duration_weeks"]))
                end_date = ed.isoformat()
            except Exception:
                pass
        if not end_date:
            end_date = "2027-03-31"

        subjects = need_draft.get("subjects") or []
        grade_levels = need_draft.get("grade_levels") or []
        skill_detail = f"{', '.join(s.title() for s in subjects)}, Teaching"

        resolved_name = need_name or f"Teaching Need — {', '.join(subjects)}"

        # Build days string: "Monday,Wednesday" (no spaces)
        schedule = need_draft.get("schedule_preference") or ""
        days_str = ",".join(d.strip().title() for d in schedule.split(",") if d.strip())

        # Build timeSlots with full ISO datetime strings as required by the API
        # Use start_date as the anchor date for slot datetimes
        anchor = start_date or end_date or "2026-04-01"
        try:
            anchor_date = date.fromisoformat(anchor)
        except Exception:
            anchor_date = date(2026, 4, 1)

        day_names = [d.strip().title() for d in schedule.split(",") if d.strip()]
        time_slots = []
        for day_name in day_names:
            slot_date = anchor_date.isoformat()
            time_slots.append({
                "day":       day_name,
                "startTime": f"{slot_date}T10:00:00Z",
                "endTime":   f"{slot_date}T11:00:00Z",
            })

        payload = {
            "needRequest": {
                "needTypeId":  ONLINE_TEACHING_NEED_TYPE_ID,
                "name":        resolved_name,
                "needPurpose": f"Teach {', '.join(s.title() for s in subjects)} to Grade {', '.join(str(g) for g in grade_levels)} students",
                "description": need_draft.get("special_requirements") or "",
                "status":      DEFAULT_NEED_STATUS,
                "userId":      coordinator_osid,
                "entityId":    entity_id,
            },
            "needRequirementRequest": {
                "skillDetails":       skill_detail,
                "volunteersRequired": str(need_draft.get("student_count") or ""),
                "priority":           "Medium",
                "occurrence": {
                    "startDate": f"{start_date}T00:00:00Z" if start_date else "",
                    "endDate":   f"{end_date}T00:00:00Z"   if end_date   else "",
                    "days":      days_str,
                    "frequency": "Weekly",
                    "timeSlots": time_slots,
                },
            },
        }

        import json as _json
        logger.info(f"[raise_need] payload: {_json.dumps(payload, default=str)}")
        data = await _request("POST", url, json=payload)
        return data

    async def update_need_status(
        self,
        need_id: str,
        status: str,
    ) -> Optional[Dict]:
        """PUT /need/status/{needId}?status={status}"""
        url = f"{NEED_SERVICE_URL}/need/status/{need_id}"
        return await _request("PUT", url, params={"status": status})

    async def update_need(
        self,
        need_id: str,
        need_draft: Dict[str, Any],
        coordinator_osid: str,
        entity_id: str,
    ) -> Optional[Dict]:
        """PUT /need/update/{needId}"""
        url = f"{NEED_SERVICE_URL}/need/update/{need_id}"
        time_slots = need_draft.get("time_slots") or []
        subjects = need_draft.get("subjects") or []
        grade_levels = need_draft.get("grade_levels") or []

        payload = {
            "needRequest": {
                "needTypeId": ONLINE_TEACHING_NEED_TYPE_ID,
                "name":       f"Teaching Need — {', '.join(subjects)}",
                "description": need_draft.get("special_requirements") or "",
                "userId":     coordinator_osid,
                "entityId":   entity_id,
            },
            "needRequirementRequest": {
                "skillDetails":       f"Subjects: {', '.join(subjects)}. Grades: {', '.join(grade_levels)}.",
                "volunteersRequired": str(need_draft.get("student_count") or ""),
                "occurrence": {
                    "startDate":  f"{need_draft.get('start_date', '')}T00:00:00Z",
                    "timeSlots":  time_slots,
                    "frequency":  need_draft.get("schedule_preference") or "Weekly",
                },
            },
        }
        return await _request("PUT", url, json=payload)

    # ── Normalisation ─────────────────────────────────────────────────────────

    def _normalise_entity(self, raw: Dict) -> Dict:
        if not raw:
            return {}
        return {
            "id":       str(raw.get("id", "")),
            "name":     raw.get("name", ""),
            "district": raw.get("district", ""),
            "state":    raw.get("state", ""),
            "location": f"{raw.get('district', '')} {raw.get('state', '')}".strip(),
            "mobile":   str(raw.get("mobile", "")),
            "category": raw.get("category", ""),
            "status":   raw.get("status", ""),
        }


# ─── Singletons ───────────────────────────────────────────────────────────────
volunteering_client = VolunteeringClient()
need_service_client = NeedServiceClient()
