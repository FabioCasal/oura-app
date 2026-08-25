"""
Shared helper: return a valid Oura access token, refreshing it via the
saved refresh_token if it's expired. Run oauth_login.py first to create
tokens.json.
"""

import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.environ.get("OURA_CLIENT_ID")
CLIENT_SECRET = os.environ.get("OURA_CLIENT_SECRET")
TOKEN_URL = "https://api.ouraring.com/oauth/token"
TOKENS_PATH = Path(__file__).parent / "tokens.json"


def get_access_token() -> str:
    if not TOKENS_PATH.exists():
        sys.exit("No tokens.json found. Run `python oauth_login.py` first.")

    tokens = json.loads(TOKENS_PATH.read_text())

    fetched_at = tokens.get("_fetched_at", 0)
    expires_in = tokens.get("expires_in", 0)
    if time.time() < fetched_at + expires_in - 60:
        return tokens["access_token"]

    print("Access token expired, refreshing...")
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        sys.exit(f"Refresh failed: HTTP {resp.status_code}: {resp.text}\nRun oauth_login.py again.")

    new_tokens = resp.json()
    new_tokens["_fetched_at"] = time.time()
    TOKENS_PATH.write_text(json.dumps(new_tokens, indent=2))
    return new_tokens["access_token"]
