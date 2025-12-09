import json
import os
import re
import sys


def clean_text(text):
    # 1. Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # 2. Remove Markdown syntax
    text = text.replace('**', '').replace('*', '').replace('_', '').replace('#', '')
    text = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'\1 (\2)', text)

    # 3. Replace smart quotes and em-dashes
    text = text.replace('“', '"').replace('”', '"')
    text = text.replace('‘', "'").replace('’', "'")
    text = text.replace('—', '--')

    # 4. Remove other non-printable characters
    text = re.sub(r'[^\x20-\x7E\n\r\t]', '', text)

    # 5. Remove repeated words
    text = re.sub(r'\b(\w+)\s+\1\b', r'\1', text, flags=re.IGNORECASE)

    return text


def fix_json_file(filepath):
    """
    Fixes a single JSON file by cleaning the content of the specified fields.
    """
    fields_to_check = ['subject', 'verse', 'reflection', 'prayer']

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f'Error reading {filepath}: {e}')
        return

    if isinstance(data, list):
        for record in data:
            for field in fields_to_check:
                if field in record and isinstance(record[field], str):
                    record[field] = clean_text(record[field])
    elif isinstance(data, dict):
        for field in fields_to_check:
            if field in data and isinstance(data[field], str):
                data[field] = clean_text(data[field])

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
        fix_json_file(filepath)
    else:
        print('Please provide a file path.')
