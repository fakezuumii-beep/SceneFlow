"""Durable JSON saves with bounded retries for Windows reader/scanner locks."""
import json
import os
from pathlib import Path
import tempfile
import time

REPLACE_ATTEMPTS = 20


def atomic_json(path, value):
    path = Path(path)
    # Serialize first: invalid input must not leave a partial recovery file.
    payload = json.dumps(value, ensure_ascii=False, indent=2)
    temp = None
    preserve = False
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=path.parent, prefix=path.name+'.',
                                         suffix='.tmp', delete=False) as stream:
            temp = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                os.replace(temp, path)
                return
            except OSError as exc:
                transient = isinstance(exc, PermissionError) or getattr(exc, 'winerror', None) in (5, 32, 33)
                if transient and attempt + 1 < REPLACE_ATTEMPTS:
                    time.sleep(min(.025 * (attempt + 1), .2))
                    continue
                # Never delete/truncate the old destination or claim a failed save succeeded.
                preserve = True
                raise RuntimeError(f'无法保存 {path.name}；文件可能被占用或不可写。'
                                   f'原文件未替换，待保存副本已保留：{temp}。请解除占用后重试。') from exc
    finally:
        if temp is not None and not preserve:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
