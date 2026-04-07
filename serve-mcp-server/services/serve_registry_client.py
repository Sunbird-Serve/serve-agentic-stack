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
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import httpx

from config import (
    VOLUNTEERING_SERVICE_URL,
    NEED_SERVICE_URL,
    FULFILL_SERVICE_URL,
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
        Tries both 10-digit and 91-prefixed formats since registry data is inconsistent.
        Returns the full user object on success, None if not found.
        """
        # Normalise to 10-digit Indian mobile
        digits = phone.strip().lstrip("+")
        if digits.startswith("91") and len(digits) == 12:
            digits = digits[2:]

        # Try 10-digit first
        url = f"{VOLUNTEERING_SERVICE_URL}/user/mobile"
        data = await _request("GET", url, params={"mobile": digits})
        if data and data.get("osid"):
            return self._normalise_user(data)

        # Fallback: try with 91 prefix (some records stored this way)
        data = await _request("GET", url, params={"mobile": f"91{digits}"})
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
        GET /user/user-profile/userId/1-{user_id}
        Returns the full user profile (skills, preferences, onboarding details).
        userId is prefixed with "1-" as required by the API.
        """
        prefixed_id = user_id if user_id.startswith("1-") else f"1-{user_id}"
        url = f"{VOLUNTEERING_SERVICE_URL}/user/user-profile/userId/{prefixed_id}"
        data = await _request("GET", url)
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

    async def get_approved_needs_bulk(self, max_entities: int = 50, max_needs_per_entity: int = 20) -> List[Dict]:
        """
        Fetch all approved needs across all entities in bulk.
        Returns enriched need details (with time_slots, subjects, grades).
        """
        entities = await self.search_entities(page=0, size=max_entities)
        all_needs = []
        for entity in entities:
            entity_id = entity.get("id")
            if not entity_id:
                continue
            raw_needs = await self.get_needs_for_entity(entity_id, page=0, size=max_needs_per_entity)
            for need in raw_needs:
                need_status = need.get("status", "")
                if need_status != "Approved":
                    continue
                need_id = need.get("id")
                if not need_id:
                    continue
                details = await self.get_need_details(need_id)
                if details and details.get("status") == "Approved":
                    details["school_name"] = entity.get("name", "")
                    details["entity_id"] = entity_id
                    all_needs.append(details)
        return all_needs

    async def get_need_details(self, need_id: str) -> Optional[Dict]:
        """
        GET /need/{needId}/details
        Returns enriched need with requirement, occurrence, and timeSlots.
        Flattens into an AI-friendly dict with subjects, grades, days, timeslots.
        """
        url = f"{NEED_SERVICE_URL}/need/{need_id}/details"
        data = await _request("GET", url)
        if not data:
            return None

        need = data.get("need", {})
        requirement = data.get("needRequirement", {})
        occurrence = data.get("occurrence", {})
        time_slots = data.get("timeSlots", [])

        # Parse subjects and grades from need name (e.g. "English Grade 6")
        name = need.get("name", "")
        subjects = []
        grades = []
        
        # Extract subjects from skillDetails if available
        skill_details = requirement.get("skillDetails", "")
        if skill_details:
            # "English, Teaching" → ["english"]
            parts = [p.strip().lower() for p in skill_details.split(",")]
            subjects = [p for p in parts if p and p != "teaching"]
        
        # Extract grade from name using regex
        import re
        grade_match = re.search(r"Grade\s+(\d+)", name, re.IGNORECASE)
        if grade_match:
            grades = [grade_match.group(1)]

        # Parse dates
        start_date = occurrence.get("startDate", "")
        end_date = occurrence.get("endDate", "")
        if start_date:
            start_date = start_date.split("T")[0]  # "2026-04-01T00:00:00Z" → "2026-04-01"
        if end_date:
            end_date = end_date.split("T")[0]

        # Parse days and frequency
        days = occurrence.get("days", "")
        frequency = occurrence.get("frequency", "")

        # Parse time slots
        parsed_slots = []
        for slot in time_slots:
            start_time = slot.get("startTime", "")
            end_time = slot.get("endTime", "")
            # Extract time portion: "2026-04-01T10:00:00Z" → "10:00"
            if start_time:
                start_time = start_time.split("T")[1].split(":")[0] + ":" + start_time.split("T")[1].split(":")[1]
            if end_time:
                end_time = end_time.split("T")[1].split(":")[0] + ":" + end_time.split("T")[1].split(":")[1]
            
            parsed_slots.append({
                "day": slot.get("day", ""),
                "startTime": start_time,
                "endTime": end_time,
            })

        return {
            "id": need.get("id"),
            "name": name,
            "entity_id": need.get("entityId", ""),
            "subjects": subjects,
            "grade_levels": grades,
            "days": days,
            "frequency": frequency,
            "start_date": start_date,
            "end_date": end_date,
            "time_slots": parsed_slots,
            "status": need.get("status"),
            "createdAt": need.get("createdAt"),
            "needPurpose": need.get("needPurpose", ""),
        }

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

        resolved_name = need_name or f"English {', '.join(f'Grade {g}' for g in grade_levels)} Teaching Support"

        # Days come from the pre-grouped draft (set by submit_for_approval)
        day_names = [d.strip().title() for d in (need_draft.get("days") or []) if d.strip()]
        days_str = ",".join(day_names)

        # Build timeSlots: one entry per day, all sharing the same time_slot string
        time_slot_str = (need_draft.get("time_slot") or "").strip()
        time_slots = []

        def _parse_time(t: str) -> str:
            """Parse HH:MM or HH:MM AM/PM → HH:MM:SS"""
            t = t.strip()
            am_pm = re.search(r'(am|pm)$', t, re.IGNORECASE)
            t_clean = re.sub(r'\s*(am|pm)$', '', t, flags=re.IGNORECASE).strip()
            parts = t_clean.replace('.', ':').split(':')
            hour = int(parts[0]) if parts else 10
            minute = int(parts[1]) if len(parts) > 1 else 0
            if am_pm:
                suffix = am_pm.group(1).lower()
                if suffix == 'pm' and hour != 12:
                    hour += 12
                elif suffix == 'am' and hour == 12:
                    hour = 0
            return f"{hour:02d}:{minute:02d}:00"

        slot_date = start_date or "2026-04-06"
        if time_slot_str:
            m = re.match(
                r'(\d{1,2}(?::\d{2})?(?:\s*[ap]m)?)\s*[-–to]+\s*(\d{1,2}(?::\d{2})?(?:\s*[ap]m)?)',
                time_slot_str, re.IGNORECASE
            )
            if m:
                start_t = _parse_time(m.group(1))
                end_t = _parse_time(m.group(2))
                for day_name in (day_names or ["Monday"]):
                    time_slots.append({
                        "day": day_name,
                        "startTime": f"{slot_date}T{start_t}Z",
                        "endTime": f"{slot_date}T{end_t}Z",
                    })

        # Fallback
        if not time_slots:
            for day_name in (day_names or ["Monday"]):
                time_slots.append({
                    "day": day_name,
                    "startTime": f"{slot_date}T10:00:00Z",
                    "endTime": f"{slot_date}T11:00:00Z",
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



# ─── Fulfillment Service Client ───────────────────────────────────────────────

class FulfillmentClient:
    """
    Calls the Serve Fulfillment Service.
    Handles fulfillment record reads and writes.

    Base URL: FULFILL_SERVICE_URL  (SERVE_BASE_URL + FULFILL_API_PATH)
    """

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_fulfillments_for_volunteer(
        self,
        volunteer_id: str,
        page: int = 0,
        size: int = 50,
    ) -> List[Dict]:
        """
        GET /fulfillment/volunteer-read/{assignedUserId}?page=&size=
        Returns all fulfillment records for a volunteer (paginated).
        """
        prefixed_id = volunteer_id if volunteer_id.startswith("1-") else f"1-{volunteer_id}"
        url = f"{FULFILL_SERVICE_URL}/fulfillment/volunteer-read/{prefixed_id}"
        data = await _request("GET", url, params={"page": page, "size": size})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("content", [])
        return []

    async def get_fulfillment_for_need(self, need_id: str) -> Optional[Dict]:
        """
        GET /fulfillment/fulfill-read/{needId}
        Returns the single fulfillment record for a need.
        """
        url = f"{FULFILL_SERVICE_URL}/fulfillment/fulfill-read/{need_id}"
        return await _request("GET", url)

    async def get_fulfillments_for_coordinator(
        self,
        coord_user_id: str,
        page: int = 0,
        size: int = 50,
    ) -> List[Dict]:
        """
        GET /fulfillment/coordinator-read/{coordUserId}?page=&size=
        Returns all fulfillment records for a coordinator.
        """
        url = f"{FULFILL_SERVICE_URL}/fulfillment/coordinator-read/{coord_user_id}"
        data = await _request("GET", url, params={"page": page, "size": size})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("content", [])
        return []

    # ── Write ─────────────────────────────────────────────────────────────────

    async def create_fulfillment(
        self,
        need_id: str,
        assigned_user_id: str,
        coord_user_id: str,
        need_plan_id: Optional[str] = None,
        occurrence_id: Optional[str] = None,
        fulfillment_status: str = "NotStarted",
    ) -> Optional[Dict]:
        """
        POST /fulfillment/{needId}
        Creates a fulfillment record linking a volunteer to a need.
        fulfillment_status: NotStarted | InProgress | Completed | Cancelled | Offline | Closed | Inactive
        """
        url = f"{FULFILL_SERVICE_URL}/fulfillment/{need_id}"
        payload: Dict[str, Any] = {
            "needId":            need_id,
            "assignedUserId":    assigned_user_id,
            "coordUserId":       coord_user_id,
            "fulfillmentStatus": fulfillment_status,
        }
        if need_plan_id:
            payload["needPlanId"] = need_plan_id
        if occurrence_id:
            payload["occurrenceId"] = occurrence_id
        return await _request("POST", url, json=payload)

    async def update_fulfillment(
        self,
        fulfillment_id: str,
        fulfillment_status: Optional[str] = None,
        assigned_user_id: Optional[str] = None,
        coord_user_id: Optional[str] = None,
        need_plan_id: Optional[str] = None,
        occurrence_id: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        PUT /fulfillment/update/{fulfillmentId}
        Updates a fulfillment record. All fields optional.
        """
        url = f"{FULFILL_SERVICE_URL}/fulfillment/update/{fulfillment_id}"
        payload: Dict[str, Any] = {}
        if fulfillment_status:
            payload["fulfillmentStatus"] = fulfillment_status
        if assigned_user_id:
            payload["assignedUserId"] = assigned_user_id
        if coord_user_id:
            payload["coordUserId"] = coord_user_id
        if need_plan_id:
            payload["needPlanId"] = need_plan_id
        if occurrence_id:
            payload["occurrenceId"] = occurrence_id
        return await _request("PUT", url, json=payload)


# ─── Nomination Service Client ────────────────────────────────────────────────

class NominationClient:
    """
    Calls the Serve Nomination Service.
    Handles volunteer nominations for needs.

    Base URL: FULFILL_SERVICE_URL  (same service, different path prefix)
    nominationStatus values: Nominated | Approved | Proposed | Backfill | Rejected
    """

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_nominations_for_volunteer(
        self,
        volunteer_id: str,
        page: int = 0,
        size: int = 50,
    ) -> List[Dict]:
        """
        GET /nomination/{nominatedUserId}?page=&size=
        Returns all nominations for a volunteer (paginated).
        """
        url = f"{FULFILL_SERVICE_URL}/nomination/{volunteer_id}"
        data = await _request("GET", url, params={"page": page, "size": size})
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("content", [])
        return []

    async def get_nominations_for_need(self, need_id: str) -> List[Dict]:
        """
        GET /nomination/{needId}/nominate
        Returns all nominations for a need.
        """
        url = f"{FULFILL_SERVICE_URL}/nomination/{need_id}/nominate"
        data = await _request("GET", url)
        return data if isinstance(data, list) else []

    async def get_nominations_for_need_by_status(
        self,
        need_id: str,
        status: str,
    ) -> List[Dict]:
        """
        GET /nomination/{needId}/nominate/{status}
        Returns nominations for a need filtered by status.
        status: Nominated | Approved | Proposed | Backfill | Rejected
        """
        url = f"{FULFILL_SERVICE_URL}/nomination/{need_id}/nominate/{status}"
        data = await _request("GET", url)
        return data if isinstance(data, list) else []

    async def get_recommended_not_nominated(self) -> List[Dict]:
        """
        GET /volunteer/recommendedNotNominated
        Returns recommended volunteers not yet nominated for any need.
        """
        url = f"{FULFILL_SERVICE_URL}/volunteer/recommendedNotNominated"
        data = await _request("GET", url)
        return data if isinstance(data, list) else []

    async def get_recommended_nominated(self) -> List[Dict]:
        """
        GET /volunteer/recommendedNominated
        Returns recommended volunteers already nominated.
        """
        url = f"{FULFILL_SERVICE_URL}/volunteer/recommendedNominated"
        data = await _request("GET", url)
        return data if isinstance(data, list) else []

    # ── Write ─────────────────────────────────────────────────────────────────

    async def nominate_volunteer(
        self,
        need_id: str,
        volunteer_id: str,
    ) -> Optional[Dict]:
        """
        POST /nomination/{needId}/nominate/{nominatedUserId}
        Nominates a volunteer for a need.
        Returns the created Nomination object with nominationStatus='Nominated'.
        """
        url = f"{FULFILL_SERVICE_URL}/nomination/{need_id}/nominate/{volunteer_id}"
        return await _request("POST", url, json={})

    async def confirm_nomination(
        self,
        volunteer_id: str,
        nomination_id: str,
        status: str,
    ) -> Optional[Dict]:
        """
        POST /nomination/nominate/{nominatedUserId}/confirm/{nominationId}?status={status}
        Confirms or rejects a nomination.
        status: Nominated | Approved | Proposed | Backfill | Rejected
        """
        url = f"{FULFILL_SERVICE_URL}/nomination/nominate/{volunteer_id}/confirm/{nomination_id}"
        return await _request("POST", url, params={"status": status}, json={})


# ─── Singletons ───────────────────────────────────────────────────────────────
volunteering_client = VolunteeringClient()
need_service_client = NeedServiceClient()
fulfillment_client  = FulfillmentClient()
nomination_client   = NominationClient()
