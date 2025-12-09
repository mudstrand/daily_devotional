import json
import sys

if __name__ == '__main__':
    filepath = sys.argv[1]
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            json.load(f)
        print(f'{filepath} is a valid JSON file.')
    except json.JSONDecodeError as e:
        print(f'Error decoding JSON in {filepath}: {e}')
