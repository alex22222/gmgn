from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class LockAcquisitionError(RuntimeError):
    pass


def atomic_write_text(text: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            'w',
            delete=False,
            dir=output_path.parent,
            encoding='utf-8',
            prefix=f'.{output_path.name}.',
            suffix='.tmp',
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, output_path)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def atomic_write_jsonl(records: list[dict], output_path: Path) -> None:
    lines = [
        json.dumps(record, ensure_ascii=False, sort_keys=True)
        for record in records
    ]
    atomic_write_text('\n'.join(lines) + ('\n' if lines else ''), output_path)


def atomic_write_json(records: list[dict], output_path: Path) -> None:
    atomic_write_text(
        json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
        output_path,
    )


def durable_append_text(text: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('a', encoding='utf-8') as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def describe_lock(lock_path: Path, stale_after_seconds: int = 3600) -> dict[str, object]:
    try:
        age_seconds = max(0, int(time.time() - lock_path.stat().st_mtime))
    except FileNotFoundError:
        return {
            'age_seconds': None,
            'exists': False,
            'path': str(lock_path),
            'stale': False,
        }
    return {
        'age_seconds': age_seconds,
        'exists': True,
        'path': str(lock_path),
        'stale': _is_stale_lock(lock_path, stale_after_seconds),
    }


def describe_temp_artifacts(base_path: Path, stale_after_seconds: int = 3600) -> dict[str, object]:
    files = []
    if base_path.exists():
        for path in sorted(base_path.rglob('.*.tmp')):
            if not path.is_file():
                continue
            age_seconds = max(0, int(time.time() - path.stat().st_mtime))
            files.append({
                'age_seconds': age_seconds,
                'path': str(path),
                'stale': age_seconds > stale_after_seconds if stale_after_seconds > 0 else False,
            })
    return {
        'base_path': str(base_path),
        'count': len(files),
        'files': files,
        'stale_count': sum(1 for file in files if file['stale']),
    }


@contextmanager
def exclusive_file_lock(lock_path: Path, stale_after_seconds: int = 3600) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    acquired = False
    try:
        try:
            _create_lock(lock_path)
            acquired = True
        except FileExistsError:
            if _is_stale_lock(lock_path, stale_after_seconds):
                lock_path.unlink(missing_ok=True)
                _create_lock(lock_path)
                acquired = True
            else:
                raise LockAcquisitionError(f'lock already held: {lock_path}')
        yield
    finally:
        if acquired:
            lock_path.unlink(missing_ok=True)


def _create_lock(lock_path: Path) -> None:
    descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(f'pid={os.getpid()}\n')
            handle.write(f'created_at={time.time()}\n')
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        lock_path.unlink(missing_ok=True)
        raise


def _is_stale_lock(lock_path: Path, stale_after_seconds: int) -> bool:
    if stale_after_seconds <= 0:
        return False
    try:
        age_seconds = time.time() - lock_path.stat().st_mtime
    except FileNotFoundError:
        return True
    return age_seconds > stale_after_seconds
