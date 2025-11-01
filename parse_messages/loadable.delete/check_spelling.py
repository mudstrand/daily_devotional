#!/usr/bin/env python3
import json
import os
import re
import sys
import shutil
import difflib
from typing import Dict, List, Tuple, Optional

# Default fields to process (you can override with --fields)
DEFAULT_FIELDS = ["subject", "verse", "reflection", "prayer", "reading"]

# Built-in allowlists (augment via files too)
GLOBAL_ALLOWLIST = {
    "else's",
    "uncircumcision",
    "lackest",
    "hearted",
    "another's",
    "flittering",
    "Israelites",
    "Christ-like",
    "Crispus",
    "Gaius",
    "Immanuel",
    "Triune",
    "Philippi",
    "Spurgeon",
    "Christhas",
}
FIELD_ALLOWLIST: Dict[str, set] = {
    "reading": {"Ps"},
}
CUSTOM_WORDS = set()  # legacy support

# Optional allowlist files (one word per line, case-insensitive, '#' comments)
GLOBAL_ALLOWLIST_FILE = "allowlist_global.txt"
FIELD_ALLOWLIST_FILE_TEMPLATE = "allowlist_{field}.txt"

PAREN_RE = re.compile(r"\([^()]*\)")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")
SEPARATOR = "=" * 72


def script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def read_json_file(path: str) -> Optional[Tuple[object, str]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return json.loads(content), content
    except Exception:
        return None


def write_json_file(path: str, data) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")


def load_allowlist_file(path: str) -> set:
    items = set()
    if not os.path.isfile(path):
        return items
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                items.add(s)
    except Exception:
        pass
    return items


def build_allowlists() -> Tuple[set, Dict[str, set], set]:
    base = script_dir()
    global_words = set(GLOBAL_ALLOWLIST)
    field_map: Dict[str, set] = {k: set(v) for k, v in FIELD_ALLOWLIST.items()}
    # file globals
    global_words |= load_allowlist_file(os.path.join(base, GLOBAL_ALLOWLIST_FILE))
    # file per-field
    for field in DEFAULT_FIELDS:
        fp = os.path.join(base, FIELD_ALLOWLIST_FILE_TEMPLATE.format(field=field))
        if os.path.isfile(fp):
            field_map.setdefault(field, set()).update(load_allowlist_file(fp))
    # lowercase maps
    global_lower = {w.lower() for w in global_words}
    field_lower_map = {k: {w.lower() for w in v} for k, v in field_map.items()}
    custom_lower = {w.lower() for w in CUSTOM_WORDS}
    return global_lower, field_lower_map, custom_lower


def remove_parentheticals(text: str) -> str:
    prev = None
    curr = text
    while prev != curr:
        prev = curr
        curr = PAREN_RE.sub("", curr)
    return curr


def tokenize_words(text: str):
    return list(WORD_RE.finditer(text))


def preserve_case(original: str, suggestion: str) -> str:
    if original.islower():
        return suggestion.lower()
    if original.isupper():
        return suggestion.upper()
    if original.istitle():
        return suggestion.title()
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


def is_allowed_word(
    word: str,
    field: str,
    global_allow: set,
    field_allow_map: Dict[str, set],
    custom_allow: set,
) -> bool:
    wl = word.lower()
    if wl in global_allow:
        return True
    if wl in field_allow_map.get(field, set()):
        return True
    if wl in custom_allow:
        return True
    return False


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
    miss_l = misspelled.lower()
    for s in suggestions:
        if not s:
            continue
        if not speller.check(s) or s.lower() == miss_l:
            continue
        candidates.append((s, suggestion_confidence(misspelled, s)))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0]


def replace_outside_parentheses(s: str, old: str, new: str) -> str:
    """
    Replace old -> new outside parentheses. Two passes:
      1) Replace old plus dash-like trailing marks (prayed-, prayed—, prayed--, etc.) -> new
      2) If nothing changed, replace bare old as a whole word -> new
    """
    dash_class = r"\-–—‒―−"  # hyphen, en, em, figure, horiz bar, minus
    zw_chars = "\u200c\u200d\u200b"  # ZWNJ, ZWJ, ZWSP
    pat_glued = re.compile(
        rf"\b{re.escape(old)}(?:[{dash_class}]+(?:'|’)?[{zw_chars}]*)?\b"
    )
    pat_bare = re.compile(rf"\b{re.escape(old)}\b")

    def repl_token(m: re.Match) -> str:
        return preserve_case(m.group(0)[: len(old)], new)

    # split out/in parentheses
    segments = []
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

    out = []
    for typ, seg in segments:
        if typ == "out":
            seg2, n1 = pat_glued.subn(repl_token, seg)
            if n1 == 0:
                seg2, _n2 = pat_bare.subn(repl_token, seg)
            out.append(seg2)
        else:
            out.append(seg)
    return "".join(out)


