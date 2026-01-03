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
    last_health_transition_time: float


class SelfMonitoringQueueProcessor:
    """
    A sequential queue processor with built-in health monitoring and auto-recovery.
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
            'last_health_log': 0.0,
            'last_health_transition_time': time.time(),
            'recovery_attempts': 0,
            'last_recovery_time': 0.0
        }

        # Health configuration with recovery parameters
        self.health_config = {
            'max_queue_utilization': 0.8,  # 80% full
            'critical_queue_utilization': 0.95,  # 95% full
            'max_processing_time_ms': 100.0,  # 100ms avg processing time
            'max_consecutive_empty_cycles': 10,  # 10 seconds without events
            'health_check_interval_sec': 5.0,  # Check health every 5 seconds
            'stuck_threshold_sec': 30.0,  # Stuck if no processing for 30s
            'health_log_interval_healthy_sec': 300,  # Log every 5 min when healthy
            'health_log_interval_unhealthy_sec': 30,  # Log every 30s when unhealthy

            # Auto-recovery configuration
            'recovery_check_interval_sec': 10.0,  # Check recovery every 10 seconds
            'min_time_in_state_sec': 15.0,  # Minimum time to stay in a state before auto-recovery
            'max_recovery_attempts': 3,  # Max recovery attempts before waiting
            'recovery_cooldown_sec': 60.0,  # Cooldown after max recovery attempts
            'auto_reset_metrics_on_recovery': True,  # Reset metrics when recovering from critical
            'dynamic_threshold_adjustment': True,  # Auto-adjust thresholds based on load
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
        # Don't reject just because processing is slow
        # Only reject if queue is critically full
        if self._current_health == HealthStatus.CRITICAL:
            # Check if CRITICAL is actually due to queue being full
            queue_utilization = self.get_queue_utilization()
            if queue_utilization >= self.health_config['critical_queue_utilization']:
                logging.warning(f"{self.name} rejecting event - queue critically full")
                self._metrics['events_dropped'] += 1
                return False
            # If CRITICAL due to other reasons (stuck), still accept

        try:
            # Try with longer timeout
            self._event_queue.put(obj, block=True, timeout=1.0)
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

                self._event_queue.task_done()

            except queue.Empty:
                with self._lock:
                    self._metrics['consecutive_empty_cycles'] += 1
                continue
            except Exception as e:
                logging.error(f"{self.name} Error processing event: {e}",exc_info=e)
                with self._lock:
                    self._metrics['consecutive_empty_cycles'] += 1

    def _monitoring_worker(self):
        """Continuous health monitoring and auto-recovery thread"""
        logging.info(f"{self.name} health monitor started")

        last_recovery_check = time.time()

        while not self._stop_event.is_set():
            try:
                # Perform health check
                self._check_health()

                # Perform auto-recovery check
                current_time = time.time()
                if current_time - last_recovery_check >= self.health_config['recovery_check_interval_sec']:
                    self._attempt_auto_recovery()
                    last_recovery_check = current_time

                # Log health status
                self._log_health_status()

                # Sleep for next check
                time.sleep(self.health_config['health_check_interval_sec'])
            except Exception as e:
                logging.error(f"{self.name} Health monitoring error: {e}")

    def _check_health(self):
        """Perform comprehensive health check with proper state transitions"""
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

        # Dynamically adjust thresholds based on load if enabled
        if self.health_config['dynamic_threshold_adjustment']:
            self._adjust_thresholds_based_on_load(avg_processing_time_ms, queue_utilization)

        # Determine new health status based on current metrics
        # Check CRITICAL conditions first
        if (queue_utilization > self.health_config['critical_queue_utilization'] or
                is_stuck):
            new_health = HealthStatus.CRITICAL
        # Check DEGRADED conditions
        elif (queue_utilization > self.health_config['max_queue_utilization'] or
              avg_processing_time_ms > self.health_config['max_processing_time_ms']):
            new_health = HealthStatus.DEGRADED
        # All conditions are healthy
        else:
            new_health = HealthStatus.HEALTHY

        # Update health status with hysteresis to prevent flapping
        # Only transition to HEALTHY if we're not currently CRITICAL and all conditions are met
        if self._current_health == HealthStatus.CRITICAL:
            # To recover from CRITICAL, we need to pass through DEGRADED first
            if (new_health == HealthStatus.HEALTHY and
                    not is_stuck and
                    queue_utilization <= self.health_config['max_queue_utilization']):
                new_health = HealthStatus.DEGRADED  # Recover to DEGRADED first
            elif new_health == HealthStatus.DEGRADED:
                # Stay in DEGRADED until all conditions are healthy
                pass

        # Update health status with proper logging
        if new_health != self._current_health:
            old_health = self._current_health
            self._current_health = new_health
            with self._lock:
                self._metrics['last_health_transition_time'] = current_time
                self._metrics['recovery_attempts'] = 0  # Reset recovery attempts on state change

            # Log health state changes
            if new_health == HealthStatus.CRITICAL:
                logging.error(f"{self.name} Health degraded to CRITICAL - "
                              f"queue_utilization={queue_utilization:.1%}, "
                              f"stuck={is_stuck}, avg_processing_time={avg_processing_time_ms:.1f}ms")
            elif new_health == HealthStatus.DEGRADED:
                if old_health == HealthStatus.CRITICAL:
                    logging.info(f"{self.name} Health improved from CRITICAL to DEGRADED")
                else:
                    logging.warning(f"{self.name} Health degraded to DEGRADED - "
                                    f"queue_utilization={queue_utilization:.1%}, "
                                    f"avg_processing_time={avg_processing_time_ms:.1f}ms")
            elif new_health == HealthStatus.HEALTHY:
                logging.info(f"{self.name} Health recovered to HEALTHY - "
                             f"queue_utilization={queue_utilization:.1%}, "
                             f"avg_processing_time={avg_processing_time_ms:.1f}ms")

    def _attempt_auto_recovery(self):
        """Attempt to auto-recover from degraded or critical states"""
        if self._current_health == HealthStatus.HEALTHY:
            return  # No recovery needed

        current_time = time.time()

        # Check if we've been in this state long enough
        time_in_state = current_time - self._metrics['last_health_transition_time']
        if time_in_state < self.health_config['min_time_in_state_sec']:
            return  # Not enough time in state

        # Check recovery cooldown
        if (self._metrics['recovery_attempts'] >= self.health_config['max_recovery_attempts'] and
                current_time - self._metrics['last_recovery_time'] < self.health_config['recovery_cooldown_sec']):
            logging.info(f"{self.name} Recovery cooldown active, skipping recovery attempt")
            return

        # Check current conditions to see if recovery is possible
        queue_size = self._event_queue.qsize()
        max_size = self._event_queue.maxsize
        queue_utilization = queue_size / max_size if max_size > 0 else 0

        time_since_last_processed = current_time - self._metrics['last_processed_time']
        is_stuck = (time_since_last_processed > self.health_config['stuck_threshold_sec'] and
                    queue_size > 0)

        # Calculate average processing time
        avg_processing_time_ms = 0
        if self._metrics['events_processed'] > 0:
            avg_processing_time_ms = (self._metrics['total_processing_time'] /
                                      self._metrics['events_processed'] * 1000)

        # Determine target health based on current conditions
        target_health = HealthStatus.HEALTHY
        if (queue_utilization > self.health_config['critical_queue_utilization'] or
                is_stuck):
            target_health = HealthStatus.CRITICAL
        elif (queue_utilization > self.health_config['max_queue_utilization'] or
              avg_processing_time_ms > self.health_config['max_processing_time_ms']):
            target_health = HealthStatus.DEGRADED

        # If target health is better than current health, try to recover
        if self._health_status_value(target_health) < self._health_status_value(self._current_health):
            self._perform_recovery_step(target_health, current_time)

    def _perform_recovery_step(self, target_health: HealthStatus, current_time: float):
        """Perform a recovery step towards target health"""
        old_health = self._current_health

        # Determine if we can transition directly or need intermediate steps
        if (old_health == HealthStatus.CRITICAL and
                target_health == HealthStatus.HEALTHY):
            # Need to go through DEGRADED first
            self._current_health = HealthStatus.DEGRADED
            logging.info(f"{self.name} Auto-recovery: CRITICAL → DEGRADED")
        else:
            # Can transition directly
            self._current_health = target_health
            logging.info(f"{self.name} Auto-recovery: {old_health.value} → {target_health.value}")

        with self._lock:
            self._metrics['last_health_transition_time'] = current_time
            self._metrics['recovery_attempts'] += 1
            self._metrics['last_recovery_time'] = current_time

        # Reset metrics if recovering from critical and configured to do so
        if (old_health == HealthStatus.CRITICAL and
                self.health_config['auto_reset_metrics_on_recovery']):
            self._reset_health_metrics()
            logging.info(f"{self.name} Metrics reset after critical recovery")

    def _health_status_value(self, status: HealthStatus) -> int:
        """Get numeric value for health status (lower is better)"""
        status_values = {
            HealthStatus.HEALTHY: 0,
            HealthStatus.DEGRADED: 1,
            HealthStatus.CRITICAL: 2,
            HealthStatus.STOPPED: 3
        }
        return status_values.get(status, 3)

    def _adjust_thresholds_based_on_load(self, avg_processing_time_ms: float, queue_utilization: float):
        """Dynamically adjust health thresholds based on current load"""
        current_time = time.time()

        # Only adjust every 30 seconds to avoid thrashing
        if hasattr(self, '_last_threshold_adjustment'):
            if current_time - self._last_threshold_adjustment < 30.0:
                return

        self._last_threshold_adjustment = current_time

        # Calculate load factor
        load_factor = min(3.0, max(0.5,
                                   (queue_utilization * 2.0 + avg_processing_time_ms / self.health_config[
                                       'max_processing_time_ms']) / 3.0))

        if load_factor > 1.8:  # Very high load
            # Be more lenient with thresholds
            self.health_config['max_queue_utilization'] = 0.9
            self.health_config['critical_queue_utilization'] = 0.98
            self.health_config['max_processing_time_ms'] = 200.0
            logging.debug(f"{self.name} Adjusted thresholds for high load (factor: {load_factor:.2f})")
        elif load_factor > 1.3:  # High load
            self.health_config['max_queue_utilization'] = 0.85
            self.health_config['critical_queue_utilization'] = 0.96
            self.health_config['max_processing_time_ms'] = 150.0
            logging.debug(f"{self.name} Adjusted thresholds for medium load (factor: {load_factor:.2f})")
        else:  # Normal or low load
            # Reset to defaults
            self.health_config['max_queue_utilization'] = 0.8
            self.health_config['critical_queue_utilization'] = 0.95
            self.health_config['max_processing_time_ms'] = 100.0

    def _reset_health_metrics(self):
        """Reset health metrics"""
        with self._lock:
            self._metrics['events_processed'] = 0
            self._metrics['events_dropped'] = 0
            self._metrics['total_processing_time'] = 0.0
            self._metrics['consecutive_empty_cycles'] = 0

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
        """Handle event with detailed timing"""
        event_type = type(obj).__name__
        processing_start = time.time()

        try:
            # Get handlers
            with self._lock:
                handlers = self._event_handlers.get(type(obj), [])[:]

            # Process with per-handler timing
            for i, handler in enumerate(handlers):
                handler_start = time.time()
                handler(obj)
                handler_time = time.time() - handler_start

                if handler_time > 0.05:  # Log handlers taking >50ms
                    handler_name = handler.__name__ if hasattr(handler, '__name__') else f'handler_{i}'
                    logging.debug(f"{self.name} Handler '{handler_name}' for {event_type} "
                                  f"took {handler_time * 1000:.1f}ms")

        except Exception as e:
            logging.error(f"{self.name} Error processing {event_type}: {e}",exc_info=e)

        finally:
            total_time = time.time() - processing_start

            # Update metrics
            with self._lock:
                self._metrics['events_processed'] += 1
                self._metrics['total_processing_time'] += total_time
                self._metrics['last_processed_time'] = time.time()
                self._metrics['consecutive_empty_cycles'] = 0

            # Log if this event was particularly slow
            if total_time > 0.1:  # >100ms
                logging.debug(f"{self.name} {event_type} processing took {total_time * 1000:.1f}ms")

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
                consecutive_empty_cycles=self._metrics['consecutive_empty_cycles'],
                last_health_transition_time=self._metrics['last_health_transition_time']
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

    # Enhanced recovery methods (for external use if needed, but auto-recovery is internal)
    def force_health_recovery(self):
        """
        Force health recovery check immediately.
        Use only when external intervention is absolutely necessary.
        """
        logging.info(f"{self.name} Forcing health recovery check")
        self._check_health()
        self._attempt_auto_recovery()

    def reset_metrics(self):
        """
        Reset health metrics.
        Use carefully as it will reset performance history.
        """
        with self._lock:
            self._metrics['events_processed'] = 0
            self._metrics['events_dropped'] = 0
            self._metrics['total_processing_time'] = 0.0
            self._metrics['consecutive_empty_cycles'] = 0
            self._metrics['recovery_attempts'] = 0
        logging.info(f"{self.name} Health metrics reset")

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


