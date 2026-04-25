"""
WhatsApp Media Upload + Cache

Uploads local video files to WhatsApp Cloud API and caches media_ids
to avoid re-uploading the same file. Handles stale media_id invalidation.
"""
import hashlib
import logging
import os
from typing import Dict, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

_WA_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
_WA_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
_WA_GRAPH_URL = "https://graph.facebook.com/v18.0"

# Cache: hash(file_content + phone_number_id) → media_id
_media_cache: Dict[str, str] = {}


def _file_hash(file_bytes: bytes) -> str:
    """SHA256 hash of file content + phone number ID for cache key."""
    h = hashlib.sha256()
    h.update(file_bytes)
    h.update((_WA_PHONE_NUMBER_ID or "").encode())
    return h.hexdigest()


async def upload_media(file_bytes: bytes, mime_type: str = "video/mp4", filename: str = "video.mp4") -> Optional[str]:
    """
    Upload media to WhatsApp Cloud API. Returns media_id on success.
    Uses cache to avoid re-uploading the same file.
    """
    if not _WA_TOKEN or not _WA_PHONE_NUMBER_ID:
        logger.warning("WhatsApp not configured — cannot upload media")
        return None

    cache_key = _file_hash(file_bytes)
    if cache_key in _media_cache:
        logger.info(f"WhatsApp media cache hit for {filename}")
        return _media_cache[cache_key]

    url = f"{_WA_GRAPH_URL}/{_WA_PHONE_NUMBER_ID}/media"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {_WA_TOKEN}"},
                files={"file": (filename, file_bytes, mime_type)},
                data={"messaging_product": "whatsapp", "type": mime_type},
            )
            resp.raise_for_status()
            data = resp.json()
            media_id = data.get("id")
            if media_id:
                _media_cache[cache_key] = media_id
                logger.info(f"WhatsApp media uploaded: {filename} → media_id={media_id}")
                return media_id
            else:
                logger.error(f"WhatsApp media upload returned no id: {data}")
                return None
    except Exception as e:
        logger.error(f"WhatsApp media upload failed: {e}")
        return None


def invalidate_cache(file_bytes: bytes) -> None:
    """Remove a cached media_id (e.g. when WhatsApp returns stale ID error)."""
    cache_key = _file_hash(file_bytes)
    _media_cache.pop(cache_key, None)


async def send_video_message(to: str, media_id: str, caption: str = "") -> bool:
    """Send a video message using a previously uploaded media_id."""
    if not _WA_TOKEN or not _WA_PHONE_NUMBER_ID:
        return False

    url = f"{_WA_GRAPH_URL}/{_WA_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "video",
        "video": {"id": media_id},
    }
    if caption:
        payload["video"]["caption"] = caption

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {_WA_TOKEN}", "Content-Type": "application/json"},
                json=payload,
            )
            if resp.status_code == 400 and "invalid media" in resp.text.lower():
                logger.warning(f"WhatsApp stale media_id — will retry after re-upload")
                return False
            resp.raise_for_status()
            return True
    except Exception as e:
        logger.error(f"WhatsApp video send failed: {e}")
        return False


async def fetch_and_send_video(to: str, video_url: str, caption: str = "") -> bool:
    """
    Fetch a video from a URL, upload to WhatsApp, and send as a video message.
    Handles caching and stale media_id retry.
    """
    # Fetch the video file
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(video_url)
            resp.raise_for_status()
            file_bytes = resp.content
            filename = video_url.split("/")[-1] or "video.mp4"
    except Exception as e:
        logger.error(f"Failed to fetch video from {video_url}: {e}")
        return False

    # Upload to WhatsApp
    media_id = await upload_media(file_bytes, "video/mp4", filename)
    if not media_id:
        return False

    # Send
    ok = await send_video_message(to, media_id, caption)
    if not ok:
        # Retry: invalidate cache, re-upload, re-send
        invalidate_cache(file_bytes)
        media_id = await upload_media(file_bytes, "video/mp4", filename)
        if media_id:
            ok = await send_video_message(to, media_id, caption)
    return ok
