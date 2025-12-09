#!/usr/bin/env python3
"""
generate_ai_content.py

Populate or replace a target column in the 'devotionals' SQLite table using Claude AI,
leveraging your existing database.py. Adds:
-   Reflection preview (80 cols) between Row header and Target.
-   Repetition avoidance: dynamically asks Claude to avoid recently used prayer openings.

Behavior:
-   If --id is NOT provided: process rows where the target column is NULL or empty.
-   If --id IS provided: show current value (if any) and AI suggestion, and let you choose
   whether to replace.

Interactive flow like markdown_clean.py:
-   Choices: [y]es apply, [n]o skip, [a]ll apply to all remaining, [q]uit
-   --non-interactive applies changes automatically
-   --dry-run previews without writing

Options:
    --column <name>                 Target column to fill/replace (required)
    --reflections-column <name>     Source column for AI prompt (default: reflection)
    --limit N                       Max rows to process (ignored with --id)
    --id <value>                    Specific primary key value to process
    --id-column <name>              Name of PK column (default: message_id)
    --db <path>                     Override DEVOTIONAL_DB (falls back to env)
    --dry-run                       Preview only, no writes
    --non-interactive               Apply without prompts
    --model <anthropic_model>       Override model (default: claude-3-5-sonnet-20240620)
    --temperature FLOAT             Creativity (default: 0.4)
    --max-tokens INT                Response length cap (default: 200)
    --avoid-memory INT              How many recent openings to avoid (default: 3)

Requirements:
-   database.py present and importable (uses get_conn)
-   Environment:
    DEVOTIONAL_DB points to your SQLite file (or pass --db)
    CLAUDE_API_KEY for Anthropic

Install:
    pip install anthropic
"""

import os
import sys
import time
import argparse
import textwrap
import re
from collections import deque
from typing import Optional, List, Dict, Any

# Use the existing DB utilities
try:
    import database  # your provided database.py
except Exception as e:
    print(f'ERROR: Could not import database.py: {e}', file=sys.stderr)
    sys.exit(1)

try:
    import anthropic
except ImportError:
    anthropic = None


# --------------------------
# Prompt and AI integration
# --------------------------

BASE_PRAYER_PROMPT = """You are a careful, concise prayer writer.

Goal:
-    Write a prayer of 1–2 sentences that flows naturally from the provided reflection text.
-    The prayer must end with the exact marker: (AI)

Opening:
-    Begin with a single, thematically appropriate address to God chosen from this list (do not default to “Lord,”):
  Almighty God; Gracious God; Loving God; Merciful God; Faithful God; Holy God; Eternal God;
  Lord of Mercy; Lord of Life; Heavenly Father; Our Father; Dear Lord; Blessed Lord; Lord Jesus;
  Jesus, our Savior

Thematic selection rules:
-    Choose the opening that best matches the dominant theme(s) detected in the reflection:
  • Forgiveness/compassion/mercy → “Merciful God” or “Lord of Mercy”
  • Love/comfort/pastoral care → “Loving God,” “Heavenly Father,” or “Our Father”
  • Faithfulness/endurance/trust → “Faithful God”
  • Holiness/reverence/repentance → “Holy God”
  • Creation/sovereignty/eternity → “Almighty God,” “Eternal God,” or “Lord of Life”
  • Guidance/wisdom/discernment → “Gracious God” or “Holy God”
  • Christ-centered redemption/following Jesus → “Lord Jesus” or “Jesus, our Savior”
  • Thanksgiving/blessing/praise → “Blessed Lord”
-    Vary openings across generations to avoid repetition. Do not overuse the same opener.

Style:
-    Keep it sincere, clear, and widely accessible.
-    Paraphrase; do not quote long passages.
-    Avoid personal identifiers and denominational jargon unless clearly warranted by the text.

Output:
-    Return only the prayer (no labels), 1–2 sentences total.
-    End with (AI)

Reflection:
"""

STRICT_AVOID_SECTION = """Constraint:
-    Do not use any of these openings in this generation: {items}
"""


def build_prompt(
    reflection_text: str,
    avoid_openers: Optional[List[str]] = None,
) -> str:
    """
    Build the Claude prompt, optionally adding a "do not use" constraint with recently used openings.
    """
    reflection_text = (reflection_text or '').strip()

    parts = [BASE_PRAYER_PROMPT.strip()]
    if avoid_openers:
        # Deduplicate while preserving order
        seen = set()
        unique = [x for x in avoid_openers if not (x in seen or seen.add(x))]
        if unique:
            parts.append(STRICT_AVOID_SECTION.format(items='; '.join(unique)).strip())
    parts.append('')  # blank line
    parts.append(reflection_text)
    parts.append('')  # trailing newline
    return '\n'.join(parts)


