#!/usr/bin/env python3
import os
import re
import base64
import pickle
import argparse
from typing import Dict, Tuple, Optional, List
from datetime import timezone
import time
import database

import email.utils as eut
from bs4 import BeautifulSoup, NavigableString, Tag
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# ----------------------------
# Config
# ----------------------------
DEFAULT_TOKEN_FILE = os.getenv("TOKEN_PICKLE", "token.pickle")
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
UNIDENTIFIED_FILE = "unidentified_messages.txt"


# ----------------------------
# Gmail Service
# ----------------------------
class GMailService:
    def __init__(
        self,
        token_file: str = DEFAULT_TOKEN_FILE,
        credentials_path: str = "credentials.json",
    ):
        creds = None
        if os.path.exists(token_file):
            with open(token_file, "rb") as fh:
                creds = pickle.load(fh)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    credentials_path, SCOPES
                )
                creds = flow.run_local_server(port=0)
            with open(token_file, "wb") as fh:
                pickle.dump(creds, fh)
        self.service = build("gmail", "v1", credentials=creds)

    def list_message_ids(
        self, query: str, limit: Optional[int] = None, verbose: bool = False
    ) -> List[str]:
        """
        List message IDs for the given query, printing running totals as we page.
        """
        user_id = "me"
        page_token = None
        ids: List[str] = []
        fetched = 0
        page = 0
        if verbose:
            print(f"Searching: {query}")
        while True:
            page += 1
            resp = (
                self.service.users()
                .messages()
                .list(userId=user_id, q=query, maxResults=100, pageToken=page_token)
                .execute()
            )
            batch = [m["id"] for m in resp.get("messages", [])]
            ids.extend(batch)
            fetched += len(batch)
            if verbose:
                print(f"  page {page}: +{len(batch)} ids (total {fetched})")
            else:
                print(f"Found ids: {fetched}", end="\r", flush=True)
            page_token = resp.get("nextPageToken")
            if limit is not None and len(ids) >= limit:
                ids = ids[:limit]
                break
            if not page_token:
                break
        if not verbose:
            print()  # newline after carriage-return progress
        print(f"Total message ids found: {len(ids)}")
        return ids

    def get_message(self, msg_id: str) -> dict:
        return (
            self.service.users()
            .messages()
            .get(userId="me", id=msg_id, format="full")
            .execute()
        )


# ----------------------------
# Header/date helpers
# ----------------------------
def header_value(headers: List[dict], name: str) -> Optional[str]:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value")
    return None


def parse_date(header_date: Optional[str]) -> Optional[str]:
    if not header_date:
        return None
    try:
        dt = eut.parsedate_to_datetime(header_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return header_date


# ----------------------------
# Extract bodies from payload
# ----------------------------
def walk_parts(parts):
    for part in parts:
        yield part
        if "parts" in part:
            yield from walk_parts(part["parts"])


def extract_bodies(
    payload: dict,
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[int]]:
    """
    Returns (mime_for_parsing, parsed_text_body, raw_html_if_any, signature_html_index)
    - signature_html_index is the character index (in raw HTML) of the first signature occurrence
      ('Pastor Sather' or 'Pastor Al'), or None if not found.
    """
    html_raw = None
    plain_raw = None

    def collect(parts):
        nonlocal html_raw, plain_raw
        for part in parts:
            mime = part.get("mimeType", "")
            body = part.get("body", {}) or {}
            data = body.get("data")
            if data:
                dec = base64.urlsafe_b64decode(data.encode("utf-8")).decode(
                    "utf-8", errors="replace"
                )
                if mime == "text/html" and html_raw is None:
                    html_raw = dec
                elif mime == "text/plain" and plain_raw is None:
                    plain_raw = dec
            if "parts" in part:
                collect(part["parts"])

    if "parts" in payload:
        collect(payload["parts"])
    else:
        mime = payload.get("mimeType", "")
        data = payload.get("body", {}).get("data")
        if data:
            dec = base64.urlsafe_b64decode(data.encode("utf-8")).decode(
                "utf-8", errors="replace"
            )
            if mime == "text/html":
                html_raw = dec
            elif mime == "text/plain":
                plain_raw = dec

    signature_idx = None
    if html_raw is not None:
        # Find signature in plain text of HTML to know it exists (not used directly for slicing here)
        soup = BeautifulSoup(html_raw, "html.parser")
        raw_text = soup.get_text(" ")
        m = re.search(r"\bPastor\s+(?:Sather|Al)\b\.?", raw_text, flags=re.IGNORECASE)
        if m:
            signature_idx = m.start()
        parsed_text = html_to_markdownish_text(html_raw)
        return ("text/html", parsed_text, html_raw, signature_idx)
    elif plain_raw is not None:
        parsed_text = plain_text_cleanup(plain_raw)
        return ("text/plain", parsed_text, None, None)
    else:
        return (None, "", None, None)


# ----------------------------
# HTML -> Markdownish text (bold/italic), table-aware, repair soft wraps
# ----------------------------
BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "canvas",
    "dd",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "noscript",
    "ol",
    "output",
    "p",
    "pre",
    "section",
    "table",
    "tbody",
    "thead",
    "tfoot",
}
ROW_TAGS = {"tr"}
CELL_TAGS = {"td", "th"}


