#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from anthropic import Anthropic, APIStatusError  # pip install anthropic

SEPARATOR = "=" * 50

# Defaults (tune as needed)
DEFAULT_MODEL = os.getenv("CLAUDE_PRAYER_MODEL", "claude-3-haiku-20240307")
DEFAULT_MAX_TOKENS = int(os.getenv("CLAUDE_PRAYER_MAX_TOKENS", "300"))
DEFAULT_TEMPERATURE = float(os.getenv("CLAUDE_PRAYER_TEMPERATURE", "0.5"))
DEFAULT_RETRIES = int(os.getenv("CLAUDE_PRAYER_RETRIES", "3"))
DEFAULT_RETRY_DELAY = float(os.getenv("CLAUDE_PRAYER_RETRY_DELAY", "1.5"))

# Strip common trailing AI markers in existing prayer content before diffing
AI_TRAILING_RE = re.compile(r"\s*\(\s*AI\s*\)\s*$", re.IGNORECASE)


def strip_trailing_ai_marker(text: str) -> str:
    if not isinstance(text, str):
        return text
    return AI_TRAILING_RE.sub("", text).rstrip()


def load_json_records(data: Any, filename: Path):
    """
    Accept:
      - top-level list of records
      - top-level dict with exactly one list value
    Returns (records, container, key) so we can write back consistently.
    """
    if isinstance(data, list):
        return data, None, None
    if isinstance(data, dict):
        list_keys = [k for k, v in data.items() if isinstance(v, list)]
        if len(list_keys) == 1:
            key = list_keys[0]
            return data[key], data, key
        raise ValueError(
            f"{filename}: expected a list or a dict with a single list of records"
        )
    raise ValueError(f"{filename}: unsupported JSON structure")


def build_claude_messages(
    reflection: str, verse: str, reading: str
) -> List[Dict[str, str]]:
    """
    Prompt Claude to generate a 2–5 sentence prayer grounded in the reflection, verse, and (optional) reading.
    """
    reflection = (reflection or "").strip()
    verse = (verse or "").strip()
    reading = (reading or "").strip()

    instr = (
        "Compose a sincere, biblically-faithful prayer (2–5 sentences) based on the provided content.\n"
        "Guidelines:\n"
        "- Use clear, reverent language addressed to God (e.g., 'Heavenly Father', 'Lord').\n"
        "- Connect to the themes found in the reflection and scripture reference(s).\n"
        "- Avoid quoting the full verse text; refer to it thematically.\n"
        "- Do not add emojis.\n"
        "- End with 'Amen.'\n"
    )
    context_lines = []
    if verse:
        context_lines.append(f"Verse: {verse}")
    if reading:
        context_lines.append(f"Reading: {reading}")
    if reflection:
        context_lines.append(f"Reflection:\n{reflection}")
    context = "\n".join(context_lines).strip() or "Reflection: (none provided)"

    return [
        {
            "role": "user",
            "content": f"{instr}\n{context}\n\nWrite only the prayer text.",
        }
    ]


def call_claude_for_prayer(
    client: Anthropic,
    reflection: str,
    verse: str,
    reading: str,
    model: str,
    max_tokens: int,
    temperature: float,
    retries: int = DEFAULT_RETRIES,
    retry_delay: float = DEFAULT_RETRY_DELAY,
) -> str:
    """
    Ask Claude to produce a 2–5 sentence prayer. Returns the cleaned prayer text.
    """
    messages = build_claude_messages(reflection, verse, reading)
    last_err: Optional[Exception] = None

    for attempt in range(1, retries + 1):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=messages,
            )
            # Collect text from content blocks
            text_parts: List[str] = []
            for block in resp.content or []:
                if getattr(block, "type", None) == "text":
                    text_parts.append(block.text)
                elif isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            raw = " ".join([p for p in text_parts if p]).strip()
            prayer = clean_prayer(raw)
            if not prayer:
                raise RuntimeError("Empty AI prayer result after cleaning.")
            # Ensure it ends with "Amen."
            if not re.search(r"\bAmen\.?\s*$", prayer, re.IGNORECASE):
                prayer = prayer.rstrip(". ") + " Amen."
            return prayer
        except (APIStatusError, Exception) as e:
            last_err = e
            if attempt < retries:
                time.sleep(retry_delay)
            else:
                raise RuntimeError(
                    f"Claude prayer generation failed after {retries} attempts: {e}"
                ) from e

    raise RuntimeError(f"Claude prayer generation failed: {last_err}")


