#!/usr/bin/env python3
import difflib
import json
import os
import re
import shutil
import sys
from typing import Dict, List, Optional, Tuple

FIELDS = ["subject", "verse", "reflection", "prayer", "reading"]

# Domain-specific words to ignore (add your proper nouns here)
CUSTOM_WORDS = {
    # "Eucharist", "Thessalonians",
}

PAREN_RE = re.compile(r"\([^()]*\)")  # non-nested quick pass


def script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def read_json_file(path: str) -> Optional[Tuple[object, str]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return json.loads(content), content
    except Exception:
        return None


def write_json_file(path: str, data) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    return text


def find_line_number_for_field(content: str, key: str, value: str) -> int:
    escaped_key = re.escape(key)
    escaped_val = re.escape(value)
    pattern = re.compile(
        r'^\s*"' + escaped_key + r'"\s*:\s*"' + escaped_val + r'"\s*(?:,|}|])',
        re.MULTILINE,
    )
    m = pattern.search(content)
    if m:
        return content.count("\n", 0, m.start()) + 1
    exact = f'"{key}": "{value}"'
    for i, line in enumerate(content.splitlines(), start=1):
        if exact in line:
            return i
    frag = value[:30] if isinstance(value, str) else ""
    if frag:
        for i, line in enumerate(content.splitlines(), start=1):
            if f'"{key}"' in line and frag in line:
                return i
    return -1


def line_text_at(content: str, line_no: int) -> str:
    lines = content.splitlines()
    if not lines:
        return ""
    if line_no <= 0:
        return lines[0]
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1]
    return lines[-1]


def remove_parentheticals(text: str) -> str:
    """
    Remove parenthetical segments (including nested by iterating).
    Example: "Foo (bar) baz (qux(quux))" -> "Foo  baz "
    """
    prev = None
    curr = text
    # Iteratively strip non-nested parentheses until no change -> handles nesting
    while prev != curr:
        prev = curr
        curr = PAREN_RE.sub("", curr)
    return curr


def tokenize_words(text: str):
    return list(re.finditer(r"[A-Za-z][A-Za-z'\-]*", text))


def preserve_case(original: str, suggestion: str) -> str:
    if original.isupper():
        return suggestion.upper()
    if original.istitle():
        return suggestion.title()
    if original.islower():
        return suggestion.lower()
    return suggestion


def init_speller():
    try:
        import enchant as enchant_mod

        try:
            return enchant_mod.Dict("en_US")
        except enchant_mod.errors.DictNotFoundError:
            try:
                return enchant_mod.Dict("en_US-large")
            except Exception:
                print("Error: pyenchant en_US dictionary not found.", file=sys.stderr)
                return None
    except Exception as e:
        print(f"Error: pyenchant unavailable ({e}).", file=sys.stderr)
        return None


def spelling_issues(speller, text: str) -> List[Tuple[str, int, List[str]]]:
    """
    Return (word, position, suggestions) for misspellings, ignoring parenthetical content.
    Position is relative to the filtered text (used only for display ordering, not for slicing).
    """
    filtered = remove_parentheticals(text)
    issues = []
    custom_lower = {w.lower() for w in CUSTOM_WORDS}
    for m in tokenize_words(filtered):
        w = m.group(0)
        wl = w.lower()
        if wl in custom_lower:
            continue
        if w.isupper() and len(w) <= 5:
            continue
        if len(w) == 1 and wl not in ("a", "i"):
            continue
        if not speller.check(w):
            suggestions = speller.suggest(w)
            issues.append((w, m.start(), suggestions))
    return issues


def suggestion_confidence(misspelled: str, suggestion: str) -> float:
    if not re.fullmatch(r"[A-Za-z][A-Za-z'\-]*", suggestion):
        return 0.0
    base = difflib.SequenceMatcher(a=misspelled.lower(), b=suggestion.lower()).ratio()
    length_penalty = max(
        0.0, 1.0 - (abs(len(misspelled) - len(suggestion)) / max(1.0, len(misspelled)))
    )
    conf = 0.75 * base + 0.25 * length_penalty
    return max(0.0, min(1.0, conf))


def best_suggestion(
    speller, misspelled: str, suggestions: List[str]
) -> Optional[Tuple[str, float]]:
    candidates: List[Tuple[str, float]] = []
    for s in suggestions:
        if not s or not speller.check(s):
            continue
        candidates.append((s, suggestion_confidence(misspelled, s)))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0]


