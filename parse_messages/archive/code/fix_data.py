import json
import os
import re
from collections import defaultdict


def fix_data():
    """
    Fixes the issues reported in edit.txt.
    """
    with open('edit.txt', 'r', encoding='utf-8') as f:
        lines = f.readlines()

    files_to_fix = defaultdict(list)
    for line in lines:
        if ':' in line:
            parts = line.split(':')
            if len(parts) > 2:
                filepath = parts[1].strip()
                issue = parts[0].strip()
                files_to_fix[filepath].append(issue)

    for filepath, issues in files_to_fix.items():
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except FileNotFoundError:
            print(f'File not found: {filepath}')
            continue

        original_content = content

        # 1. Remove HTML tags
        content = re.sub(r'<[^>]+>', '', content)

        # 2. Remove Markdown syntax
        content = content.replace('**', '').replace('*', '').replace('_', '').replace('#', '')
        content = re.sub(r'\[([^]]+)\]\(([^)]+)\)', r'\1 (\2)', content)

        # 3. Replace smart quotes and em-dashes
        content = content.replace('“', '"').replace('”', '"')
        content = content.replace('‘', "'").replace('’', "'")
        content = content.replace('—', '--')

        # 4. Remove other non-printable characters
        content = re.sub(r'[^\x20-\x7E\n\r\t]', '', content)

        # 5. Remove repeated words
        content = re.sub(r'\b(\w+)\s+\1\b', r'\1', content, flags=re.IGNORECASE)

        if content != original_content:
            print(f'Fixing {filepath}...')
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)


if __name__ == '__main__':
    fix_data()