def strip_soft_hyphens(s: str) -> str:
    return s.replace("\u00ad", "")


def html_to_markdownish_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    # Remove script/style
    for t in soup(["script", "style"]):
        t.decompose()

    # Convert <br> to newline
    for br in soup.find_all("br"):
        br.replace_with(NavigableString("\n"))

    # Insert markdown markers, then unwrap tags (no extra spaces)
    for b in soup.find_all(["b", "strong"]):
        b.insert_before(NavigableString("**"))
        b.insert_after(NavigableString("**"))
        b.unwrap()
    for i in soup.find_all(["i", "em"]):
        i.insert_before(NavigableString("_"))
        i.insert_after(NavigableString("_"))
        i.unwrap()

    parts: List[str] = []

    def emit(txt: str):
        if txt:
            parts.append(txt)

    def walk(node: Tag | NavigableString):
        if isinstance(node, NavigableString):
            emit(str(node))
            return

        if isinstance(node, Tag):
            name = (node.name or "").lower()

            # Start-of-block separation
            if name in ROW_TAGS or name in BLOCK_TAGS:
                if parts and not parts[-1].endswith("\n"):
                    emit("\n")

            for child in node.children:
                walk(child)

            # End-of-node handling
            if name in CELL_TAGS:
                # Space between adjacent cells
                next_sib = node.find_next_sibling()
                if next_sib and next_sib.name and next_sib.name.lower() in CELL_TAGS:
                    emit(" ")
            elif name in ROW_TAGS:
                if not (parts and parts[-1].endswith("\n")):
                    emit("\n")
            elif name in BLOCK_TAGS:
                if not (parts and parts[-1].endswith("\n")):
                    emit("\n")

    walk(soup.body or soup)

    text = "".join(parts)

    # Normalize spaces and line breaks
    text = text.replace("\u00a0", " ").replace("\u2007", " ").replace("\u202f", " ")
    text = strip_soft_hyphens(text)
    # Collapse multiple spaces (but don't touch newlines yet)
    text = re.sub(r"[ \t]+", " ", text)
    # Trim spaces around newlines
    text = re.sub(r" *\n *", "\n", text)
    # Collapse 3+ newlines to 2 (paragraph breaks)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Repair formatting runs split across newlines:
    text = re.sub(r"\*\*(\S.*?)\s*\n\*\*", r"**\1** ", text, flags=re.DOTALL)
    text = re.sub(r"_(\S.*?)\s*\n_", r"_\1_ ", text, flags=re.DOTALL)

    # Remove lines that are just markers
    lines = []
    for ln in text.split("\n"):
        stripped = ln.strip()
        if stripped in {"**", "****", "_", "__"}:
            continue
        lines.append(ln)
    text = "\n".join(lines).strip()

    # Ensure space after closing markers when followed by non-space text/punct
    text = re.sub(r"\*\*(\S+)\*\*(\S)", r"**\1** \2", text)
    text = re.sub(r"_(\S+)_(\S)", r"_\1_ \2", text)

    # Insert a newline before an inline signature to create a clean boundary
    text = re.sub(
        r"\s+(\*?\*?_?Pastor\s+(?:Sather|Al)_?\*?\*?)",
        r"\n\1",
        text,
        flags=re.IGNORECASE,
    )

    # Join soft wraps only within paragraphs (between double-newline boundaries)
    def join_soft_wraps(block: str) -> str:
        # Replace single newlines with spaces; keep double newlines intact
        return re.sub(r"(?<!\n)\n(?!\n)", " ", block)

    paragraphs = [join_soft_wraps(p) for p in text.split("\n\n")]
    text = "\n\n".join(paragraphs).strip()

    return text


