#!/usr/bin/env python3
"""
generate_reading.py

Generate a compact Bible verse recommendation ("additional reading") for devotionals
that have an empty/NULL reading column. Uses both the verse and the reflection to pick
a strongly related, concise passage. Appends " AI" to the end of the verse reference
(e.g., "Isaiah 40:31 AI"). Interactive confirmation flow included.

Behavior:
-    Select rows from 'devotionals' where reading IS NULL or TRIM(reading) = ''.
-    For each row, build a prompt using the verse and reflection, and ask Claude to return:
        • Exactly one Bible verse reference (book chap:verses), as compact as possible
        • No quotes or extra text
        • Must append " AI" to the end
-    Show a preview: reflection (80 cols), current reading, and AI suggestion.
-    Options to apply: [y]es, [n]o, [a]ll, [q]uit
-    Supports --limit, --id, --id-column
-    Supports --dry-run and --non-interactive

Environment:
-    DEVOTIONAL_DB: path to SQLite database (or use --db)
-    CLAUDE_API_KEY: Anthropic API key
-    Optional CLAUDE_MODEL: override default model

Install:
    pip install anthropic
"""

import argparse
import os
import sys
import textwrap
import time
from typing import Any, Dict, List, Optional

# Local database utilities (provided by user)
try:
    import database
except Exception as e:
    print(f'ERROR: Could not import database.py: {e}', file=sys.stderr)
    sys.exit(1)

try:
    import anthropic
except ImportError:
    anthropic = None


# --------------------------
# Prompt for verse selection
# --------------------------

BASE_READING_PROMPT = """You are a careful, concise Bible-reading selector.

Goal:
-    Suggest exactly ONE Bible passage reference that is the most compact and thematically strong
    follow-up reading for the provided devotional content.
-    It must be Scripture only (book, chapter:verse[s]) with NO quotes or commentary.
-    Keep it as short/compact as possible (prefer 1–3 verses, or a single verse if it stands well).
-    Tailor the selection to the provided verse AND reflection themes.
-    Append " AI" at the end of the reference (exactly, with a preceding space).

Output format (strict):
-    Example: Isaiah 40:31 AI
-    Do not include any other text, punctuation, or explanation.

Given:
-    Main verse: {main_verse}
-    Reflection: {reflection}
"""


def build_prompt(main_verse: str, reflection: str) -> str:
    return BASE_READING_PROMPT.format(
        main_verse=(main_verse or '').strip(),
        reflection=(reflection or '').strip(),
    )


def postprocess_ai_output(s: str) -> str:
    # Normalize whitespace, ensure it ends with " AI"
    t = ' '.join((s or '').strip().split())
    if not t:
        return t
    # Remove trailing punctuation just in case
    while t and t[-1] in '.;:,!?)':
        t = t[:-1].rstrip()
    if not t.endswith(' AI'):
        # Avoid duplicating AI if already present in another casing/format
        if t.lower().endswith(' ai'):
            t = t[:-3] + ' AI'
        else:
            t = f'{t} AI'
    return t


def call_claude(prompt: str, model: str, temperature: float, max_tokens: int) -> str:
    if anthropic is None:
        raise RuntimeError('anthropic package not installed. Run: pip install anthropic')

    api_key = os.getenv('CLAUDE_API_KEY')
    if not api_key:
        raise RuntimeError('CLAUDE_API_KEY environment variable not set')

    client = anthropic.Anthropic(api_key=api_key)

    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{'role': 'user', 'content': prompt}],
    )

    content = ''
    try:
        if resp and hasattr(resp, 'content') and resp.content:
            for block in resp.content:
                if hasattr(block, 'text') and block.text:
                    content = block.text.strip()
                    if content:
                        break
    except Exception:
        content = str(resp)

    if not content:
        raise RuntimeError('Empty response from Claude API')

    return postprocess_ai_output(content)


# --------------------------
# DB helpers
# --------------------------


def override_db_path(db_path: Optional[str]) -> None:
    if db_path:
        database.DB_PATH = db_path
        os.environ['DEVOTIONAL_DB'] = db_path


def select_rows_missing_reading(
    conn,
    table: str,
    id_col: str,
    limit: Optional[int],
) -> List[Dict[str, Any]]:
    limit_clause = ' LIMIT ? ' if limit else ''
    sql = f"""
        SELECT {id_col} AS _id,
               verse AS _verse,
               reflection AS _reflection,
               reading AS _reading
        FROM {table}
        WHERE reading IS NULL
           OR TRIM(reading) = ''
        ORDER BY {id_col}
        {limit_clause}
    """
    cur = conn.execute(sql, (limit,) if limit else ())
    return [dict(r) for r in cur.fetchall()]


def select_row_by_id(
    conn,
    table: str,
    id_col: str,
    id_value: str,
) -> Optional[Dict[str, Any]]:
    sql = f"""
        SELECT {id_col} AS _id,
               verse AS _verse,
               reflection AS _reflection,
               reading AS _reading
        FROM {table}
        WHERE {id_col} = ?
    """
    row = conn.execute(sql, (id_value,)).fetchone()
    return dict(row) if row else None


def update_reading(
    conn,
    table: str,
    id_col: str,
    row_id: str,
    new_value: str,
) -> None:
    sql = f"""
        UPDATE {table}
        SET reading = ?, updated_at = datetime('now')
        WHERE {id_col} = ?
    """
    conn.execute(sql, (new_value, row_id))


