#!/usr/bin/env python3
import json
import os
import re
import sys
from typing import Dict, Optional, Tuple

FIELDS = ["subject", "verse", "reflection", "prayer", "reading"]
LANG_CODE = "en-US"


def script_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def read_json_file(path: str) -> Optional[Tuple[object, str]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return json.loads(content), content
    except Exception:
        return None


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


def init_grammar():
    try:
        import language_tool_python as lt_mod

        try:
            return lt_mod.LanguageTool(LANG_CODE)
        except Exception:
            return lt_mod.LanguageToolPublicAPI(LANG_CODE)
    except Exception as e:
        print(f"Error: language_tool_python unavailable ({e}).", file=sys.stderr)
        return None


def match_span(m):
    offset = getattr(m, "offset", None)
    length = getattr(m, "errorLength", None)
    if offset is None:
        offset = getattr(m, "offsetInContext", 0)
    if length is None:
        try:
            ctx = getattr(m, "context", None) or getattr(m, "contextForSureMatch", None)
            length = len(str(ctx)) if ctx else 0
        except Exception:
            length = 0
    try:
        return int(offset), int(length)
    except Exception:
        return 0, 0


def match_message(m) -> str:
    rid = getattr(m, "ruleId", None) or getattr(m, "rule", None) or "RULE"
    msg = getattr(m, "message", None) or "Issue"
    return f"Grammar ({rid}): {msg}"


def inspect_record(tool, obj: Dict, file_content: str, filename: str):
    for field in FIELDS:
        val = obj.get(field)
        if not isinstance(val, str):
            continue
        text = val
        try:
            matches = tool.check(text)
        except Exception:
            matches = []
        for m in matches:
            offset, length = match_span(m)
            start = max(0, offset - 20)
            end = min(len(text), offset + max(1, length) + 20)
            context = text[start:end].replace("\n", " ")
            msg = f"{match_message(m)} | ...{context}..."
            line = find_line_number_for_field(file_content, field, text)
            print(f"{field}: {msg} -> code -g {filename}:{1 if line == -1 else line}")


def main():
    tool = init_grammar()
    if not tool:
        sys.exit(1)

    base = script_dir()

    any_json = False
    for name in sorted(os.listdir(base)):
        if not name.endswith(".json"):
            continue
        any_json = True
        data_content = read_json_file(os.path.join(base, name))
        if not data_content:
            continue
        data, content = data_content
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    inspect_record(tool, item, content, name)
        elif isinstance(data, dict):
            inspect_record(tool, data, content, name)

    if not any_json:
        print("No JSON files found", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