def postprocess_ai_output(text_out: str) -> str:
    # Normalize whitespace and enforce ending with (AI)
    t = ' '.join((text_out or '').strip().split())
    if not t:
        return t
    # Soft length guard
    if len(t) > 400:
        t = t[:400].rstrip()
    if not t.endswith('(AI)'):
        if t.endswith('.') or t.endswith('!') or t.endswith('?'):
            t = f'{t} (AI)'
        else:
            t = f'{t} (AI)'
    return t


def call_claude(
    prompt: str,
    model: str = 'claude-3-5-sonnet-20240620',
    temperature: float = 0.4,
    max_tokens: int = 200,
) -> str:
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
# DB helpers (using database.py)
# --------------------------


def override_db_path(db_path: Optional[str]) -> None:
    """
    Optionally override the DB path from CLI. This updates the module-level DB_PATH
    used by database.get_conn().
    """
    if db_path:
        database.DB_PATH = db_path
        os.environ['DEVOTIONAL_DB'] = db_path


def select_rows_for_column_empty(
    conn,
    table: str,
    id_col: str,
    target_col: str,
    reflections_col: str,
    limit: Optional[int],
) -> List[Dict[str, Any]]:
    """
    Select rows where target column is NULL or empty (after trim).
    Returns list of dicts with keys: _id, _target, _reflections
    """
    limit_clause = ' LIMIT ? ' if limit else ''
    sql = f"""
        SELECT {id_col} AS _id,
               {target_col} AS _target,
               {reflections_col} AS _reflections
        FROM {table}
        WHERE {target_col} IS NULL
           OR TRIM({target_col}) = ''
        ORDER BY {id_col}
        {limit_clause}
    """
    cur = conn.execute(sql, (limit,) if limit else ())
    rows = [dict(r) for r in cur.fetchall()]
    return rows


def select_row_by_id(
    conn,
    table: str,
    id_col: str,
    target_col: str,
    reflections_col: str,
    id_value: str,
) -> Optional[Dict[str, Any]]:
    sql = f"""
        SELECT {id_col} AS _id,
               {target_col} AS _target,
               {reflections_col} AS _reflections
        FROM {table}
        WHERE {id_col} = ?
        """
    row = conn.execute(sql, (id_value,)).fetchone()
    return dict(row) if row else None


def update_target_column(
    conn,
    table: str,
    id_col: str,
    row_id: str,
    target_col: str,
    new_value: str,
) -> None:
    sql = f"""
        UPDATE {table}
        SET {target_col} = ?, updated_at = datetime('now')
        WHERE {id_col} = ?
    """
    conn.execute(sql, (new_value, row_id))


# --------------------------
# Opening extraction for repetition avoidance
# --------------------------

# Captures an initial address like "Almighty God," or "Jesus, our Savior,"
OPENING_PATTERN = re.compile(r"^\s*([A-Z][A-Za-z0-9 ,’'\\-]+?),\s")


def extract_opening(prayer_text: str) -> Optional[str]:
    """
    Extract the initial address/opening from the generated prayer.
    Returns e.g., 'Almighty God' or 'Jesus, our Savior', otherwise None.
    """
    if not prayer_text:
        return None
    m = OPENING_PATTERN.match(prayer_text)
    return m.group(1).strip() if m else None


# --------------------------
# Interactive UI
# --------------------------