# --------------------------
# UI helpers
# --------------------------


def print_row_preview(
    idx: int,
    row_id: str,
    verse: str,
    reflection: str,
    current_reading: Optional[str],
    ai_suggestion: str,
):
    print('\n' + '=' * 72)
    print(f'Row #{idx}  ID: {row_id}')
    print('- Verse:')
    print(textwrap.indent(textwrap.fill((verse or '').strip(), width=80), '  '))
    print('- Reflection:')
    if reflection and reflection.strip():
        print(textwrap.indent(textwrap.fill(reflection.strip(), width=80), '  '))
    else:
        print('  <empty>')
    print('- Current reading:')
    if current_reading and current_reading.strip():
        print(textwrap.indent(textwrap.fill(current_reading.strip(), width=80), '  '))
    else:
        print('  <empty>')
    print('- AI suggestion:')
    print(textwrap.indent(textwrap.fill(ai_suggestion.strip(), width=80), '  '))
    print('- Choice: [y]es apply, [n]o skip, [a]ll apply to all remaining, [q]uit')


def ask_choice() -> str:
    while True:
        choice = input('Apply? [y/n/a/q]: ').strip().lower()
        if choice in ('y', 'n', 'a', 'q'):
            return choice
        print('Please enter one of: y, n, a, q')


# --------------------------
# Main
# --------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Generate compact Bible reading recommendations (appends ' AI') for devotionals with empty 'reading'."
    )
    parser.add_argument('--table', default='devotionals', help='Table name (default: devotionals)')
    parser.add_argument(
        '--id',
        dest='id_value',
        default=None,
        help='Specific primary key value to process',
    )
    parser.add_argument(
        '--id-column',
        default='message_id',
        help='Primary key column name (default: message_id)',
    )
    parser.add_argument(
        '--db',
        dest='db_path',
        default=None,
        help='Path to SQLite DB (overrides DEVOTIONAL_DB)',
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of rows to process (ignored with --id)',
    )
    parser.add_argument('--dry-run', action='store_true', help='Preview only, no writes')
    parser.add_argument('--non-interactive', action='store_true', help='Apply without prompts')
    parser.add_argument(
        '--model',
        default=os.getenv('CLAUDE_MODEL', 'claude-3-5-sonnet-20240620'),
        help='Anthropic model name',
    )
    parser.add_argument(
        '--temperature',
        type=float,
        default=0.2,
        help='Lower temperature for precision (default: 0.2)',
    )
    parser.add_argument(
        '--max-tokens',
        type=int,
        default=40,
        help='Small cap since output is short (default: 40)',
    )

    args = parser.parse_args()

    override_db_path(args.db_path)

    # Fetch rows
    with database.get_conn(database.DB_PATH) as conn:
        if args.id_value:
            row = select_row_by_id(conn, args.table, args.id_column, args.id_value)
            if not row:
                print(f'No row found with {args.id_column} = {args.id_value}')
                return
            rows = [row]
        else:
            rows = select_rows_missing_reading(conn, args.table, args.id_column, args.limit)

        if not rows:
            print('No rows found with missing/empty reading.')
            return

        apply_all = False
        processed = 0
        updated = 0

        for idx, row in enumerate(rows, start=1):
            row_id = row['_id']
            verse = (row.get('_verse') or '').strip()
            reflection = (row.get('_reflection') or '').strip()
            current_reading = (row.get('_reading') or '').strip()

            # If this row already has reading text and user targeted via --id, still proceed
            if not args.id_value and current_reading:
                # Safety: skip if not targeted specifically
                continue

            prompt = build_prompt(main_verse=verse, reflection=reflection)

            # Call Claude with retry
            suggestion = None
            attempt = 0
            backoff = 5
            while True:
                try:
                    suggestion = call_claude(
                        prompt=prompt,
                        model=args.model,
                        temperature=args.temperature,
                        max_tokens=args.max_tokens,
                    )
                    break
                except Exception as e:
                    attempt += 1
                    if attempt >= 3:
                        print(f'ERROR: AI generation failed for ID={row_id}: {e}')
                        break
                    print(f'Warn: AI error for ID={row_id}: {e} — retrying in {backoff}s...')
                    time.sleep(backoff)
                    backoff *= 2

            if not suggestion:
                processed += 1
                continue

            # Non-interactive path
            if args.non_interactive:
                if args.dry_run:
                    print_row_preview(idx, row_id, verse, reflection, current_reading, suggestion)
                    processed += 1
                    continue
                update_reading(conn, args.table, args.id_column, row_id, suggestion)
                updated += 1
                processed += 1
                continue

            # Interactive preview
            print_row_preview(idx, row_id, verse, reflection, current_reading, suggestion)

            if apply_all:
                choice = 'y'
            else:
                choice = ask_choice()

            if choice == 'q':
                print('Quitting...')
                break
            elif choice == 'n':
                processed += 1
                continue
            elif choice == 'a':
                apply_all = True
                choice = 'y'

            if choice == 'y':
                if args.dry_run:
                    print(f'[DRY-RUN] Would update ID={row_id}')
                else:
                    update_reading(conn, args.table, args.id_column, row_id, suggestion)
                    updated += 1
                processed += 1

        print('\nSummary:')
        print(f'- Processed: {processed}')
        print(f'- Updated:   {updated}')
        if args.dry_run:
            print('- Mode:      DRY RUN (no changes written)')


if __name__ == '__main__':
    main()
