#!/usr/bin/env python3
import os
import pickle
from typing import List, Optional

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
TOKEN_FILE = os.getenv("TOKEN_PICKLE", "token.pickle")
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS", "credentials.json")
OUTPUT_FILE = "complete_pastor_al.ids"


def gmail_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as fh:
            creds = pickle.load(fh)
    if not creds or not creds.valid:
        if creds and creds.expired and getattr(creds, "refresh_token", None):
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as fh:
            pickle.dump(creds, fh)
    return build("gmail", "v1", credentials=creds)


def fetch_message_ids(query: str) -> List[str]:
    svc = gmail_service()
    user_id = "me"
    page_token: Optional[str] = None
    ids: List[str] = []
    page = 0

    while True:
        page += 1
        resp = (
            svc.users()
            .messages()
            .list(userId=user_id, q=query, maxResults=500, pageToken=page_token)
            .execute()
        )
        batch = [m["id"] for m in resp.get("messages", []) or []]
        ids.extend(batch)
        print(f"Page {page}: +{len(batch)} (total {len(ids)})")
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return ids


if __name__ == "__main__":
    # Query by display name in the From header
    q = 'from:"Pastor Sather"'
    # Example alternative:
    # q = 'from:"Pastor Al" OR from:pastor.al@example.com'

    ids = fetch_message_ids(q)
    print(f"Total matching messages: {len(ids)}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for mid in ids:
            f.write(f"{mid}\n")

    print(f"Wrote {len(ids)} IDs to {OUTPUT_FILE}")
