from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .file_io import atomic_write_text
from .sources import load_events


def format_message(event: dict) -> str | None:
    if event['decision'] not in ('alert', 'watch'):
        return None

    reasons = event.get('reasons', [])
    reason_text = '\n'.join(f'- {reason}' for reason in reasons[:4])
    return '\n'.join([
        f"[{event['decision'].upper()}] {event['symbol']} on {event['chain']}",
        f"Score: {event['score']}",
        f"Token: {event['token_address']}",
        f"Market cap: {event['market_cap']}",
        f"Liquidity: {event['liquidity']}",
        'Reasons:',
        reason_text or '- no reasons recorded',
    ])


def build_messages(events: list[dict]) -> list[str]:
    messages: list[str] = []
    for event in events:
        message = format_message(event)
        if message:
            messages.append(message)
    return messages


def main() -> int:
    parser = argparse.ArgumentParser(description='Write Telegram-ready dry-run alert messages without sending them.')
    parser.add_argument('--input', type=Path, default=Path('data/candidate_events.jsonl'))
    parser.add_argument('--output', type=Path, default=Path('data/telegram_dry_run.txt'))
    args = parser.parse_args()

    try:
        messages = build_messages(load_events(args.input))
    except ValueError as exc:
        print(f'invalid dry-run input: {exc}', file=sys.stderr)
        return 2
    try:
        atomic_write_text('\n\n---\n\n'.join(messages) + ('\n' if messages else ''), args.output)
    except OSError as exc:
        print(f'failed to write dry-run messages: {exc}', file=sys.stderr)
        return 2
    print(f'wrote {len(messages)} dry-run messages to {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
