import os
import urllib.parse

import requests
from dotenv import load_dotenv

load_dotenv()

UGC_URL   = "https://api.linkedin.com/v2/ugcPosts"
ASSET_URL = "https://api.linkedin.com/v2/assets?action=registerUpload"


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }


def _parse_result(resp: requests.Response) -> dict:
    post_id = resp.headers.get("x-restli-id", "unknown")
    return {
        "url": f"https://www.linkedin.com/feed/update/{post_id}/",
        "urn": post_id,
    }


def _author_urn() -> str:
    return os.environ.get("LINKEDIN_ORG_URN") or os.environ["LINKEDIN_PERSON_URN"]


def post_to_linkedin(text: str) -> dict:
    token = os.environ["LINKEDIN_ACCESS_TOKEN"]
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
    resp = requests.post(UGC_URL, json=payload, headers=_headers(token))
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
    resp = requests.post(ASSET_URL, json=payload, headers=_headers(token))
    resp.raise_for_status()
    data = resp.json()["value"]
    upload_url = data["uploadMechanism"][
        "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
    ]["uploadUrl"]
    return upload_url, data["asset"]


def _upload_image_binary(upload_url: str, token: str, image_path: str):
    with open(image_path, "rb") as f:
        resp = requests.put(
            upload_url,
            data=f,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "image/png"},
        )
    resp.raise_for_status()


def post_to_linkedin_with_image(text: str, image_path: str) -> dict:
    token = os.environ["LINKEDIN_ACCESS_TOKEN"]
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
    resp = requests.post(UGC_URL, json=payload, headers=_headers(token))
    resp.raise_for_status()
    return _parse_result(resp)


def post_to_linkedin_with_document(text: str, pdf_path: str) -> dict:
    token = os.environ["LINKEDIN_ACCESS_TOKEN"]
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
    resp = requests.post(ASSET_URL, json=payload, headers=_headers(token))
    resp.raise_for_status()
    data = resp.json()["value"]
    upload_url = data["uploadMechanism"][
        "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
    ]["uploadUrl"]
    asset_urn = data["asset"]

    with open(pdf_path, "rb") as f:
        resp = requests.put(
            upload_url,
            data=f,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/pdf"},
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
    resp = requests.post(UGC_URL, json=payload, headers=_headers(token))
    resp.raise_for_status()
    return _parse_result(resp)


def post_first_comment(post_urn: str, comment_text: str) -> bool:
    token = os.environ["LINKEDIN_ACCESS_TOKEN"]
    actor = _author_urn()
    encoded_urn = urllib.parse.quote(post_urn, safe="")
    payload = {
        "actor": actor,
        "message": {"text": comment_text},
    }
    resp = requests.post(
        f"https://api.linkedin.com/v2/socialActions/{encoded_urn}/comments",
        json=payload,
        headers=_headers(token),
    )
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
        )
        if not resp.ok:
            return {}
        data = resp.json()
        return {
            "likes":    data.get("likesSummary", {}).get("totalLikes", 0),
            "comments": data.get("commentsSummary", {}).get("totalFirstLevelComments", 0),
        }
    except Exception:
        return {}
