import os
import random
import time
import urllib.parse
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

from logger import get_logger

log = get_logger("linkedin")


load_dotenv()

UGC_URL   = "https://api.linkedin.com/v2/ugcPosts"
ASSET_URL = "https://api.linkedin.com/v2/assets?action=registerUpload"

_RETRY_STATUSES = {429, 500, 502, 503, 504}


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }


def _request_with_retry(
    method: str,
    url: str,
    *,
    max_retries: int = 3,
    timeout: int = 30,
    **kwargs,
) -> requests.Response:
    """HTTP call with exponential backoff on transient errors.

    Retries on 429 / 5xx responses, requests.Timeout, requests.ConnectionError.
    Returns the final response — caller still invokes raise_for_status().
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = requests.request(method, url, timeout=timeout, **kwargs)
            if resp.status_code in _RETRY_STATUSES and attempt < max_retries - 1:
                delay = min(2 ** attempt + random.uniform(0, 1), 30)
                log.info(f"{method} {url} -> {resp.status_code}, retry in {delay:.1f}s")
                time.sleep(delay)
                continue
            return resp
        except (requests.Timeout, requests.ConnectionError) as e:
            last_exc = e
            if attempt == max_retries - 1:
                raise
            delay = min(2 ** attempt + random.uniform(0, 1), 30)
            log.warning(f"{method} {url} transient error: {str(e)[:120]} — retry in {delay:.1f}s")
            time.sleep(delay)
    if last_exc:
        raise last_exc
    raise RuntimeError("unreachable")


def _parse_result(resp: requests.Response) -> dict:
    post_id = resp.headers.get("x-restli-id", "unknown")
    return {
        "url": f"https://www.linkedin.com/feed/update/{post_id}/",
        "urn": post_id,
    }


def _author_urn() -> str:
    urn = os.environ.get("LINKEDIN_ORG_URN", "")
    if not urn:
        raise EnvironmentError("LINKEDIN_ORG_URN is required — personal posting is disabled")
    return urn


LINKEDIN_MAX_CHARS = 3000

_LINKEDIN_UPLOAD_HOSTS = {"linkedin.com", "licdn.com"}


def _validate_upload_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"Upload URL must use HTTPS: {url[:80]}")
    host = parsed.hostname or ""
    if not any(host == h or host.endswith("." + h) for h in _LINKEDIN_UPLOAD_HOSTS):
        raise ValueError(f"Upload URL host not trusted: {host!r}")


_IMAGE_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _image_content_type(path: str) -> str:
    return _IMAGE_CONTENT_TYPES.get(Path(path).suffix.lower(), "image/octet-stream")


def post_to_linkedin(text: str) -> dict:
    if len(text) > LINKEDIN_MAX_CHARS:
        raise ValueError(
            f"Post text is {len(text)} chars, exceeds LinkedIn max ({LINKEDIN_MAX_CHARS}). "
            "Shorten the post before publishing."
        )
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
    if not token:
        raise EnvironmentError("LINKEDIN_ACCESS_TOKEN is required but not set")
    person_urn = _author_urn()

    payload = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    resp = _request_with_retry("POST", UGC_URL, json=payload, headers=_headers(token))
    resp.raise_for_status()
    return _parse_result(resp)


def _register_image(token: str, person_urn: str) -> tuple[str, str]:
    payload = {
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "owner": person_urn,
            "serviceRelationships": [
                {"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}
            ],
        }
    }
    resp = _request_with_retry("POST", ASSET_URL, json=payload, headers=_headers(token))
    resp.raise_for_status()
    data = resp.json()["value"]
    upload_url = data["uploadMechanism"][
        "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
    ]["uploadUrl"]
    return upload_url, data["asset"]


def _upload_image_binary(upload_url: str, token: str, image_path: str):
    _validate_upload_url(upload_url)
    if not Path(image_path).exists():
        raise FileNotFoundError(f"Image not found: {image_path}")
    with open(image_path, "rb") as f:
        body = f.read()
    resp = _request_with_retry(
        "PUT",
        upload_url,
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": _image_content_type(image_path)},
        timeout=60,
    )
    resp.raise_for_status()


def post_to_linkedin_with_image(text: str, image_path: str) -> dict:
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
    if not token:
        raise EnvironmentError("LINKEDIN_ACCESS_TOKEN is required but not set")
    person_urn = _author_urn()

    upload_url, asset_urn = _register_image(token, person_urn)
    _upload_image_binary(upload_url, token, image_path)

    payload = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "IMAGE",
                "media": [
                    {
                        "status": "READY",
                        "description": {"text": ""},
                        "media": asset_urn,
                        "title": {"text": ""},
                    }
                ],
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    resp = _request_with_retry("POST", UGC_URL, json=payload, headers=_headers(token))
    resp.raise_for_status()
    return _parse_result(resp)


def post_to_linkedin_with_document(text: str, pdf_path: str) -> dict:
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
    if not token:
        raise EnvironmentError("LINKEDIN_ACCESS_TOKEN is required but not set")
    if not Path(pdf_path).exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    person_urn = _author_urn()

    payload = {
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-document"],
            "owner": person_urn,
            "serviceRelationships": [
                {"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}
            ],
        }
    }
    resp = _request_with_retry("POST", ASSET_URL, json=payload, headers=_headers(token))
    resp.raise_for_status()
    data = resp.json()["value"]
    upload_url = data["uploadMechanism"][
        "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
    ]["uploadUrl"]
    asset_urn = data["asset"]

    _validate_upload_url(upload_url)
    with open(pdf_path, "rb") as f:
        body = f.read()
    resp = _request_with_retry(
        "PUT",
        upload_url,
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/pdf"},
        timeout=60,
    )
    resp.raise_for_status()

    payload = {
        "author": person_urn,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "DOCUMENT",
                "media": [{"status": "READY", "media": asset_urn, "title": {"text": ""}}],
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    resp = _request_with_retry("POST", UGC_URL, json=payload, headers=_headers(token))
    resp.raise_for_status()
    return _parse_result(resp)


def post_first_comment(post_urn: str, comment_text: str) -> bool:
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
    if not token:
        raise EnvironmentError("LINKEDIN_ACCESS_TOKEN is required but not set")
    actor = _author_urn()
    encoded_urn = urllib.parse.quote(post_urn, safe="")
    payload = {
        "actor": actor,
        "message": {"text": comment_text},
    }
    try:
        resp = _request_with_retry(
            "POST",
            f"https://api.linkedin.com/v2/socialActions/{encoded_urn}/comments",
            json=payload,
            headers=_headers(token),
        )
    except (requests.Timeout, requests.ConnectionError) as e:
        print(f"  Warning: first comment failed (network): {e}")
        return False
    if not resp.ok:
        print(f"  Warning: first comment failed ({resp.status_code}): {resp.text[:200]}")
        return False
    return True


def get_post_stats(post_urn: str) -> dict:
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
    if not token or post_urn in ("", "unknown"):
        return {}
    try:
        encoded = urllib.parse.quote(post_urn, safe="")
        resp = requests.get(
            f"https://api.linkedin.com/v2/socialActions/{encoded}",
            headers=_headers(token),
            timeout=15,
        )
        if not resp.ok:
            return {}
        data = resp.json()
        return {
            "likes":    data.get("likesSummary", {}).get("totalLikes", 0),
            "comments": data.get("commentsSummary", {}).get("totalFirstLevelComments", 0),
        }
    except Exception as e:
        log.info(f"get_post_stats({post_urn[:40]}): {type(e).__name__}: {e}")
        return {}
