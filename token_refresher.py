"""
Refreshes the LinkedIn access token using the stored refresh token.
Runs as a GitHub Action every 50 days (before the 60-day expiry).

Required env vars:
  LINKEDIN_CLIENT_ID
  LINKEDIN_CLIENT_SECRET
  LINKEDIN_REFRESH_TOKEN
  GITHUB_PAT           — Personal Access Token with secrets:write scope
  GITHUB_REPO          — e.g. "username/posting-agent"

Optional:
  DISCORD_BOT_TOKEN
  DISCORD_ANALYTICS_CHANNEL_ID

Usage: python token_refresher.py
"""

import os
import sys

import requests
from dotenv import load_dotenv, set_key

load_dotenv()

TOKEN_URL  = "https://www.linkedin.com/oauth/v2/accessToken"
GITHUB_API = "https://api.github.com"
ENV_FILE   = ".env"


def refresh_linkedin_token() -> dict:
    client_id     = os.environ.get("LINKEDIN_CLIENT_ID", "")
    client_secret = os.environ.get("LINKEDIN_CLIENT_SECRET", "")
    refresh_token = os.environ.get("LINKEDIN_REFRESH_TOKEN", "")

    if not client_id or not client_secret:
        raise ValueError("LINKEDIN_CLIENT_ID or LINKEDIN_CLIENT_SECRET not set.")

    if not refresh_token:
        raise ValueError(
            "LINKEDIN_REFRESH_TOKEN is not set. Re-run: python linkedin_auth.py"
        )

    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
            "client_id":     client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _get_repo_public_key(repo: str, pat: str) -> tuple[str, str]:
    resp = requests.get(
        f"{GITHUB_API}/repos/{repo}/actions/secrets/public-key",
        headers={"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["key_id"], data["key"]


def _encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    from base64 import b64decode, b64encode
    try:
        from nacl import encoding, public
    except ImportError:
        raise ImportError("PyNaCl required. Add 'PyNaCl' to requirements.txt and re-install.")
    pk_bytes  = b64decode(public_key_b64)
    pk        = public.PublicKey(pk_bytes, encoding.RawEncoder)
    box       = public.SealedBox(pk)
    encrypted = box.encrypt(secret_value.encode("utf-8"))
    return b64encode(encrypted).decode("utf-8")


def update_github_secret(repo: str, secret_name: str, secret_value: str, pat: str) -> None:
    key_id, public_key = _get_repo_public_key(repo, pat)
    encrypted = _encrypt_secret(public_key, secret_value)
    resp = requests.put(
        f"{GITHUB_API}/repos/{repo}/actions/secrets/{secret_name}",
        headers={"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"},
        json={"encrypted_value": encrypted, "key_id": key_id},
        timeout=10,
    )
    resp.raise_for_status()


def _notify_discord(message: str) -> None:
    token      = os.environ.get("DISCORD_BOT_TOKEN", "")
    channel_id = os.environ.get("DISCORD_ANALYTICS_CHANNEL_ID", "")
    if not token or not channel_id:
        return
    try:
        requests.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            json={"content": message},
            headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
            timeout=10,
        )
    except Exception as e:
        print(f"  [token_refresher] Discord alert failed: {e}")


def main():
    repo = os.environ.get("GITHUB_REPO", "")
    pat  = os.environ.get("GITHUB_PAT", "")

    print("Refreshing LinkedIn access token...")
    try:
        result = refresh_linkedin_token()
    except Exception as e:
        msg = f"❌ **LinkedIn token refresh FAILED** — manual re-auth needed.\nRun: python linkedin_auth.py\nError: {e}"
        print(msg)
        _notify_discord(msg)
        sys.exit(1)

    new_access_token  = result["access_token"]
    new_refresh_token = result.get("refresh_token", "")
    expires_in        = result.get("expires_in", 5184000)
    days              = expires_in // 86400

    print(f"  New token received (expires in {days} days).")

    if repo and pat:
        print("  Updating GitHub secrets...")
        try:
            update_github_secret(repo, "LINKEDIN_ACCESS_TOKEN", new_access_token, pat)
            if new_refresh_token:
                update_github_secret(repo, "LINKEDIN_REFRESH_TOKEN", new_refresh_token, pat)
            print("  GitHub secrets updated.")
            _notify_discord(
                f"✅ **LinkedIn token auto-refreshed** (expires in {days} days). GitHub secrets updated."
            )
        except Exception as e:
            msg = f"⚠️ **LinkedIn token refreshed but GitHub secret update FAILED** — update manually.\nError: {e}"
            print(msg)
            _notify_discord(msg)
            sys.exit(1)
    else:
        print("  GITHUB_REPO or GITHUB_PAT not set — saving to local .env only.")
        set_key(ENV_FILE, "LINKEDIN_ACCESS_TOKEN", new_access_token)
        if new_refresh_token:
            set_key(ENV_FILE, "LINKEDIN_REFRESH_TOKEN", new_refresh_token)
        _notify_discord(
            f"✅ **LinkedIn token refreshed** (expires in {days} days). Saved to local .env (no GitHub PAT configured)."
        )
    print("Done.")


if __name__ == "__main__":
    main()
