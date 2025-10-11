import logging
import threading
from queue import Queue, Empty, Full
from contextlib import contextmanager

from common.recycle import Recyclable


class ObjectPool:
    def __init__(self, create_func, size=10):
        logging.info("Creating object pool with size {}".format(size))

        # Validate that create_func returns Recyclable objects
        test_obj = create_func()
        if not isinstance(test_obj, Recyclable):
            raise TypeError("create_func must return objects implementing Recyclable interface")

        self.create_func = create_func
        self.size = size
        self._pool = Queue(maxsize=size)
        self._lock = threading.Lock()
        self._active_count = 0

        # Pre-populate with some objects
        for _ in range(size):
            obj = create_func()
            if not isinstance(obj, Recyclable):
                raise TypeError("All pool objects must implement Recyclable interface")
            self._pool.put(obj)
            self._active_count += 1

    def acquire(self):
        """Acquire an object from the pool (thread-safe)"""
        try:
            # Try to get from pool first
            return self._pool.get_nowait()
        except Empty:
            # Create new object if pool is empty and we haven't reached max size
            with self._lock:
                if self._active_count < self.size:
                    obj = self.create_func()
                    if not isinstance(obj, Recyclable):
                        raise TypeError("Created object must implement Recyclable interface")
                    self._active_count += 1
                    return obj
                else:
                    # Wait for an object to become available
                    return self._pool.get()

    def release(self, obj):
        """Release an object back to the pool (thread-safe)"""
        # Call recycle method before returning to pool
        if isinstance(obj, Recyclable):
            try:
                obj.recycle()
            except Exception as e:
                logging.warning(f"Error calling recycle on object: {e}")
        else:
            logging.warning("Object does not implement Recyclable interface")

        try:
            self._pool.put_nowait(obj)
        except Full:
            # If pool is full, discard the object
            logging.debug("Pool is full, discarding object")

    @contextmanager
    def context(self):
        """Context manager for automatic acquire/release"""
        obj = self.acquire()
        try:
            yield obj
        finally:
            self.release(obj)

    def current_size(self):
        """Get current pool size"""
        return self._pool.qsize()

    def active_count(self):
        """Get total number of active objects created"""
        return self._active_count