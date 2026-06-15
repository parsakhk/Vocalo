"""
Tracks message counts per group in memory.
A spawn is triggered when MESSAGE_THRESHOLD messages arrive
within WINDOW_SECONDS seconds — then the counter resets.
"""
import time
from collections import defaultdict

# ── Tune these to control how often spawns happen ────────────────────────────
MESSAGE_THRESHOLD = 10   # messages needed to trigger a spawn
WINDOW_SECONDS    = 60   # rolling window in seconds
# ─────────────────────────────────────────────────────────────────────────────

# { group_id: [timestamp, timestamp, ...] }
_message_log: dict[int, list[float]] = defaultdict(list)


def record_message(group_id: int) -> bool:
    """
    Call this on every group message.
    Returns True if the spawn threshold has been reached (and resets the counter).
    """
    now = time.time()
    cutoff = now - WINDOW_SECONDS

    # Drop messages older than the window
    _message_log[group_id] = [t for t in _message_log[group_id] if t > cutoff]
    _message_log[group_id].append(now)

    if len(_message_log[group_id]) >= MESSAGE_THRESHOLD:
        _message_log[group_id].clear()   # reset so we don't spam spawns
        return True

    return False