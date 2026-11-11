"""Building blocks shared by the background job runners (web API and desktop GUI).

They are deliberately free of any web or UI framework: a job's status is a
plain string, its logs a list of lines and its worker threads a set of ids.
"""

import logging

PENDING = "pending"
RUNNING = "running"
CANCELLING = "cancelling"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"

ACTIVE_STATUSES = (PENDING, RUNNING, CANCELLING)
TERMINAL_STATUSES = (COMPLETED, FAILED, CANCELLED)


def transition_allowed(current: str | None, new: str) -> bool:
    """Return True if a job may move from ``current`` to ``new``.

    Terminal states are never left, and a job that is cancelling never goes
    back to pending or running.
    """
    if current in TERMINAL_STATUSES:
        return False
    if current == CANCELLING and new in (PENDING, RUNNING):
        return False
    return True


class LogLinesHandler(logging.Handler):
    """Append formatted log records to a list, keeping only the last lines."""

    def __init__(self, lines: list[str], max_lines: int = 500):
        """Write into ``lines`` (mutated in place), capped at ``max_lines``."""
        super().__init__()
        self.lines = lines
        self.max_lines = max_lines

    def emit(self, record: logging.LogRecord) -> None:
        """Format ``record`` and append it, trimming the oldest lines."""
        try:
            self.lines.append(self.format(record))
            # Trim in place so readers holding the list keep seeing updates.
            if len(self.lines) > self.max_lines:
                del self.lines[: len(self.lines) - self.max_lines]
        except Exception:
            self.handleError(record)


class WorkerThreadFilter(logging.Filter):
    """Keep only log records emitted by a job's worker threads.

    Worker threads register their id in ``thread_ids``. Threads spawned by the
    pipeline itself (``Worker-<api>`` collector threads, ``ThreadPoolExecutor``
    pools, default ``Thread-N`` names) cannot be traced to a job: they are
    accepted when ``accept_anonymous()`` says so (default: always, which is
    right while a single job runs; the desktop runner, which runs several,
    gives them to one job only).
    """

    PIPELINE_THREAD_PREFIXES = ("Thread-", "Worker-", "ThreadPoolExecutor-")

    def __init__(self, thread_ids: set[int], accept_anonymous=None):
        """Accept records from the threads whose ids are in ``thread_ids``."""
        super().__init__()
        self.thread_ids = thread_ids
        self.accept_anonymous = accept_anonymous

    def filter(self, record: logging.LogRecord) -> bool:
        """Return True if ``record`` comes from one of the job's threads."""
        if record.thread in self.thread_ids:
            return True
        if not (record.threadName or "").startswith(self.PIPELINE_THREAD_PREFIXES):
            return False
        return self.accept_anonymous is None or bool(self.accept_anonymous())
