"""
One-time (well, re-run when refresh token expires) OAuth2 login for the Oura
API. Opens your browser to Oura's consent screen, catches the redirect on
localhost, exchanges the code for an access/refresh token pair, and saves
them to tokens.json.

Requires OURA_CLIENT_ID, OURA_CLIENT_SECRET, OURA_REDIRECT_URI in .env.
"""

import json
import os
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.environ.get("OURA_CLIENT_ID")
CLIENT_SECRET = os.environ.get("OURA_CLIENT_SECRET")
REDIRECT_URI = os.environ.get("OURA_REDIRECT_URI", "http://localhost:8080/callback")

if not CLIENT_ID or not CLIENT_SECRET:
    sys.exit("Missing OURA_CLIENT_ID / OURA_CLIENT_SECRET in .env")

AUTH_URL = "https://cloud.ouraring.com/oauth/authorize"
TOKEN_URL = "https://api.ouraring.com/oauth/token"
SCOPES = "email personal daily heartrate workout tag session spo2 ring_configuration stress heart_health"
TOKENS_PATH = Path(__file__).parent / "tokens.json"

_captured_code = {}


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        if "code" in params:
            _captured_code["code"] = params["code"][0]
            self.wfile.write(b"<html><body>Login successful, you can close this tab.</body></html>")
        else:
            self.wfile.write(b"<html><body>No code received. Check the terminal.</body></html>")

    def log_message(self, format, *args):
        pass  # silence default request logging


def main():
    parsed_redirect = urlparse(REDIRECT_URI)
    port = parsed_redirect.port or 8080

    auth_params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": "oura-app-local",
    }
    url = f"{AUTH_URL}?{urlencode(auth_params)}"
    print(f"Opening browser for Oura login:\n{url}\n")
    webbrowser.open(url)

    server = HTTPServer(("localhost", port), CallbackHandler)
    print(f"Waiting for redirect on {REDIRECT_URI} ...")
    while "code" not in _captured_code:
        server.handle_request()

    code = _captured_code["code"]
    print("Got authorization code, exchanging for tokens...")

    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        sys.exit(f"Token exchange failed: HTTP {resp.status_code}: {resp.text}")

    tokens = resp.json()
    tokens["_fetched_at"] = time.time()
    with open(TOKENS_PATH, "w") as f:
        json.dump(tokens, f, indent=2)

    print(f"Saved tokens to {TOKENS_PATH}")
    print(f"Access token expires in {tokens.get('expires_in')} seconds; refresh_token saved for renewal.")


if __name__ == "__main__":
    main()
