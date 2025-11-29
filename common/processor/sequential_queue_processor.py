# self_monitoring_queue_processor.py
import queue
import threading
import time
import logging
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass
from enum import Enum


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    STOPPED = "stopped"


@dataclass
class HealthMetrics:
    """Comprehensive health metrics for monitoring"""
    queue_size: int
    max_queue_size: int
    queue_utilization: float
    events_processed: int
    events_dropped: int
    avg_processing_time_ms: float
    health_status: HealthStatus
    last_processed_time: float
    worker_thread_alive: bool
    consecutive_empty_cycles: int


class SelfMonitoringQueueProcessor:
    """
    A sequential queue processor with built-in health monitoring.
    Guarantees event ordering and provides comprehensive health metrics.
    """

    def __init__(self, name: str, max_queue_size: int = 10000):
        self.name = name
        self._event_queue = queue.Queue(maxsize=max_queue_size)
        self._processing_thread: Optional[threading.Thread] = None
        self._monitoring_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Event handling
        self._event_handlers: Dict[type, List[Callable]] = {}
        self._lock = threading.Lock()

        # Health monitoring state
        self._metrics = {
            'events_processed': 0,
            'events_dropped': 0,
            'total_processing_time': 0.0,
            'last_processed_time': 0.0,
            'consecutive_empty_cycles': 0,
            'last_health_check': time.time(),
            'last_health_log': 0.0
        }

        # Health configuration
        self.health_config = {
            'max_queue_utilization': 0.8,  # 80% full
            'critical_queue_utilization': 0.95,  # 95% full
            'max_processing_time_ms': 100.0,  # 100ms avg processing time
            'max_consecutive_empty_cycles': 10,  # 10 seconds without events
            'health_check_interval_sec': 5.0,  # Check health every 5 seconds
            'stuck_threshold_sec': 30.0,  # Stuck if no processing for 30s
            'health_log_interval_healthy_sec': 300,  # Log every 5 min when healthy
            'health_log_interval_unhealthy_sec': 30  # Log every 30s when unhealthy
        }

        self._current_health = HealthStatus.STOPPED
        self._last_logged_health = HealthStatus.STOPPED

    def register_handler(self, event_type: type, handler: Callable[[Any], None]):
        """Register a handler for specific event types"""
        with self._lock:
            if event_type not in self._event_handlers:
                self._event_handlers[event_type] = []
            self._event_handlers[event_type].append(handler)
        logging.info(f"{self.name} Registered handler for {event_type.__name__}")

    def unregister_handler(self, event_type: type, handler: Callable[[Any], None]):
        """Unregister a handler for specific event types"""
        with self._lock:
            if event_type in self._event_handlers:
                if handler in self._event_handlers[event_type]:
                    self._event_handlers[event_type].remove(handler)
                    logging.info(f"{self.name} Unregistered handler for {event_type.__name__}")

    def start(self):
        """Start the sequential processing and monitoring threads"""
        if self._processing_thread is not None:
            logging.warning(f"{self.name} processor already started")
            return

        self._stop_event.clear()

        # Start processing thread
        self._processing_thread = threading.Thread(
            target=self._process_events_worker,
            name=f"{self.name}-Processor",
            daemon=True
        )

        # Start monitoring thread
        self._monitoring_thread = threading.Thread(
            target=self._monitoring_worker,
            name=f"{self.name}-Monitor",
            daemon=True
        )

        self._processing_thread.start()
        self._monitoring_thread.start()
        self._current_health = HealthStatus.HEALTHY
        self._last_logged_health = HealthStatus.HEALTHY
        logging.info(f"{self.name} sequential event processor started with max_queue_size={self._event_queue.maxsize}")

    def stop(self):
        """Stop the processor gracefully"""
        self._stop_event.set()
        self._current_health = HealthStatus.STOPPED

        if self._processing_thread:
            self._processing_thread.join(timeout=5.0)
            if self._processing_thread.is_alive():
                logging.warning(f"{self.name} Processing thread did not stop gracefully")
            self._processing_thread = None

        if self._monitoring_thread:
            self._monitoring_thread.join(timeout=5.0)
            if self._monitoring_thread.is_alive():
                logging.warning(f"{self.name} Monitoring thread did not stop gracefully")
            self._monitoring_thread = None

        logging.info(f"{self.name} sequential event processor stopped")

    def submit(self, obj: Any) -> bool:
        """
        Submit an event to the queue with health-aware backpressure.
        Returns True if event was accepted, False if rejected due to health issues.
        """
        if not self.is_healthy():
            logging.warning(f"{self.name} rejecting event - processor not healthy")
            self._metrics['events_dropped'] += 1
            return False

        try:
            # Try quick submission first
            self._event_queue.put(obj, block=True, timeout=0.1)
            return True
        except queue.Full:
            # Queue is getting full - apply backpressure with warning
            self._metrics['events_dropped'] += 1
            logging.warning(f"{self.name} event queue full, applying backpressure")

            try:
                # Try with longer timeout
                self._event_queue.put(obj, block=True, timeout=5.0)
                return True
            except queue.Full:
                # Critical: queue persistently full
                self._metrics['events_dropped'] += 1
                logging.error(f"{self.name} CRITICAL: Event queue persistently full - blocking indefinitely")

                # Last resort - block indefinitely but update health status
                self._current_health = HealthStatus.CRITICAL
                self._event_queue.put(obj, block=True)
                return True

    def submit_nowait(self, obj: Any) -> bool:
        """
        Submit without blocking. Returns True if successful, False if queue is full.
        May drop events if queue is full.
        """
        try:
            self._event_queue.put_nowait(obj)
            return True
        except queue.Full:
            self._metrics['events_dropped'] += 1
            return False

    def _process_events_worker(self):
        """Worker thread that processes events sequentially in order"""
        logging.info(f"{self.name} event processor worker started")

        while not self._stop_event.is_set():
            try:
                # Get event with timeout to allow checking stop event
                obj = self._event_queue.get(timeout=1.0)

                # Process the event
                processing_start = time.time()
                self._handle_event(obj)
                processing_time = time.time() - processing_start

                # Update metrics
                with self._lock:
                    self._metrics['events_processed'] += 1
                    self._metrics['total_processing_time'] += processing_time
                    self._metrics['last_processed_time'] = time.time()
                    self._metrics['consecutive_empty_cycles'] = 0

                self._event_queue.task_done()

            except queue.Empty:
                with self._lock:
                    self._metrics['consecutive_empty_cycles'] += 1
                continue
            except Exception as e:
                logging.error(f"{self.name} Error processing event: {e}")
                with self._lock:
                    self._metrics['consecutive_empty_cycles'] += 1

    def _monitoring_worker(self):
        """Continuous health monitoring thread"""
        logging.info(f"{self.name} health monitor started")

        while not self._stop_event.is_set():
            try:
                self._check_health()
                self._log_health_status()
                time.sleep(self.health_config['health_check_interval_sec'])
            except Exception as e:
                logging.error(f"{self.name} Health monitoring error: {e}")

    def _check_health(self):
        """Perform comprehensive health check"""
        current_time = time.time()

        with self._lock:
            self._metrics['last_health_check'] = current_time

        # Check worker thread status
        worker_alive = (self._processing_thread is not None and
                        self._processing_thread.is_alive())

        if not worker_alive:
            self._current_health = HealthStatus.CRITICAL
            return

        # Check queue utilization
        queue_size = self._event_queue.qsize()
        max_size = self._event_queue.maxsize
        queue_utilization = queue_size / max_size if max_size > 0 else 0

        # Check if processor is stuck (queue not empty but no processing)
        time_since_last_processed = current_time - self._metrics['last_processed_time']
        is_stuck = (time_since_last_processed > self.health_config['stuck_threshold_sec'] and
                    queue_size > 0)

        # Check processing performance
        avg_processing_time_ms = 0
        if self._metrics['events_processed'] > 0:
            avg_processing_time_ms = (self._metrics['total_processing_time'] /
                                      self._metrics['events_processed'] * 1000)

        # Determine health status
        new_health = HealthStatus.HEALTHY

        if queue_utilization > self.health_config['critical_queue_utilization'] or is_stuck:
            new_health = HealthStatus.CRITICAL
        elif (queue_utilization > self.health_config['max_queue_utilization'] or
              avg_processing_time_ms > self.health_config['max_processing_time_ms']):
            new_health = HealthStatus.DEGRADED

        # Update health status
        if new_health != self._current_health:
            old_health = self._current_health
            self._current_health = new_health

            # Log health state changes
            if new_health == HealthStatus.CRITICAL:
                logging.error(f"{self.name} Health degraded to CRITICAL - "
                              f"queue_utilization={queue_utilization:.1%}, "
                              f"stuck={is_stuck}, avg_processing_time={avg_processing_time_ms:.1f}ms")
            elif new_health == HealthStatus.DEGRADED:
                logging.warning(f"{self.name} Health degraded to DEGRADED - "
                                f"queue_utilization={queue_utilization:.1%}, "
                                f"avg_processing_time={avg_processing_time_ms:.1f}ms")
            elif new_health == HealthStatus.HEALTHY and old_health != HealthStatus.HEALTHY:
                logging.info(f"{self.name} Health recovered to HEALTHY")

    def _log_health_status(self):
        """Log health status periodically based on current health"""
        current_time = time.time()

        # Determine log interval based on health status
        if self._current_health == HealthStatus.HEALTHY:
            log_interval = self.health_config['health_log_interval_healthy_sec']
        else:
            log_interval = self.health_config['health_log_interval_unhealthy_sec']

        # Check if it's time to log
        if current_time - self._metrics['last_health_log'] >= log_interval:
            metrics = self.get_health_metrics()

            if self._current_health == HealthStatus.HEALTHY:
                logging.info(f"{self.name} Health status: {metrics}")
            elif self._current_health == HealthStatus.DEGRADED:
                logging.warning(f"{self.name} Health status: {metrics}")
            else:  # CRITICAL
                logging.error(f"{self.name} Health status: {metrics}")

            with self._lock:
                self._metrics['last_health_log'] = current_time

    def _handle_event(self, obj: Any):
        """Handle event by calling registered handlers"""
        event_type = type(obj)

        # Get handlers safely
        with self._lock:
            handlers = self._event_handlers.get(event_type, [])[:]  # Copy to avoid lock during execution

        if not handlers:
            logging.warning(f"{self.name} No handlers registered for event type: {event_type.__name__}")
            return

        for handler in handlers:
            try:
                handler(obj)
            except Exception as e:
                logging.error(f"{self.name} Handler error for {event_type.__name__}: {e}")

    # Public health interface
    def is_healthy(self) -> bool:
        """Quick health check for external callers"""
        return self._current_health == HealthStatus.HEALTHY

    def get_health_status(self) -> HealthStatus:
        """Get detailed health status"""
        return self._current_health

    def get_health_metrics(self) -> HealthMetrics:
        """Get comprehensive health metrics for monitoring"""
        queue_size = self._event_queue.qsize()
        max_size = self._event_queue.maxsize
        queue_utilization = queue_size / max_size if max_size > 0 else 0

        with self._lock:
            avg_processing_time_ms = 0
            if self._metrics['events_processed'] > 0:
                avg_processing_time_ms = (self._metrics['total_processing_time'] /
                                          self._metrics['events_processed'] * 1000)

            metrics = HealthMetrics(
                queue_size=queue_size,
                max_queue_size=max_size,
                queue_utilization=queue_utilization,
                events_processed=self._metrics['events_processed'],
                events_dropped=self._metrics['events_dropped'],
                avg_processing_time_ms=avg_processing_time_ms,
                health_status=self._current_health,
                last_processed_time=self._metrics['last_processed_time'],
                worker_thread_alive=(self._processing_thread is not None and
                                     self._processing_thread.is_alive()),
                consecutive_empty_cycles=self._metrics['consecutive_empty_cycles']
            )

        return metrics

    def get_queue_size(self) -> int:
        """Get current queue size"""
        return self._event_queue.qsize()

    def get_queue_utilization(self) -> float:
        """Get current queue utilization (0.0 to 1.0)"""
        queue_size = self._event_queue.qsize()
        max_size = self._event_queue.maxsize
        return queue_size / max_size if max_size > 0 else 0.0

    # Configuration methods
    def update_health_config(self, **kwargs):
        """Update health monitoring configuration"""
        valid_keys = set(self.health_config.keys())
        for key, value in kwargs.items():
            if key in valid_keys:
                self.health_config[key] = value
            else:
                logging.warning(f"{self.name} Ignoring invalid health config key: {key}")

        logging.info(f"{self.name} Updated health config: {kwargs}")

    # Utility methods
    def wait_until_empty(self, timeout: Optional[float] = None) -> bool:
        """
        Wait until all events in the queue are processed.
        Returns True if queue emptied, False if timeout.
        """
        return self._event_queue.join() if timeout is None else self._event_queue.join(timeout=timeout)

    def clear_queue(self):
        """Clear all events from the queue (use with caution!)"""
        try:
            while True:
                self._event_queue.get_nowait()
                self._event_queue.task_done()
        except queue.Empty:
            pass
        logging.warning(f"{self.name} Queue cleared")

    def __enter__(self):
        """Context manager support"""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager support"""
        self.stop()