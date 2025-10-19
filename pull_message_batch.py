#!/usr/bin/env python3
import argparse
import base64
import os
import pickle
import re
from pathlib import Path
from typing import Iterable

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
DEFAULT_TOKEN_FILE = os.getenv("TOKEN_PICKLE", "token.pickle")


def get_service(token_file: str, credentials_path: str):
    creds = None
    if os.path.exists(token_file):
        with open(token_file, "rb") as fh:
            creds = pickle.load(fh)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "wb") as fh:
            pickle.dump(creds, fh)
    return build("gmail", "v1", credentials=creds)


def _decode_part_data(data: str) -> str:
    if not data:
        return ""
    return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", "replace")


def _iter_parts(payload):
    if not payload:
        return
    if "parts" in payload:
        for p in payload["parts"]:
            yield from _iter_parts(p)
    else:
        yield payload


def _cleanup_text(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\u2007", " ").replace("\u202f", " ")
    text = re.sub(r"\u00ad", "", text)  # soft hyphen
    text = re.sub(r"[ \t]+", " ", text)  # collapse spaces/tabs
    text = re.sub(r" *\n *", "\n", text)  # trim spaces around newlines
    text = re.sub(r"\n{3,}", "\n\n", text)  # collapse 3+ newlines to 2
    return text.strip()


def get_headers(msg):
    headers = {}
    for h in (msg.get("payload", {}) or {}).get("headers", []) or []:
        name = (h.get("name") or "").lower()
        headers[name] = h.get("value") or ""
    return {
        "subject": headers.get("subject", ""),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "date": headers.get("date", ""),
        "message-id": headers.get("message-id", ""),
    }


def get_plain_text(msg) -> str:
    payload = msg.get("payload", {}) or {}

    # Prefer text/plain part
    for part in _iter_parts(payload):
        mime = (part.get("mimeType") or "").lower()
        if mime == "text/plain":
            data = (part.get("body") or {}).get("data")
            if data:
                return _cleanup_text(_decode_part_data(data))

    # Fallback to top-level single-part body
    data = (payload.get("body") or {}).get("data")
    if data:
        return _cleanup_text(_decode_part_data(data))

    return ""


def render_message_text(message_id: str, msg: dict) -> str:
    hdr = get_headers(msg)
    body = get_plain_text(msg)
    sep = "=" * 67
    lines = [
        f"message_id: {message_id}",
        f"subject   : {hdr['subject']}",
        f"from      : {hdr['from']}",
        f"to        : {hdr['to']}",
        f"date      : {hdr['date']}",
        sep,
        "Body (clean, unformatted):",
        sep,
        body if body else "[No plain-text body found]",
        "",
    ]
    return "\n".join(lines)


def read_ids(path: Path) -> Iterable[str]:
    with path.open("r", encoding="utf-8") as fh:
        for ln in fh:
            mid = ln.strip()
            if mid:
                yield mid


def main():
    ap = argparse.ArgumentParser(
        description="Download messages for IDs in a file and save to orig/<id>.txt"
    )
    ap.add_argument(
        "--ids-file",
        default="message_ids.txt",
        help="Path to file with one message_id per line",
    )
    ap.add_argument("--out-dir", default="orig", help="Output directory")
    ap.add_argument("--credentials", default="credentials.json")
    ap.add_argument("--token", default=DEFAULT_TOKEN_FILE)
    ap.add_argument(
        "--limit", type=int, default=0, help="Max messages to process (0 = all)"
    )
    args = ap.parse_args()

    ids_path = Path(args.ids_file)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    svc = get_service(args.token, args.credentials)

    processed = 0
    for mid in read_ids(ids_path):
        if args.limit and processed >= args.limit:
            break
        try:
            msg = (
                svc.users().messages().get(userId="me", id=mid, format="full").execute()
            )
            content = render_message_text(mid, msg)
            (out_dir / f"{mid}.txt").write_text(content, encoding="utf-8")
            processed += 1
            if processed % 25 == 0:
                print(f"Saved {processed} messages...", flush=True)
        except Exception as e:
            print(f"ERROR {mid}: {e}", flush=True)

    print(f"Done. Saved {processed} messages to {out_dir}/")


if __name__ == "__main__":
    main()
