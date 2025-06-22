import logging
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets
import sys
import datetime
import threading
import time
import random
from collections import deque

class RealTimePlot:
    def __init__(self, ticker_name="TICKER", max_minutes=60, max_ticks=None, update_interval_ms=100, is_simulation=True):
        self.app = QtWidgets.QApplication(sys.argv)

        # Window setup
        self.win = QtWidgets.QWidget()
        self.win.setWindowTitle(f"Real-Time Tick Plot - {ticker_name}")
        self.layout = QtWidgets.QVBoxLayout()
        self.win.setLayout(self.layout)

        self.ticker_label = QtWidgets.QLabel(ticker_name)
        font = self.ticker_label.font()
        font.setPointSize(16)
        font.setBold(True)
        self.ticker_label.setFont(font)
        self.layout.addWidget(self.ticker_label)

        self.content_widget = QtWidgets.QWidget()
        self.content_layout = QtWidgets.QHBoxLayout()
        self.content_widget.setLayout(self.content_layout)
        self.layout.addWidget(self.content_widget, stretch=1)

        self.plot_widget = pg.PlotWidget(title="Tick Price vs Time")
        self.plot_widget.setLabel('left', 'Price')
        self.plot_widget.setLabel('bottom', 'Time')
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_widget.setAxisItems({'bottom': pg.graphicsItems.DateAxisItem.DateAxisItem()})
        self.legend = self.plot_widget.addLegend(offset=(10, 10))
        self.legend.setBrush(pg.mkBrush((30, 30, 30, 180)))

        self.price_curve = self.plot_widget.plot(pen='y', name="Price")
        self.sma_curve = self.plot_widget.plot(pen=pg.mkPen('c', width=2), name="SMA")
        self.sma2_curve = self.plot_widget.plot(pen=pg.mkPen('m', width=2), name="SMA2")  # New SMA2 line
        self.signal_scatter = pg.ScatterPlotItem(size=15, brush='g', symbol='t1', pen='w', name="Signals")
        self.plot_widget.addItem(self.signal_scatter)
        self.content_layout.addWidget(self.plot_widget, stretch=4)

        self.info_panel = QtWidgets.QWidget()
        self.info_layout = QtWidgets.QFormLayout()
        self.info_panel.setLayout(self.info_layout)
        self.content_layout.addWidget(self.info_panel, stretch=1)

        self.realized_pnl_label = QtWidgets.QLabel("0.00")
        self.capital_label = QtWidgets.QLabel("0.00")
        self.unrealized_pnl_label = QtWidgets.QLabel("0.00")
        self.margin_ratio_label = QtWidgets.QLabel("0.00%")
        self.daily_sharpe_label = QtWidgets.QLabel("0.00")
        self.signal_text_label = QtWidgets.QLabel("No signals")

        self.info_layout.addRow("Realized PnL:", self.realized_pnl_label)
        self.info_layout.addRow("Capital:", self.capital_label)
        self.info_layout.addRow("Unrealized PnL:", self.unrealized_pnl_label)
        self.info_layout.addRow("Margin Ratio:", self.margin_ratio_label)
        self.info_layout.addRow("Daily Sharpe:", self.daily_sharpe_label)
        self.info_layout.addRow("Latest Signal:", self.signal_text_label)

        # Data containers
        self.timestamps = deque()
        self.prices = deque()

        self.sma_timestamps = deque()
        self.sma_values = deque()
        self.sma_buffer = deque()

        self.sma2_timestamps = deque()  # For SMA2
        self.sma2_values = deque()
        self.sma2_buffer = deque()

        self.signals = deque()

        self.max_minutes = max_minutes
        self.max_seconds = max_minutes * 60 if max_minutes else None
        self.max_ticks = max_ticks

        self.tick_buffer = deque()
        self.signal_buffer = deque()

        self.lock = threading.Lock()

        self._realized_pnl = 0.0
        self._capital = 0.0
        self._unrealized_pnl = 0.0
        self._margin_ratio = 0.0
        self._daily_sharpe = 0.0

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_all)
        self.timer.start(update_interval_ms)
        self.is_started = False

        if is_simulation:
            threading.Thread(target=self._simulate_ticks, daemon=True).start()
            threading.Thread(target=self._simulate_metrics, daemon=True).start()
            threading.Thread(target=self._simulate_signals, daemon=True).start()
            threading.Thread(target=self._simulate_daily_sharpe, daemon=True).start()
            threading.Thread(target=self._simulate_external_sma, daemon=True).start()
            threading.Thread(target=self._simulate_external_sma2, daemon=True).start()  # Simulate SMA2

    # --- Simulated Data ---
    def _simulate_ticks(self):
        while True:
            price = 100 + random.uniform(-0.5, 0.5)
            timestamp = datetime.datetime.now()
            self.add_tick(timestamp, price)
            time.sleep(0.1)

    def _simulate_metrics(self):
        realized_pnl = 0.0
        capital = 10000.0
        unrealized_pnl = 0.0
        margin_ratio = 0.0
        while True:
            realized_pnl += random.uniform(-5, 5)
            unrealized_pnl += random.uniform(-3, 3)
            capital += realized_pnl * 0.01
            margin_ratio = max(0, min(100, margin_ratio + random.uniform(-0.5, 0.5)))
            self.add_realized_pnl(realized_pnl)
            self.add_capital(capital)
            self.add_unrealized_pnl(unrealized_pnl)
            self.add_margin_ratio(margin_ratio)
            time.sleep(0.5)

    def _simulate_signals(self):
        signals = [1, -1]
        while True:
            signal = random.choice(signals)
            price = 100 + random.uniform(-0.5, 0.5)
            timestamp = datetime.datetime.now()
            self.add_signal(timestamp, signal,price)
            time.sleep(3)

    def _simulate_daily_sharpe(self):
        sharpe = 0.0
        while True:
            sharpe += random.uniform(-0.1, 0.1)
            sharpe = max(-5, min(5, sharpe))
            self.add_daily_sharpe(sharpe)
            time.sleep(1)

    # Simulated external SMA feed (just for demo)
    def _simulate_external_sma(self):
        sma_val = 100.0
        while True:
            sma_val += random.uniform(-0.2, 0.2)
            timestamp = datetime.datetime.now()
            self.add_sma_point(timestamp, sma_val)
            time.sleep(0.1)

    # Simulated external SMA2 feed (just for demo)
    def _simulate_external_sma2(self):
        sma2_val = 100.0
        while True:
            sma2_val += random.uniform(-0.3, 0.3)
            timestamp = datetime.datetime.now()
            self.add_sma2_point(timestamp, sma2_val)
            time.sleep(0.1)

    # --- Data ingestion methods ---
    def add_tick(self, timestamp: datetime.datetime, price: float):
        with self.lock:
            self.tick_buffer.append((timestamp.timestamp(), price))

    def add_sma_point(self, timestamp: datetime.datetime, sma: float):
        with self.lock:
            self.sma_buffer.append((timestamp.timestamp(), sma))

    def add_sma2_point(self, timestamp: datetime.datetime, sma2: float):
        with self.lock:
            self.sma2_buffer.append((timestamp.timestamp(), sma2))

    def add_signal(self, timestamp: datetime.datetime,signal_value: int, price: float):
        if signal_value not in (1, -1):
            return
        with self.lock:
            self.signal_buffer.append((timestamp.timestamp(), price, signal_value))

    def add_realized_pnl(self, value: float): self._realized_pnl = value
    def add_capital(self, value: float): self._capital = value
    def add_unrealized_pnl(self, value: float): self._unrealized_pnl = value
    def add_margin_ratio(self, value: float): self._margin_ratio = value
    def add_daily_sharpe(self, value: float): self._daily_sharpe = value

    # --- GUI update ---
    def update_all(self):
        now = time.time()
        with self.lock:
            # Process tick buffer
            while self.tick_buffer:
                ts, price = self.tick_buffer.popleft()
                self.timestamps.append(ts)
                self.prices.append(price)

            # Process SMA buffer
            while self.sma_buffer:
                ts, sma = self.sma_buffer.popleft()
                self.sma_timestamps.append(ts)
                self.sma_values.append(sma)

            # Process SMA2 buffer
            while self.sma2_buffer:
                ts, sma2 = self.sma2_buffer.popleft()
                self.sma2_timestamps.append(ts)
                self.sma2_values.append(sma2)

            # Maintain window size for ticks
            if self.max_ticks:
                while len(self.timestamps) > self.max_ticks:
                    self.timestamps.popleft()
                    self.prices.popleft()
                while len(self.sma_timestamps) > self.max_ticks:
                    self.sma_timestamps.popleft()
                    self.sma_values.popleft()
                while len(self.sma2_timestamps) > self.max_ticks:
                    self.sma2_timestamps.popleft()
                    self.sma2_values.popleft()
            elif self.max_seconds:
                while self.timestamps and now - self.timestamps[0] > self.max_seconds:
                    self.timestamps.popleft()
                    self.prices.popleft()
                while self.sma_timestamps and now - self.sma_timestamps[0] > self.max_seconds:
                    self.sma_timestamps.popleft()
                    self.sma_values.popleft()
                while self.sma2_timestamps and now - self.sma2_timestamps[0] > self.max_seconds:
                    self.sma2_timestamps.popleft()
                    self.sma2_values.popleft()

            # Update price curve
            if self.timestamps:
                self.price_curve.setData(list(self.timestamps), list(self.prices))

            # Update SMA curve
            if self.sma_timestamps and self.sma_values:
                self.sma_curve.setData(list(self.sma_timestamps), list(self.sma_values))

            # Update SMA2 curve
            if self.sma2_timestamps and self.sma2_values:
                self.sma2_curve.setData(list(self.sma2_timestamps), list(self.sma2_values))

            # Update metrics labels
            self.realized_pnl_label.setText(f"{self._realized_pnl:.6f}")
            self.realized_pnl_label.setStyleSheet("color: green;" if self._realized_pnl >= 0 else "color: red;")

            self.unrealized_pnl_label.setText(f"{self._unrealized_pnl:.6f}")
            self.unrealized_pnl_label.setStyleSheet("color: green;" if self._unrealized_pnl >= 0 else "color: red;")

            self.capital_label.setText(f"{self._capital:.6f}")

            self.margin_ratio_label.setText(f"{self._margin_ratio:.6f}")
            self.margin_ratio_label.setStyleSheet("color: green;" if self._margin_ratio >= 0 else "color: red;")

            self.daily_sharpe_label.setText(f"{self._daily_sharpe:.6f}")
            self.daily_sharpe_label.setStyleSheet("color: green;" if self._daily_sharpe >= 0 else "color: red;")

            # Process signals
            while self.signal_buffer:
                self.signals.append(self.signal_buffer.popleft())

            # Remove signals outside time window
            if self.timestamps:
                min_ts = self.timestamps[0]
                max_ts = self.timestamps[-1]
                while self.signals and (self.signals[0][0] < min_ts or self.signals[0][0] > max_ts):
                    self.signals.popleft()

            # Latest signal text
            if self.signals:
                latest_sig = self.signals[-1][2]
                if latest_sig == 1:
                    self.signal_text_label.setText("BUY")
                elif latest_sig == -1:
                    self.signal_text_label.setText("SELL")
            else:
                self.signal_text_label.setText("No signals")

            # Plot BUY/SELL signals
            signal_points = []
            for ts, price, sig in self.signals:
                if sig == 1:
                    color = 'g'
                    symbol = 't1'  # triangle up
                elif sig == -1:
                    color = 'r'
                    symbol = 't'  # triangle down
                else:
                    continue
                signal_points.append({'pos': (ts, price), 'brush': color, 'symbol': symbol, 'size': 15})
            self.signal_scatter.setData(signal_points)

    def start(self):
        if not self.is_started:
            self.is_started = True
            logging.info("Starting plotter")
            self.win.show()
            sys.exit(self.app.exec())

if __name__ == '__main__':
    plotter = RealTimePlot(ticker_name="UNKNOWN", max_minutes=60, max_ticks=500)
    plotter.start()
