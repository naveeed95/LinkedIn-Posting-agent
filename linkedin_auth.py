"""
Run this once to authenticate with LinkedIn.
Opens a browser, asks you to approve access,
then saves your access token and org URN to .env automatically.

Usage: python linkedin_auth.py
"""

import os
import webbrowser
import urllib.parse
import http.server
import threading
import requests
from dotenv import load_dotenv, set_key

load_dotenv()

CLIENT_ID     = os.environ["LINKEDIN_CLIENT_ID"]
CLIENT_SECRET = os.environ["LINKEDIN_CLIENT_SECRET"]
REDIRECT_URI  = "http://localhost:8000/callback"
SCOPE         = "w_member_social w_organization_social rw_organization_admin openid profile"
ENV_FILE      = ".env"

auth_code_holder = {}


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            auth_code_holder["code"] = params["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h2>Auth successful! You can close this tab.</h2>")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"<h2>Auth failed. No code received.</h2>")

    def log_message(self, format, *args):
        pass


def get_auth_code():
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
    }
    url = "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode(params)

    server = http.server.HTTPServer(("localhost", 8000), CallbackHandler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()

    print("Opening LinkedIn in your browser...")
    webbrowser.open(url)
    thread.join(timeout=120)
    server.server_close()

    return auth_code_holder.get("code")


def exchange_code_for_token(code: str) -> str:
    resp = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_person_urn(access_token: str) -> str:
    resp = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    resp.raise_for_status()
    return f"urn:li:person:{resp.json()['sub']}"


def get_org_urn(access_token: str) -> str | None:
    resp = requests.get(
        "https://api.linkedin.com/v2/organizationAcls",
        params={"q": "roleAssignee", "role": "ADMINISTRATOR", "state": "APPROVED"},
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
        },
    )
    if not resp.ok:
        print(f"  Warning: Could not fetch org list ({resp.status_code}). Check app permissions.")
        return None

    elements = resp.json().get("elements", [])
    if not elements:
        print("  No administered pages found. Make sure you are an admin of the company page.")
        return None

    if len(elements) == 1:
        return elements[0]["organization"]

    print("\nMultiple company pages found:")
    for i, el in enumerate(elements):
        print(f"  {i+1}. {el['organization']}")
    choice = input("Which page should posts come from? Enter number: ").strip()
    try:
        return elements[int(choice) - 1]["organization"]
    except (ValueError, IndexError):
        return elements[0]["organization"]


def main():
    code = get_auth_code()
    if not code:
        print("ERROR: Did not receive auth code. Try again.")
        return

    print("Exchanging code for access token...")
    token = exchange_code_for_token(code)

    print("Fetching your LinkedIn profile URN...")
    person_urn = get_person_urn(token)

    print("Fetching your company page URN...")
    org_urn = get_org_urn(token)

    set_key(ENV_FILE, "LINKEDIN_ACCESS_TOKEN", token)
    set_key(ENV_FILE, "LINKEDIN_PERSON_URN", person_urn)

    if org_urn:
        set_key(ENV_FILE, "LINKEDIN_ORG_URN", org_urn)

    print(f"\nSuccess! Saved to .env:")
    print(f"  LINKEDIN_PERSON_URN = {person_urn}")
    if org_urn:
        print(f"  LINKEDIN_ORG_URN    = {org_urn}")
    else:
        print("  LINKEDIN_ORG_URN    = not found — add manually to .env")
    print(f"  LINKEDIN_ACCESS_TOKEN = [hidden]")
    print("\nYou can now run: python run.py")


if __name__ == "__main__":
    main()
