import json
import os
import re


def comprehensive_scan():
    """
    Performs a comprehensive scan of the JSON files in the loadable directory for a variety of issues.
    """
    fields_to_check = ['subject', 'verse', 'reflection', 'prayer']
    output_file = 'edit.txt'

    with open(output_file, 'w', encoding='utf-8') as f_out:
        for filename in os.listdir('loadable'):
            if filename.endswith('.json'):
                filepath = os.path.join('loadable', filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f_in:
                        lines = f_in.readlines()
                        content = ''.join(lines)
                        data = json.loads(content)
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    f_out.write(f'Error reading {filepath}: {e}\n')
                    continue

                records = data if isinstance(data, list) else [data]

                for i, record in enumerate(records):
                    for field in fields_to_check:
                        if field in record and isinstance(record[field], str):
                            value = record[field]

                            # Find line number for the value
                            line_num = -1
                            for j, line in enumerate(lines):
                                if value in line:
                                    line_num = j + 1
                                    break

                            # Check for non-printable characters (including smart quotes)
                            non_printable = re.findall(r'[^\x20-\x7E\n\r\t]', value)
                            if non_printable:
                                f_out.write(f'Unusual characters in {field} at: {filepath}:{line_num}\n')
                                f_out.write(f'  Characters: {list(set(non_printable))}\n')

                            # Check for HTML/XML tags
                            html_tags = re.findall(r'<[^>]+>', value)
                            if html_tags:
                                f_out.write(f'HTML/XML tags in {field} at: {filepath}:{line_num}\n')
                                f_out.write(f'  Tags: {list(set(html_tags))}\n')

                            # Check for Markdown syntax
                            markdown = re.findall(r'(\*\*|\*|_|#|\[[^\]]+\]\([^)]+\))', value)
                            if markdown:
                                f_out.write(f'Markdown syntax in {field} at: {filepath}:{line_num}\n')
                                f_out.write(f'  Syntax: {list(set(markdown))}\n')

                            # Check for repeated words
                            repeated_words = re.findall(r'\b(\w+)\s+\1\b', value, re.IGNORECASE)
                            if repeated_words:
                                f_out.write(f'Repeated words in {field} at: {filepath}:{line_num}\n')
                                f_out.write(f'  Words: {list(set(repeated_words))}\n')


if __name__ == '__main__':
    comprehensive_scan()
