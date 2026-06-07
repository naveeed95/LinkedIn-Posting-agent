import os
import random
import time
import urllib.parse

import requests
from dotenv import load_dotenv

from logger import get_logger

log = get_logger("linkedin")


load_dotenv()

UGC_URL = "https://api.linkedin.com/v2/ugcPosts"

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