def print_row_preview(
    row_idx: int,
    row_id: str,
    target_col: str,
    current_value: Optional[str],
    ai_value: str,
    reflection_value: Optional[str],
) -> None:
    print('\n' + '=' * 72)
    print(f'Row #{row_idx}  ID: {row_id}')
    print(f'Target column: {target_col}')
    print('- Reflection:')
    if reflection_value and reflection_value.strip():
        print(textwrap.indent(textwrap.fill(reflection_value.strip(), width=80), '  '))
    else:
        print('  <empty>')
    print('- Current value:')
    if current_value and current_value.strip():
        print(textwrap.indent(textwrap.fill(current_value.strip(), width=80), '  '))
    else:
        print('  <empty>')
    print('- AI suggestion:')
    print(textwrap.indent(textwrap.fill(ai_value, width=80), '  '))
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
    parser = argparse.ArgumentParser(description='Generate AI content for devotionals using database.py (SQLite).')
    parser.add_argument('--table', default='devotionals', help='Table name (default: devotionals)')
    parser.add_argument('--column', required=True, help='Target column to populate (e.g., prayer)')
    parser.add_argument(
        '--reflections-column',
        default='reflection',
        help='Source column (default: reflection)',
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of rows (ignored with --id)',
    )
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
    parser.add_argument('--dry-run', action='store_true', help='Preview only; no changes written')
    parser.add_argument('--non-interactive', action='store_true', help='Apply without prompts')
    parser.add_argument(
        '--model',
        default=os.getenv('CLAUDE_MODEL', 'claude-3-5-sonnet-20240620'),
        help='Anthropic model (default: claude-3-5-sonnet-20240620)',
    )
    parser.add_argument('--temperature', type=float, default=0.4, help='Creativity (default: 0.4)')
    parser.add_argument('--max-tokens', type=int, default=200, help='Max tokens (default: 200)')
    parser.add_argument(
        '--avoid-memory',
        type=int,
        default=3,
        help='Remember this many recent openings to avoid (default: 3; set 0 to disable)',
    )

    args = parser.parse_args()

    # Ensure DB path aligns with database.py
    override_db_path(args.db_path)

    # Safety note
    if args.id_value and args.limit:
        print('Note: --id provided; --limit will be ignored.', file=sys.stderr)

    # Set up recent opener memory
    recent_openers = deque(maxlen=max(0, args.avoid_memory))
    # Optionally seed with a most-overused opener
    # recent_openers.append("Lord")  # not necessary with current prompt, but available

    # Acquire rows
    with database.get_conn(database.DB_PATH) as conn:
        rows: List[Dict[str, Any]] = []

        if args.id_value:
            row = select_row_by_id(
                conn=conn,
                table=args.table,
                id_col=args.id_column,
                target_col=args.column,
                reflections_col=args.reflections_column,
                id_value=args.id_value,
            )
            if row:
                rows = [row]
            else:
                print(f'No row found with {args.id_column} = {args.id_value}')
                return
        else:
            rows = select_rows_for_column_empty(
                conn=conn,
                table=args.table,
                id_col=args.id_column,
                target_col=args.column,
                reflections_col=args.reflections_column,
                limit=args.limit,
            )
            if not rows:
                print('No rows found with NULL/empty target column.')
                return

        apply_all = False
        processed = 0
        updated = 0

        for idx, row in enumerate(rows, start=1):
            row_id = row['_id']
            current_value = row.get('_target')
            reflection = (row.get('_reflections') or '').strip()

            if not reflection:
                print(f'Skipping ID={row_id} because {args.reflections_column} is empty.')
                processed += 1
                continue

            # Build prompt with dynamic avoid list (if memory enabled)
            avoid_list = list(recent_openers) if recent_openers.maxlen and len(recent_openers) > 0 else None
            prompt = build_prompt(reflection_text=reflection, avoid_openers=avoid_list)

            # AI call with simple retries
            ai_value = None
            attempt = 0
            backoff = 5
            while True:
                try:
                    ai_value = call_claude(
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

            if not ai_value:
                processed += 1
                continue

            # Track the opening to reduce repetition next time
            if recent_openers.maxlen:
                opener = extract_opening(ai_value)
                if opener:
                    # Normalize typical punctuation spacing
                    opener = ' '.join(opener.split())
                    recent_openers.append(opener)

            # Interactive or non-interactive application
            if args.non_interactive:
                if args.dry_run:
                    print_row_preview(idx, row_id, args.column, current_value, ai_value, reflection)
                    processed += 1
                    continue
                update_target_column(conn, args.table, args.id_column, row_id, args.column, ai_value)
                updated += 1
                processed += 1
                continue

            # Interactive preview (includes Reflection block at 80 cols)
            print_row_preview(idx, row_id, args.column, current_value, ai_value, reflection)

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
                    update_target_column(conn, args.table, args.id_column, row_id, args.column, ai_value)
                    updated += 1
                processed += 1

        print('\nSummary:')
        print(f'- Processed: {processed}')
        print(f'- Updated:   {updated}')
        if args.dry_run:
            print('- Mode:      DRY RUN (no changes written)')


if __name__ == '__main__':
    main()
