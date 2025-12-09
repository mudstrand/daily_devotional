#!/usr/bin/env python3
import os
import re
import base64
import pickle
import argparse
from typing import Optional, List, Tuple
from datetime import timezone

import email.utils as eut
from bs4 import BeautifulSoup, NavigableString, Tag
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

import database

# Config
DEFAULT_TOKEN_FILE = os.getenv('TOKEN_PICKLE', 'token.pickle')
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
UNIDENTIFIED_TXT = 'unidentified_messages.txt'
FIXED_TXT = 'fixed_messages.txt'
OUT_DIR = 'unidentified'

# Keep raw_body as original HTML if present; otherwise it will be plain text body_text
RAW_BODY_AS_TEXT = False  # set True to store body_text in raw_body instead of HTML


# ---------------- Gmail service ----------------
class GMailService:
    def __init__(
        self,
        token_file: str = DEFAULT_TOKEN_FILE,
        credentials_path: str = 'credentials.json',
    ):
        creds = None
        if os.path.exists(token_file):
            with open(token_file, 'rb') as fh:
                creds = pickle.load(fh)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_file, 'wb') as fh:
                pickle.dump(creds, fh)
        self.service = build('gmail', 'v1', credentials=creds)

    def get_message(self, msg_id: str) -> dict:
        return self.service.users().messages().get(userId='me', id=msg_id, format='full').execute()


# ---------------- Helpers ----------------
def header_value(headers: List[dict], name: str) -> Optional[str]:
    for h in headers:
        if h.get('name', '').lower() == name.lower():
            return h.get('value')
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


def walk_parts(parts):
    for part in parts:
        yield part
        if 'parts' in part:
            yield from walk_parts(part['parts'])


