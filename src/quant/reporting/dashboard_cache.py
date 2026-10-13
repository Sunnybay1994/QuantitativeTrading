"""Serialize expensive snapshots while other HTTP routes remain available."""
import datetime as dt
import threading
import time


class SnapshotCache:
    def __init__(self, reader, ttl: float = 15):
        self.reader, self.ttl = reader, ttl
        self.lock = threading.Lock()
        self.at = 0.
        self.payload = None
        self.saved_at = None
        self.invalidated = False
        self.generation = 0

    def invalidate(self):
        with self.lock:
            self.invalidated = True

    def get(self, *, force=False):
        # Capture before the lock so concurrent force callers share one refresh.
        requested_gen = self.generation
        requested = time.monotonic()
        with self.lock:
            error = None
            if (
                self.payload is None
                or self.invalidated
                or requested - self.at > self.ttl
                or (force and self.generation == requested_gen)
            ):
                try:
                    payload = self.reader()
                except Exception as exc:
                    if self.payload is None:
                        raise
                    error = type(exc).__name__
                    self.generation += 1
                else:
                    self.invalidated = False
                    self.payload = payload
                    self.at = time.monotonic()
                    self.saved_at = dt.datetime.now().isoformat()
                    self.generation += 1
            return {**self.payload, 'cache': {'saved_at': self.saved_at,
                'age_seconds': round(max(0., time.monotonic()-self.at), 1),
                'stale': error is not None, 'refresh_error': error}}