def plain_text_cleanup(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = strip_soft_hyphens(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ----------------------------
# Section parsing (Verse / Reflection / Prayer)
# ----------------------------
APO = r"[’']?"

# Primary + fallback patterns
VERSE_PATTERNS = [
    rf"(?:Today{APO}s?\s+)?Verse\s*:?",  # handles Today's Verse:, Todays Verse:, Today Verse:, Verse:
]
REFLECTION_PATTERNS = [
    rf"(?:Today{APO}s?\s+)?Reflection\s*:?",  # handles Today's Reflection: and variants
]
SIGNATURE_PATTERNS = [
    r"Pastor\s+Al\b.?",
    r"Pastor\s+Sather\b.?",
]


def compile_heading_regex_line(options: List[str]) -> re.Pattern:
    # line-start or paragraph-start, allow leading markdown markers
    alts = [f"(?:^|\n)\s*(?:\\|__|_)?\s*({opt})\s*" for opt in options]
    return re.compile("|".join(alts), flags=re.IGNORECASE)


def compile_heading_regex_inline(options: List[str]) -> re.Pattern:
    # anywhere in the text, forgiving about surrounding markdown markers/spaces
    alts = [f"(?:\\|_)?\s*({opt})\s*(?:\\|_)?" for opt in options]
    return re.compile("|".join(alts), flags=re.IGNORECASE)


VERSE_RE_LINE = compile_heading_regex_line(VERSE_PATTERNS)
REFLECTION_RE_LINE = compile_heading_regex_line(REFLECTION_PATTERNS)
VERSE_RE_INLINE = compile_heading_regex_inline(VERSE_PATTERNS)
REFLECTION_RE_INLINE = compile_heading_regex_inline(REFLECTION_PATTERNS)
# Inline signature match (not line-anchored) so we can split even if glued to prior text
SIGNATURE_RE_INLINE = re.compile(r"(Pastor\s+(?:Sather|Al))", re.IGNORECASE)


def find_first_after(text: str, regex: re.Pattern, start: int) -> Optional[re.Match]:
    for m in regex.finditer(text):
        if m.start() >= start:
            return m
    return None


def normalize_ws_keep_paras(s: str) -> str:
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def extract_sections(
    markdown_text: str,
) -> Tuple[Optional[str], Optional[str], Optional[str], bool]:
    text = markdown_text.replace("\r\n", "\n").replace("\r", "\n")

    # Include exotic apostrophes and strip zero-width spaces defensively
    text = text.replace("\u200b", "")

    APO = r"[’'′`´]?"
    # Full tokens (match anywhere), tolerant of surrounding markdown markers
    VERSE_TOKEN = re.compile(
        rf"(?:\*\*|__|_)?\s*((?:Today{APO}s?\s+)?Verse)\s*:?\s*(?:\*\*|__|_)?",
        re.IGNORECASE,
    )
    REFLECTION_TOKEN = re.compile(
        rf"(?:\*\*|__|_)?\s*((?:Today{APO}s?\s+)?Reflection)\s*:?\s*(?:\*\*|__|_)?",
        re.IGNORECASE,
    )
    SIGNATURE_INLINE = re.compile(r"(Pastor\s+(?:Sather|Al))", re.IGNORECASE)

    vm = VERSE_TOKEN.search(text)
    if not vm:
        return (None, None, None, False)
    rm = REFLECTION_TOKEN.search(text, vm.end())
    if not rm:
        return (None, None, None, False)

    # Verse ends at the START of the Reflection heading
    verse = text[vm.end() : rm.start()].strip()

    # Reflection begins AFTER the Reflection heading
    reflection_start = rm.end()

    sig = SIGNATURE_INLINE.search(text, reflection_start)
    if sig:
        reflection = text[reflection_start : sig.start()].strip()
        prayer = text[sig.end() :].strip()
    else:
        reflection = text[reflection_start:].strip()
        prayer = None

    # Strip optional 'Prayer:' label if present
    if prayer:
        prayer = re.sub(
            r"^(?:\*\*|__|_)?\s*Prayer\b:?\s*", "", prayer, flags=re.IGNORECASE
        ).strip()

    # Cleanup helpers
    def fix(s: str) -> str:
        # Merge split formatting runs
        s = re.sub(r"\*\*(\S.*?)\s*\n\*\*", r"**\1** ", s, flags=re.DOTALL)
        s = re.sub(r"_(\S.*?)\s*\n_", r"_\1_ ", s, flags=re.DOTALL)

        # Heuristic: join “soft” line breaks inside a paragraph.
        # If there is a single newline not followed by another newline, and the previous
        # character is not strong paragraph punctuation, convert it to a space.
        # Paragraph punctuation to keep: . ! ? : ; ) ] " ’ '
        s = re.sub(r"(?<![\.\!\?\:\;\)\]\"’'])\n(?!\n)", " ", s)

        # Ensure space after markers when jammed
        s = re.sub(r"\*\*(\S+)\*\*(\S)", r"**\1** \2", s)
        s = re.sub(r"_(\S+)_(\S)", r"_\1_ \2", s)

        # Normalize whitespace
        s = re.sub(r"[ \t]+", " ", s)
        s = re.sub(r" *\n *", "\n", s)

        # Collapse 2+ blank lines to a single blank line
        s = re.sub(r"\n{3,}", "\n\n", s)  # first reduce big runs to 2
        s = re.sub(
            r"\n{2,}", "\n\n", s
        )  # enforce exactly one blank line between paragraphs

        return s.strip()

    verse = fix(verse) or None
    reflection = fix(reflection) or None
    if prayer:
        prayer = fix(prayer)
        # Remove leftover outer markers if entire prayer is emphasized
        prayer = prayer.strip("*").strip("_").strip()
        prayer = re.sub(r"\s{2,}", " ", prayer) or None

    return (verse, reflection, prayer, True)


# ----------------------------
# Unidentified logging
# ----------------------------
def load_unidentified(path: str = UNIDENTIFIED_FILE) -> set:
    if not os.path.exists(path):
        return set()
    with open(path, "r", encoding="utf-8") as fh:
        return set(line.strip() for line in fh if line.strip())


def save_unidentified(msg_id: str, path: str = UNIDENTIFIED_FILE) -> None:
    existing = load_unidentified(path)
    if msg_id not in existing:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{msg_id}\n")


# ----------------------------
# Processing one message
# ----------------------------
def process_message_obj(
    msg: dict,
    want_raw_html: bool = False,
    only_raw_html: bool = False,
    debug_text: bool = False,
) -> Dict[str, Optional[str]]:
    try:
        payload = msg.get("payload", {})
        headers = payload.get("headers", [])
        subject = header_value(headers, "Subject") or ""
        date_iso = parse_date(header_value(headers, "Date"))
        mid = msg.get("id", "")

        mime, text_body, raw_html, _sig_idx = extract_bodies(payload)

        if only_raw_html:
            return {
                "message_id": mid,
                "date": date_iso,
                "subject": subject,
                "verse": None,
                "reflection": None,
                "prayer": None,
                "identified": None,
                "raw_html": raw_html,
                "mime": mime,
            }

        verse, reflection, prayer, ok = extract_sections(text_body)
        if not ok:
            save_unidentified(mid)

        result = {
            "message_id": mid,
            "date": date_iso,
            "subject": subject,
            "verse": verse,
            "reflection": reflection,
            "prayer": prayer,
            "identified": ok,
            "mime": mime,
        }
        if want_raw_html:
            result["raw_html"] = raw_html
        if debug_text:
            result["debug_text"] = text_body
        return result
    except Exception as e:
        return {
            "message_id": msg.get("id", "unknown-id"),
            "date": None,
            "subject": None,
            "verse": None,
            "reflection": None,
            "prayer": None,
            "identified": None,
            "mime": None,
            "error": str(e),
        }


# ----------------------------
# CLI
# ----------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Parse Gmail devotional emails into verse, reflection, prayer."
    )
    p.add_argument(
        "--sender",
        default="pastor.sather5@gmail.com",
        help="Sender email to search for.",
    )
    p.add_argument("--subject", help="Subject text to match (quote for exact phrase).")
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Dev limit: number of messages to process (0 = no cap).",
    )
    p.add_argument(
        "--message-id", help="Process a single message by ID (skips search)."
    )
    p.add_argument(
        "--query",
        help="Custom Gmail search query to use instead of --sender/--subject.",
    )
    p.add_argument(
        "--credentials",
        default="credentials.json",
        help="Path to OAuth client credentials.",
    )
    p.add_argument(
        "--token", default=DEFAULT_TOKEN_FILE, help="Path to token.pickle file."
    )
    p.add_argument(
        "--raw-html",
        action="store_true",
        help="Print the raw HTML part of the message if available.",
    )
    p.add_argument(
        "--only-raw-html",
        action="store_true",
        help="Only print raw HTML and skip parsing.",
    )
    p.add_argument(
        "--debug-text",
        action="store_true",
        help="Print normalized text body for debugging heading detection.",
    )
    p.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print per-message progress details.",
    )
    return p