def clean_prayer(text: str) -> str:
    """
    Normalize whitespace, remove enclosing quotes/backticks if any, and ensure reasonable length.
    """
    if not isinstance(text, str):
        return ""
    s = text.strip().strip('"').strip("'").strip("`")
    # Collapse whitespace/newlines
    s = re.sub(r"\s+", " ", s).strip()
    # Optional: constrain excessively long outputs (rare with our tokens)
    if len(s) > 1200:
        s = s[:1200].rstrip()
    return s


def process_file(
    path: Path,
    preview: bool,
    client: Anthropic,
    model: str,
    temperature: float,
    max_tokens: int,
    only_if_empty: bool,
) -> int:
    """
    For each record:
      - If only_if_empty is True:
          Generate and set prayer ONLY if 'prayer' is empty after trim.
      - Else:
          Always generate a new prayer (overwriting existing), using reflection/verse/reading context.
      - In all cases we set ai_prayer=True for records we update.
    In preview mode: show before/after only for changed records.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        records, container, key = load_json_records(raw, path)
    except Exception as e:
        print(f"[ERROR] {path}: cannot read/parse JSON: {e}")
        return 2

    updated_records: List[Dict[str, Any]] = []
    preview_items: List[Tuple[int, Dict[str, str]]] = []

    for idx, rec in enumerate(records, start=1):
        if not isinstance(rec, dict):
            updated_records.append(rec)
            continue

        curr_prayer_raw = rec.get("prayer", "")
        curr_prayer = curr_prayer_raw if isinstance(curr_prayer_raw, str) else ""
        curr_prayer_no_ai = strip_trailing_ai_marker(curr_prayer)

        # Skip update if only_if_empty and there's content
        if only_if_empty and curr_prayer_no_ai.strip():
            updated_records.append(rec)
            continue

        reflection = (rec.get("reflection") or "").strip()
        verse = (rec.get("verse") or "").strip()
        reading = (rec.get("reading") or "").strip()

        try:
            new_prayer = call_claude_for_prayer(
                client=client,
                reflection=reflection,
                verse=verse,
                reading=reading,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            # Report error and keep going
            print(f"[ERROR] {path}:{idx} AI prayer generation failed: {e}")
            updated_records.append(rec)
            continue

        # Apply update
        rec_copy = dict(rec)
        rec_copy["prayer"] = new_prayer
        rec_copy["ai_prayer"] = True
        updated_records.append(rec_copy)

        if preview:
            preview_items.append(
                (
                    idx,
                    {
                        "before_prayer": curr_prayer,
                        "after_prayer": new_prayer,
                        "ai_prayer": "true",
                    },
                )
            )

    if preview:
        if preview_items:
            print(f"\n=== Preview: {path} ===")
            for idx, payload in preview_items:
                print(SEPARATOR)
                print(f"Record {idx}:")
                print(f"- prayer (before): {payload['before_prayer']}")
                print(f"- prayer (after) : {payload['after_prayer']}")
                print(f"- ai_prayer      : {payload['ai_prayer']}")
            print(SEPARATOR)
        else:
            print(f"\n=== Preview: {path} ===")
            print("- No changes")
        return 0

    # Write changes
    try:
        out = (
            updated_records
            if container is None
            else {**container, key: updated_records}
        )
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] {path}: updated prayers")
        return 0
    except Exception as e:
        print(f"[ERROR] {path}: failed to write updates: {e}")
        return 2


def main():
    parser = argparse.ArgumentParser(
        description="Generate/update 'prayer' (2–5 sentences) with Claude using reflection, verse, and reading. Sets ai_prayer=true on updates."
    )
    parser.add_argument(
        "files", nargs="+", help="One or more JSON files (e.g., *.json)"
    )
    parser.add_argument(
        "--preview", action="store_true", help="Show before/after without writing files"
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Claude model (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=DEFAULT_TEMPERATURE,
        help=f"Sampling temperature (default: {DEFAULT_TEMPERATURE})",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help=f"Max tokens (default: {DEFAULT_MAX_TOKENS})",
    )
    parser.add_argument(
        "--only-if-empty",
        action="store_true",
        help="Only generate a prayer when the existing 'prayer' field is empty (after stripping optional trailing (AI))",
    )
    args = parser.parse_args()

    # Prefer CLAUDE_API_KEY, fall back to ANTHROPIC_API_KEY for compatibility
    api_key = os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("[ERROR] CLAUDE_API_KEY (or ANTHROPIC_API_KEY) is not set.")
        sys.exit(2)

    client = Anthropic(api_key=api_key)

    exit_code = 0
    for file_arg in args.files:
        path = Path(file_arg)
        if not path.exists():
            print(f"[ERROR] {path}: not found")
            exit_code = max(exit_code, 2)
            continue
        rc = process_file(
            path=path,
            preview=args.preview,
            client=client,
            model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            only_if_empty=args.only_if_empty,
        )
        exit_code = max(exit_code, rc)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