def find_field_key_line(content: str, key: str) -> int:
    for i, line in enumerate(content.splitlines(), start=1):
        if f'"{key}"' in line:
            return i
    return 1


def find_match_line_for_word(content: str, key: str, word: str) -> int:
    lines = content.splitlines(True)
    start_line_idx = next((i for i, ln in enumerate(lines) if f'"{key}"' in ln), 0)
    region = "".join(lines[start_line_idx:])
    m = re.search(rf"\b{re.escape(word)}\b", region)
    if not m:
        return find_field_key_line(content, key)
    abs_index = sum(len(ln) for ln in lines[:start_line_idx]) + m.start()
    return content[:abs_index].count("\n") + 1


def collect_batch(
    speller,
    base_dir: str,
    fields: List[str],
    min_conf: float,
    lowercase_only: bool,
    page_size: int,
    global_allow: set,
    field_allow_map: Dict[str, set],
    custom_allow: set,
):
    """
    Return up to page_size items:
      dict: file, key, line, old, new, conf, apply_fn
    """
    batch = []
    for name in sorted(os.listdir(base_dir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(base_dir, name)
        loaded = read_json_file(path)
        if not loaded:
            continue
        data, content = loaded

        def per_field(obj: Dict, key: str):
            nonlocal batch
            val = obj.get(key)
            if not isinstance(val, str):
                return
            filtered = remove_parentheticals(val)
            for m in tokenize_words(filtered):
                if len(batch) >= page_size:
                    return
                w = m.group(0)
                # Skip tokens ending with a trailing apostrophe to avoid plural possessive "fixes"
                if w.endswith("'") or w.endswith("’"):
                    continue
                # lowercase-only pass (default)
                if lowercase_only and not w.islower():
                    continue
                if is_allowed_word(w, key, global_allow, field_allow_map, custom_allow):
                    continue
                if speller.check(w):
                    continue
                best = best_suggestion(speller, w, speller.suggest(w))
                if not best:
                    continue
                sug, conf = best
                if conf < min_conf:
                    continue
                fixed = preserve_case(w, sug)
                line = find_match_line_for_word(content, key, w)

                def make_apply(pth: str, field_key: str, old_word: str, new_word: str):
                    def apply_change():
                        loaded2 = read_json_file(pth)
                        if not loaded2:
                            return 0
                        data2, _content2 = loaded2
                        count = 0

                        def apply_to_obj(obj2: Dict):
                            nonlocal count
                            if field_key in obj2 and isinstance(obj2[field_key], str):
                                before = obj2[field_key]
                                after = replace_outside_parentheses(
                                    before, old_word, new_word
                                )
                                if after != before:
                                    # Count both glued and bare occurrences outside parentheses
                                    dash_class = r"\-–—‒―−"
                                    zw_chars = "\u200c\u200d\u200b"
                                    count_pat = re.compile(
                                        rf"\b{re.escape(old_word)}[{dash_class}]+(?:'|’)?[{zw_chars}]*\b|\b{re.escape(old_word)}\b"
                                    )
                                    c = len(
                                        count_pat.findall(remove_parentheticals(before))
                                    )
                                    obj2[field_key] = after
                                    count += c

                        if isinstance(data2, list):
                            for it in data2:
                                if isinstance(it, dict):
                                    apply_to_obj(it)
                        elif isinstance(data2, dict):
                            apply_to_obj(data2)
                        if count > 0:
                            shutil.copy2(pth, pth + ".bak")
                            write_json_file(pth, data2)
                        return count

                    return apply_change

                batch.append(
                    {
                        "file": name,
                        "key": key,
                        "line": line,
                        "old": w,
                        "new": fixed,
                        "conf": conf,
                        "apply_fn": make_apply(path, key, w, fixed),
                    }
                )

        # Process all selected fields for all objects (list or dict)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    for f in fields:
                        per_field(item, f)
                        if len(batch) >= page_size:
                            break
                if len(batch) >= page_size:
                    break
        elif isinstance(data, dict):
            for f in fields:
                per_field(data, f)
                if len(batch) >= page_size:
                    break
        if len(batch) >= page_size:
            break
    return batch


def prompt_yes_no(question: str) -> str:
    while True:
        ans = input(f"{question} [y/n/q]: ").strip().lower()
        if ans in ("y", "yes"):
            return "y"
        if ans in ("n", "no"):
            return "n"
        if ans in ("q", "quit"):
            return "q"
        print("Please answer y, n, or q.")


def main():
    import argparse

    ap = argparse.ArgumentParser(
        description="Single-batch spelling suggestions across selected JSON fields; supports allowlists, lowercase-first, apostrophe ignore, and robust apply."
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--count", action="store_true", help="List all matches (no prompt, no changes)"
    )
    mode.add_argument(
        "--yes",
        action="store_true",
        help="Apply all fixes in the batch without prompting",
    )
    ap.add_argument(
        "--min-confidence",
        type=float,
        default=0.90,
        help="Minimum confidence to include (default: 0.90)",
    )
    ap.add_argument(
        "--fields",
        nargs="*",
        default=DEFAULT_FIELDS,
        help="Fields to scan (default: subject verse reflection prayer reading)",
    )
    ap.add_argument(
        "--page-size",
        type=int,
        default=20,
        help="Max suggestions to show in the batch (default: 20)",
    )
    lf = ap.add_mutually_exclusive_group()
    lf.add_argument(
        "--lowercase-first",
        dest="lowercase_first",
        action="store_true",
        default=True,
        help="Only consider lowercase words (default)",
    )
    lf.add_argument(
        "--no-lowercase-first",
        dest="lowercase_first",
        action="store_false",
        help="Include capitalized words too",
    )
    args = ap.parse_args()

    if not (0.0 <= args.min_confidence <= 1.0):
        print("Error: --min-confidence must be between 0.0 and 1.0", file=sys.stderr)
        sys.exit(2)

    base = script_dir()
    speller = init_speller()
    if not speller:
        print("Spelling checker not available; aborting.", file=sys.stderr)
        sys.exit(1)

    global_allow, field_allow_map, custom_allow = build_allowlists()

    # Count mode: list every match across all files/fields (no batching), no writes
    if args.count:
        total = 0
        for name in sorted(os.listdir(base)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(base, name)
            loaded = read_json_file(path)
            if not loaded:
                continue
            data, content = loaded

            def per_field_list(obj: Dict, key: str):
                nonlocal total
                val = obj.get(key)
                if not isinstance(val, str):
                    return
                filtered = remove_parentheticals(val)
                for m in tokenize_words(filtered):
                    w = m.group(0)
                    if args.lowercase_first and not w.islower():
                        continue
                    if w.endswith("'") or w.endswith("’"):
                        continue
                    if is_allowed_word(
                        w, key, global_allow, field_allow_map, custom_allow
                    ):
                        continue
                    if speller.check(w):
                        continue
                    best = best_suggestion(speller, w, speller.suggest(w))
                    if not best:
                        continue
                    sug, conf = best
                    if conf < args.min_confidence:
                        continue
                    line = find_match_line_for_word(content, key, w)
                    print(
                        f"code -g {name}:{line} | {key}: '{w}' -> '{preserve_case(w, sug)}'  [confidence: {conf:.2f}]"
                    )
                    total += 1

            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        for f in args.fields:
                            per_field_list(item, f)
            elif isinstance(data, dict):
                for f in args.fields:
                    per_field_list(data, f)
        print(SEPARATOR)
        print(f"Total suggestions: {total}")
        sys.exit(0)

    # Single-batch mode
    batch = collect_batch(
        speller=speller,
        base_dir=base,
        fields=args.fields,
        min_conf=args.min_confidence,
        lowercase_only=args.lowercase_first,
        page_size=args.page_size,
        global_allow=global_allow,
        field_allow_map=field_allow_map,
        custom_allow=custom_allow,
    )

    if not batch:
        print("No suggestions found.")
        sys.exit(0)

    print(SEPARATOR)
    for item in batch:
        print(
            f"code -g {item['file']}:{item['line']} | {item['key']}: '{item['old']}' -> '{item['new']}'  [confidence: {item['conf']:.2f}]"
        )
    print(SEPARATOR)

    if args.yes:
        decision = "y"
    else:
        decision = prompt_yes_no("Apply ALL fixes in this batch?")

    if decision == "q":
        print("Aborted.")
        sys.exit(1)
    if decision == "n":
        print("Skipped applying this batch.")
        sys.exit(0)

    # Apply batch
    total_applied = 0
    for item in batch:
        total_applied += item["apply_fn"]()

    print(f"Applied {total_applied} change(s) across {len(batch)} item(s).")


if __name__ == "__main__":
    main()