def build_query(args) -> str:
    if args.query:
        return args.query
    clauses = [f"from:({args.sender})"]
    if args.subject:
        if args.subject.startswith('"') and args.subject.endswith('"'):
            clauses.append(f"subject:{args.subject}")
        else:
            clauses.append(f"subject:({args.subject})")
    return " ".join(clauses)


# ----------------------------
# Main
# ----------------------------
def main():
    args = build_arg_parser().parse_args()
    database.init_db()
    service = GMailService(token_file=args.token, credentials_path=args.credentials)

    msgs: List[dict] = []
    if args.message_id:
        msgs.append(service.get_message(args.message_id))
        print("Processing 1 message by ID")
    else:
        query = build_query(args)
        ids = service.list_message_ids(
            query=query, limit=(args.limit or None), verbose=args.verbose
        )
        print("Fetching messages...")
        for i, mid in enumerate(ids, start=1):
            msgs.append(service.get_message(mid))
            # Per-10 fetch logging (optional; keep it quiet unless verbose)
            if args.verbose and i % 10 == 0:
                print(f"  fetched {i}/{len(ids)} messages...")

    total = len(msgs)
    ok_count = 0
    fail_count = 0
    unid_count = 0
    start = time.time()

    for idx, m in enumerate(msgs, start=1):
        try:
            rec = process_message_obj(
                m,
                want_raw_html=args.raw_html,
                only_raw_html=args.only_raw_html,
                debug_text=args.debug_text,
            )
            mid = rec.get("message_id") if isinstance(rec, dict) else m.get("id")

            # Save to DB
            if rec.get("error"):
                fail_count += 1
                database.record_failure(mid or "unknown-id", reason=rec["error"])
                status = "ERROR"
            elif not rec.get("identified"):
                unid_count += 1
                database.record_failure(mid or "unknown-id", reason="unidentified")
                status = "UNID"
            else:
                ok_count += 1
                database.upsert_devotional(
                    rec,
                    sender=args.sender if not args.query else None,
                    save_raw_html=args.raw_html,
                    save_normalized_text=args.debug_text,
                )
                status = "OK"

            if args.verbose:
                print(
                    f"[{idx}/{total}] {status} {mid} | ok={ok_count} unid={unid_count} err={fail_count}"
                )
            else:
                # Compact single-line progress; every 10, print a line
                if idx % 10 == 0 or idx == total:
                    print(
                        f"[{idx}/{total}] ok={ok_count} unid={unid_count} err={fail_count}"
                    )
                else:
                    print(
                        f"[{idx}/{total}] ok={ok_count} unid={unid_count} err={fail_count}",
                        end="\r",
                        flush=True,
                    )

            # Existing detailed printing (kept)
            print("-" * 40)
            print(
                f"Date: {rec.get('date')}, Subject: {rec.get('subject')}, Message ID: {rec.get('message_id')}"
            )
            if args.only_raw_html:
                if rec.get("raw_html") is not None:
                    print("(Raw HTML below)")
                    print(rec["raw_html"])
                else:
                    print("(No HTML part found; message may be plain text.)")
                continue

            if rec.get("error"):
                print(f"(Processing error) {rec['error']}")
                continue

            if args.debug_text and rec.get("debug_text"):
                print("\n--- Debug normalized text ---")
                print(rec["debug_text"])
                print("--- End debug normalized text ---\n")

            print(f"Identified: {rec.get('identified')}")
            if args.raw_html:
                print()
                print("Raw HTML:")
                if rec.get("raw_html") is not None:
                    print(rec["raw_html"])
                else:
                    print("(No HTML part found; message may be plain text.)")
                print()

            # print("Verse:")
            # print(rec.get("verse") or "")
            # print()
            # print("Reflection:")
            # print(rec.get("reflection") or "")
            # print()
            # print("Prayer:")
            # print(rec.get("prayer") or "")

        except Exception as e:
            fail_count += 1
            mid = m.get("id", "unknown-id")
            database.record_failure(mid, reason=str(e))
            if args.verbose:
                print(f"[{idx}/{total}] ERROR {mid}: {e}")
            else:
                if idx % 10 == 0 or idx == total:
                    print(
                        f"[{idx}/{total}] ok={ok_count} unid={unid_count} err={fail_count}"
                    )
                else:
                    print(
                        f"[{idx}/{total}] ok={ok_count} unid={unid_count} err={fail_count}",
                        end="\r",
                        flush=True,
                    )
            print("-" * 40)
            print(f"(Error processing message {mid}) {e}")

    if not args.verbose:
        print()  # newline after last carriage-return line
    elapsed = time.time() - start
    print(
        f"Done. Processed {total}: OK={ok_count}, UNIDENTIFIED={unid_count}, ERRORS={fail_count} in {elapsed:.1f}s"
    )


if __name__ == "__main__":
    main()
