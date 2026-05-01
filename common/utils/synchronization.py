import threading
import time

class SharedLock:
    """
    A lock that supports timeouts and can be released by any thread.
    Uses a Semaphore(1) under the hood to bypass thread-ownership restrictions.
    """

    def __init__(self, initially_locked=False):
        # We use BoundedSemaphore to prevent "over-releasing"
        self._lock = threading.BoundedSemaphore(1)
        if initially_locked:
            self._lock.acquire()  # Start at 0

    def acquire(self, timeout=None):
        # Returns True if acquired, False if timeout
        return self._lock.acquire(blocking=True, timeout=timeout)

    def release(self):
        try:
            self._lock.release()
        except ValueError:
            # Already released/unlocked
            pass

    def __enter__(self):
        """Context manager support (blocks indefinitely)"""
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()