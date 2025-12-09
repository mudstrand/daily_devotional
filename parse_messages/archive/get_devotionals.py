#!/usr/bin/env python3
import argparse
import database


def build_args():
    p = argparse.ArgumentParser(description='Fetch random devotionals from the database.')
    p.add_argument(
        '--count',
        type=int,
        default=1,
        help='How many devotionals to fetch (default 1).',
    )
    p.add_argument(
        '--include-read',
        action='store_true',
        help='If not enough unread, include previously read items to fill the count.',
    )
    p.add_argument('--mark-date', help='YYYY-MM-DD to record as read_date (default: today).')
    p.add_argument(
        '--no-mark',
        action='store_true',
        help='Do not mark selected devotionals as read.',
    )
    return p.parse_args()


def main():
    args = build_args()
    database.init_db()

    # Fetch up to count unread
    rows = database.get_random_unread(args.count)
    picked = list(rows)

    # If we need more and --include-read is set, fill with random read
    if len(picked) < args.count and args.include_read:
        remain = args.count - len(picked)
        picked += database.get_random_read(remain)

    # Print results
    if not picked:
        print('No devotionals found.')
        return

    for r in picked:
        print('-' * 40)
        print(f'Message ID: {r["message_id"]}')
        print(f'Subject: {r["subject"]}')
        print()
        print('Verse:')
        print(r['verse'] or '')
        print()
        print('Reflection:')
        print(r['reflection'] or '')
        print()
        print('Prayer:')
        print(r['prayer'] or '')

    # Mark as read unless suppressed
    if not args.no_mark:
        to_mark = [r['message_id'] for r in rows]  # only mark unread picks
        if to_mark:
            database.mark_read(to_mark, mark_date=args.mark_date)
            print(f'\nMarked {len(to_mark)} devotional(s) as read.')


if __name__ == '__main__':
    main()