def apply_spelling_fixes(
    text: str, speller, min_conf: float, do_fix: bool
) -> Tuple[str, List[Tuple[str, str, float]]]:
    """
    Return (new_text, changes), where changes is list of (old, new, confidence).
    We skip applying changes inside parentheses by design (they were filtered out).
    """
    filtered = remove_parentheticals(text)
    changes: List[Tuple[str, str, float]] = []
    new_text = text

    # We only propose/replace tokens from the filtered text; to update original, we replace whole-word matches.
    tokens = tokenize_words(filtered)
    for m in tokens:
        w = m.group(0)
        if speller.check(w):
            continue
        best = best_suggestion(speller, w, speller.suggest(w))
        if not best:
            continue
        sug, conf = best
        if conf < min_conf:
            continue
        fixed = preserve_case(w, sug)
        changes.append((w, fixed, conf))
        if do_fix:
            # Replace whole-word occurrences in the original text that are NOT inside parentheses.
            # We reconstruct a regex that excludes parentheses by using the filtered tokens and word boundaries.
            # Safe approach: replace in the filtered copy, then map back by doing a cautious global replace in the original
            # but skipping parenthetical spans.
            pass  # see below

    if do_fix and changes:
        # Implement safe replace outside parentheses:
        # Split original into segments: outside and inside parentheses
        segments = []
        s = new_text
        idx = 0
        stack = []
        last = 0
        for i, ch in enumerate(s):
            if ch == "(":
                if not stack:
                    segments.append(("out", s[last:i]))
                    last = i
                stack.append(i)
            elif ch == ")":
                if stack:
                    stack.pop()
                    if not stack:
                        segments.append(("in", s[last : i + 1]))
                        last = i + 1
        segments.append(("out", s[last:]))

        def replace_outside(segment: str) -> str:
            for old, new, _conf in changes:
                segment = re.sub(
                    rf"\b{re.escape(old)}\b",
                    lambda m: preserve_case(m.group(0), new),
                    segment,
                )
            return segment

        rebuilt = []
        for typ, seg in segments:
            if typ == "out":
                rebuilt.append(replace_outside(seg))
            else:
                rebuilt.append(seg)
        new_text = "".join(rebuilt)

    return new_text, changes


def process_file(path: str, do_fix: bool, fields: List[str], min_conf: float):
    loaded = read_json_file(path)
    if not loaded:
        return
    data, content = loaded
    name = os.path.basename(path)

    speller = init_speller()
    if not speller:
        print("Spelling checker not available; aborting.", file=sys.stderr)
        sys.exit(1)

    changed = False

    def handle_field(obj: Dict, key: str):
        nonlocal changed
        val = obj.get(key)
        if not isinstance(val, str):
            return

        new_val, changes = apply_spelling_fixes(
            val, speller, min_conf=min_conf, do_fix=do_fix
        )

        if changes:
            line = find_line_number_for_field(content, key, val)
            line_text = line_text_at(content, 1 if line == -1 else line)
            for old, new, conf in changes:
                print(f"{key}: '{old}' -> '{new}'  [confidence: {conf:.2f}]")
                print(f"    {line_text}")
                print(f"    code -g {name}:{1 if line == -1 else line}")

        if do_fix and new_val != val:
            obj[key] = new_val
            changed = True

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                for f in fields:
                    handle_field(item, f)
    elif isinstance(data, dict):
        for f in fields:
            handle_field(data, f)

    if do_fix and changed:
        shutil.copy2(path, path + ".bak")
        write_json_file(path, data)
        print(f"Updated {name}")


def main():
    import argparse

    ap = argparse.ArgumentParser(
        description="Check spelling in selected JSON fields, ignoring parentheses; report confidence and optionally fix."
    )
    ap.add_argument(
        "--fix",
        action="store_true",
        help="Apply fixes in-place outside parentheses (creates .bak)",
    )
    ap.add_argument(
        "--min-confidence",
        type=float,
        default=0.90,
        help="Minimum confidence in [0,1] to report/apply (default: 0.90)",
    )
    ap.add_argument(
        "--fields",
        nargs="*",
        default=FIELDS,
        help="Fields to check (default: subject verse reflection prayer reading)",
    )
    args = ap.parse_args()

    if not (0.0 <= args.min_confidence <= 1.0):
        print("Error: --min-confidence must be between 0.0 and 1.0", file=sys.stderr)
        sys.exit(2)

    base = script_dir()
    any_json = False
    for name in sorted(os.listdir(base)):
        if not name.endswith(".json"):
            continue
        any_json = True
        process_file(
            os.path.join(base, name),
            do_fix=args.fix,
            fields=args.fields,
            min_conf=args.min_confidence,
        )
    if not any_json:
        print("No JSON files found", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