def extract_bodies(payload: dict) -> Tuple[Optional[str], str, Optional[str]]:
    """
    Returns (chosen_mime, body_text_plain, raw_html_if_any)
    - body_text_plain: plain text (HTML stripped) or cleaned text/plain
    - raw_html_if_any: original HTML if the message had it; otherwise None
    """
    html_raw, plain_raw = None, None

    def collect(parts):
        nonlocal html_raw, plain_raw
        for part in parts:
            mime = part.get('mimeType', '')
            body = part.get('body', {}) or {}
            data = body.get('data')
            if data:
                dec = base64.urlsafe_b64decode(data.encode('utf-8')).decode('utf-8', errors='replace')
                if mime == 'text/html' and html_raw is None:
                    html_raw = dec
                elif mime == 'text/plain' and plain_raw is None:
                    plain_raw = dec
            if 'parts' in part:
                collect(part['parts'])

    if 'parts' in payload:
        collect(payload['parts'])
    else:
        mime = payload.get('mimeType', '')
        data = payload.get('body', {}).get('data')
        if data:
            dec = base64.urlsafe_b64decode(data.encode('utf-8')).decode('utf-8', errors='replace')
            if mime == 'text/html':
                html_raw = dec
            elif mime == 'text/plain':
                plain_raw = dec

    if html_raw is not None:
        return ('text/html', html_to_text(html_raw), html_raw)
    elif plain_raw is not None:
        return ('text/plain', plain_text_cleanup(plain_raw), None)
    else:
        return (None, '', None)


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, 'html.parser')
    for t in soup(['script', 'style']):
        t.decompose()
    for br in soup.find_all('br'):
        br.replace_with(NavigableString('\n'))

    parts = []

    def emit(x):
        if x:
            parts.append(x)

    BLOCK_TAGS = {
        'p',
        'div',
        'section',
        'article',
        'blockquote',
        'ul',
        'ol',
        'li',
        'table',
        'thead',
        'tbody',
        'tfoot',
        'tr',
        'td',
        'th',
        'h1',
        'h2',
        'h3',
        'h4',
        'h5',
        'h6',
    }

    def walk(node):
        if isinstance(node, NavigableString):
            emit(str(node))
            return
        if isinstance(node, Tag):
            name = (node.name or '').lower()
            if name in BLOCK_TAGS and parts and not parts[-1].endswith('\n'):
                emit('\n')
            for c in node.children:
                walk(c)
            if name in BLOCK_TAGS and (not parts or not parts[-1].endswith('\n')):
                emit('\n')

    walk(soup.body or soup)
    text = ''.join(parts)
    text = text.replace('\u00a0', ' ').replace('\u2007', ' ').replace('\u202f', ' ')
    text = re.sub(r'\u00ad', '', text)  # soft hyphen
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r' *\n *', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def plain_text_cleanup(text: str) -> str:
    text = text.replace('\u00a0', ' ').replace('\u2007', ' ').replace('\u202f', ' ')
    text = re.sub(r'\u00ad', '', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r' *\n *', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# Best-effort section splitter
APO = r"[’'′`´]?"
VERSE_RE = re.compile(rf'(?:^|\n)\s*(?:Today{APO}s?\s+)?Verse\s*:?\s*', re.IGNORECASE)
REFL_RE = re.compile(rf'(?:^|\n)\s*(?:Today{APO}s?\s+)?Reflection\s*:?\s*', re.IGNORECASE)
SIG_RE = re.compile(r'(?:^|\n)\s*Pastor\s+(?:Sather|Al)\b\.?', re.IGNORECASE)


def best_effort_split(text: str) -> Tuple[str, str, str]:
    verse, reflection, prayer = '', '', ''
    m_v = VERSE_RE.search(text)
    m_r = REFL_RE.search(text, m_v.end() if m_v else 0)
    if not (m_v and m_r):
        return ('', '', '')
    verse = text[m_v.end() : m_r.start()].strip()
    rest = text[m_r.end() :]
    m_sig = SIG_RE.search(rest)
    if m_sig:
        reflection = rest[: m_sig.start()].strip()
        prayer = rest[m_sig.end() :].strip()
    else:
        reflection = rest.strip()
        prayer = ''
    return (verse, reflection, prayer)


# ---------------- Output writer ----------------
TEMPLATE = """message-id: {message_id}
===================================================================
date_utc:

{date_utc}
===================================================================
subject:

{subject}
===================================================================
verse:

{verse}
===================================================================
reflection:

{reflection}
===================================================================
prayer:

{prayer}
===================================================================
body_text:

{body_text}
===================================================================
raw_body:

{raw_body}
"""


def write_unidentified_file(
    path: str,
    *,
    message_id: str,
    date_utc: str,
    subject: str,
    verse: str,
    reflection: str,
    prayer: str,
    body_text: str,
    raw_body: str,
) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(
            TEMPLATE.format(
                message_id=message_id or '',
                date_utc=date_utc or '',
                subject=(subject or '').strip(),
                verse=(verse or '').strip(),
                reflection=(reflection or '').strip(),
                prayer=(prayer or '').strip(),
                body_text=(body_text or '').strip(),
                raw_body=raw_body or '',
            )
        )


def clean_subject_prefix(subj: str) -> str:
    if not subj:
        return subj
    return re.sub(r'^\s*Subject\s*:\s*', '', subj, flags=re.IGNORECASE).strip()


# ---------------- CLI ----------------
def build_args():
    p = argparse.ArgumentParser(description='Download unidentified messages to editable files (plain body + raw).')
    p.add_argument('--limit', type=int, default=0, help='Max number to dump (0 = all).')
    p.add_argument(
        '--from-file',
        default=UNIDENTIFIED_TXT,
        help='Path to unidentified_messages.txt',
    )
    p.add_argument('--fixed-file', default=FIXED_TXT, help='Path to fixed_messages.txt')
    p.add_argument('--out-dir', default=OUT_DIR, help='Directory to write unidentified files')
    p.add_argument('--credentials', default='credentials.json')
    p.add_argument('--token', default=DEFAULT_TOKEN_FILE)
    return p.parse_args()


def main():
    args = build_args()
    database.init_db()
    svc = GMailService(token_file=args.token, credentials_path=args.credentials)

    # Read ids from unidentified_messages.txt
    if not os.path.exists(args.from_file):
        print(f'Missing {args.from_file}. Ensure unidentified_messages.txt exists.')
        return
    with open(args.from_file, 'r', encoding='utf-8') as fh:
        ids = [ln.strip() for ln in fh if ln.strip()]

    # Exclude IDs that are already fixed (in fixed_messages.txt)
    fixed_ids = set()
    if os.path.exists(args.fixed_file):
        with open(args.fixed_file, 'r', encoding='utf-8') as fh:
            fixed_ids = {ln.strip() for ln in fh if ln.strip()}
    remaining = [mid for mid in ids if mid not in fixed_ids]

    # Exclude IDs that already have a file in unidentified/ (not fixed yet)
    os.makedirs(args.out_dir, exist_ok=True)
    remaining = [mid for mid in remaining if not os.path.exists(os.path.join(args.out_dir, f'{mid}.txt'))]

    if args.limit and len(remaining) > args.limit:
        remaining = remaining[: args.limit]

    print(f'Dumping {len(remaining)} unidentified messages to {args.out_dir}/ (skipping fixed + already downloaded)')

    dumped = 0
    for idx, mid in enumerate(remaining, start=1):
        out_path = os.path.join(args.out_dir, f'{mid}.txt')
        try:
            msg = svc.get_message(mid)
            payload = msg.get('payload', {})
            headers = payload.get('headers', [])
            subject_raw = header_value(headers, 'Subject') or ''
            subject = clean_subject_prefix(subject_raw)
            date_iso = parse_date(header_value(headers, 'Date')) or ''

            chosen_mime, body_text_plain, raw_html = extract_bodies(payload)
            verse, reflection, prayer = best_effort_split(body_text_plain)

            raw_body = body_text_plain if (RAW_BODY_AS_TEXT or raw_html is None) else raw_html

            write_unidentified_file(
                out_path,
                message_id=mid,
                date_utc=date_iso,
                subject=subject,
                verse=verse,
                reflection=reflection,
                prayer=prayer,
                body_text=body_text_plain,
                raw_body=raw_body,
            )
            dumped += 1
            if idx % 10 == 0:
                print(f'  processed {idx} (new files {dumped})')
        except Exception as e:
            print(f'ERROR {mid}: {e}')

    print(f'Done. New files written: {dumped}')


if __name__ == '__main__':
    main()
