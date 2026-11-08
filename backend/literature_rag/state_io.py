"""Bounded retries for local checkpoints; never replay a model request."""
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path


def log_error(path, context):
    text = f"\n{datetime.now(timezone.utc).isoformat()} {context}\n{traceback.format_exc()}"
    try:
        with Path(path).open('a', encoding='utf8') as stream:
            stream.write(text)
    except OSError:
        # Parent captures stderr even if the diagnostic file itself is locked.
        sys.stderr.write(text)


def save_state(path, payload):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    for attempt in range(6):
        try:
            temporary.write_text(serialized, encoding='utf8')
            temporary.replace(path)
            return
        except OSError as error:
            transient = isinstance(error, PermissionError) or getattr(error, 'winerror', None) in (32, 33)
            log_error(path.parent / 'state-errors.log', f'checkpoint attempt={attempt + 1} transient={transient}')
            if not transient or attempt == 5:
                raise
            time.sleep(0.05 * 2 ** attempt)
