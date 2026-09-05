"""Best-effort progress snapshots; readers must only see complete JSON."""
import json
import os
from pathlib import Path
import tempfile
import time


def atomic_json(path, value):
    path = Path(path)
    temp = None
    try:
        # A unique sibling avoids collisions and keeps replacement atomic.
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=path.parent, prefix=path.name+'.',
                                         suffix='.tmp', delete=False) as stream:
            temp = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False)
        for attempt in range(6):
            try:
                os.replace(temp, path)
                return True
            except PermissionError:
                if attempt == 5:
                    return False  # A locked progress display must not abort inference.
                time.sleep(.02 * (attempt + 1))
    except PermissionError:
        return False
    finally:
        if temp is not None:
            try:
                temp.unlink(missing_ok=True)
            except PermissionError:
                pass
