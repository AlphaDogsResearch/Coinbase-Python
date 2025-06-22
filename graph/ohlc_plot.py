import sys
import random
import time
import datetime
import threading
from collections import deque

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets

# Candlestick plotting helper
class CandlestickItem(pg.GraphicsObject):
    def __init__(self, data):
        super().__init__()
        self.data = data  # Each element: (timestamp, open, high, low, close)
        self.picture = None
        self._bounding_rect = QtCore.QRectF()
        self.generatePicture()

    def generatePicture(self):
        self.picture = pg.QtGui.QPicture()
        painter = pg.QtGui.QPainter(self.picture)

        if len(self.data) > 1:
            times = [d[0] for d in self.data]
            avg_diff = (times[-1] - times[0]) / (len(times) - 1)
            w = max(1, avg_diff * 0.8)
        else:
            w = 5  # fallback width

        x_vals = []
        y_vals = []

        for (t, open_, high, low, close) in self.data:
            x_vals.append(t)
            y_vals += [open_, high, low, close]

            candle_color = 'g' if close >= open_ else 'r'
            painter.setPen(pg.mkPen('w'))
            painter.setBrush(pg.mkBrush(candle_color))

            top = max(open_, close)
            bottom = min(open_, close)

            painter.drawRect(QtCore.QRectF(t - w / 2, bottom, w, top - bottom))
            painter.drawLine(QtCore.QPointF(t, low), QtCore.QPointF(t, high))

        painter.end()

        if x_vals and y_vals:
            min_x, max_x = min(x_vals) - w, max(x_vals) + w
            min_y, max_y = min(y_vals), max(y_vals)
            self._bounding_rect = QtCore.QRectF(min_x, min_y, max_x - min_x, max_y - min_y)
        else:
            self._bounding_rect = QtCore.QRectF()

    def paint(self, painter, *args):
        if self.picture:
            painter.drawPicture(0, 0, self.picture)

    def boundingRect(self):
        return self._bounding_rect



class RealTimePlotWithCandlestick:
    def __init__(self, ticker_name="TICKER", max_minutes=10, max_ticks=None, update_interval_ms=100,is_simulation=True):
        self.app = QtWidgets.QApplication(sys.argv)

        self.win = QtWidgets.QWidget()
        self.win.setWindowTitle(f"Real-Time OHLC Plot - {ticker_name}")

        # Layouts
        self.layout = QtWidgets.QHBoxLayout()
        self.win.setLayout(self.layout)

        left_layout = QtWidgets.QVBoxLayout()
        self.layout.addLayout(left_layout)

        self.ticker_label = QtWidgets.QLabel(ticker_name)
        font = self.ticker_label.font()
        font.setPointSize(16)
        font.setBold(True)
        self.ticker_label.setFont(font)
        left_layout.addWidget(self.ticker_label)

        self.plot_widget = pg.PlotWidget(title="OHLC Candlestick + SMA")
        self.plot_widget.setLabel('left', 'Price')
        self.plot_widget.setLabel('bottom', 'Time')
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_widget.setAxisItems({'bottom': pg.graphicsItems.DateAxisItem.DateAxisItem()})
        self.legend = self.plot_widget.addLegend(offset=(10, 10))
        self.legend.setBrush(pg.mkBrush((30, 30, 30, 180)))
        left_layout.addWidget(self.plot_widget)

        self.info_panel = QtWidgets.QWidget()
        self.info_layout = QtWidgets.QFormLayout()
        self.info_panel.setLayout(self.info_layout)
        self.layout.addWidget(self.info_panel)

        # Metrics labels
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

        # Data buffers
        self.ohlc_data = deque()
        self.ohlc_buffer = deque()
        self.ohlc_item = CandlestickItem([])
        self.plot_widget.addItem(self.ohlc_item)

        self.sma_timestamps = deque()
        self.sma_values = deque()
        self.sma_buffer = deque()

        self.sma2_timestamps = deque()
        self.sma2_values = deque()
        self.sma2_buffer = deque()

        self.signals = deque()
        self.signal_buffer = deque()

        self.lock = threading.Lock()

        # Metrics initial values
        self._realized_pnl = 0.0
        self._capital = 0.0
        self._unrealized_pnl = 0.0
        self._margin_ratio = 0.0
        self._daily_sharpe = 0.0

        # SMA plot curves
        self.sma_curve = self.plot_widget.plot(pen=pg.mkPen('c', width=2), name="SMA")
        self.sma2_curve = self.plot_widget.plot(pen=pg.mkPen('m', width=2), name="SMA2")

        self.signal_scatter = pg.ScatterPlotItem(size=15, brush='b', symbol='t1', pen='w', name="Signals")
        self.plot_widget.addItem(self.signal_scatter)

        # New params
        self.max_seconds = max_minutes * 60
        self.max_ticks = max_ticks

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_all)
        self.timer.start(update_interval_ms)

        if is_simulation:
            # Start simulation threads (unchanged)
            threading.Thread(target=self._simulate_ohlc_feed, daemon=True).start()
            threading.Thread(target=self._simulate_metrics, daemon=True).start()
            threading.Thread(target=self._simulate_signals, daemon=True).start()
            threading.Thread(target=self._simulate_daily_sharpe, daemon=True).start()
            threading.Thread(target=self._simulate_external_sma, daemon=True).start()
            threading.Thread(target=self._simulate_external_sma2, daemon=True).start()

    # Simulated OHLC data
    def _simulate_ohlc_feed(self):
        price = 100.0
        while True:
            open_ = price
            high = open_ + random.uniform(0, 0.5)
            low = open_ - random.uniform(0, 0.5)
            close = low + random.random() * (high - low)
            price = close
            timestamp = datetime.datetime.now()
            self.add_ohlc_candle(timestamp, open_, high, low, close)
            time.sleep(1)

    # Simulated SMA 1
    def _simulate_external_sma(self):
        sma_val = 100.0
        while True:
            sma_val += random.uniform(-0.2, 0.2)
            timestamp = datetime.datetime.now()
            self.add_sma_point(timestamp, sma_val)
            time.sleep(0.1)

    # Simulated SMA 2
    def _simulate_external_sma2(self):
        sma2_val = 100.0
        while True:
            sma2_val += random.uniform(-0.3, 0.3)
            timestamp = datetime.datetime.now()
            self.add_sma2_point(timestamp, sma2_val)
            time.sleep(0.1)

    # Simulated metrics (for demo)
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
            self.add_signal(timestamp, signal, price)
            time.sleep(3)

    def _simulate_daily_sharpe(self):
        sharpe = 0.0
        while True:
            sharpe += random.uniform(-0.1, 0.1)
            sharpe = max(-5, min(5, sharpe))
            self.add_daily_sharpe(sharpe)
            time.sleep(1)

    # Data ingestion
    def add_ohlc_candle(self, timestamp: datetime.datetime, open_, high, low, close):
        with self.lock:
            self.ohlc_buffer.append((timestamp.timestamp(), open_, high, low, close))

    def add_sma_point(self, timestamp: datetime.datetime, sma: float):
        with self.lock:
            self.sma_buffer.append((timestamp.timestamp(), sma))

    def add_sma2_point(self, timestamp: datetime.datetime, sma2: float):
        with self.lock:
            self.sma2_buffer.append((timestamp.timestamp(), sma2))

    def add_realized_pnl(self, value: float):
        self._realized_pnl = value

    def add_capital(self, value: float):
        self._capital = value

    def add_unrealized_pnl(self, value: float):
        self._unrealized_pnl = value

    def add_margin_ratio(self, value: float):
        self._margin_ratio = value

    def add_daily_sharpe(self, value: float):
        self._daily_sharpe = value

    def add_signal(self, timestamp: datetime.datetime, signal_value: int, price: float):
        if signal_value not in (1, -1):
            return
        with self.lock:
            self.signal_buffer.append((timestamp.timestamp(), price, signal_value))

    # Update GUI
    def update_all(self):
        with self.lock:
            now = time.time()

            # Process OHLC buffer
            while self.ohlc_buffer:
                self.ohlc_data.append(self.ohlc_buffer.popleft())

            # Trim OHLC data by max_ticks only
            if self.max_ticks is not None:
                while len(self.ohlc_data) > self.max_ticks:
                    self.ohlc_data.popleft()

            # Process SMA buffers
            while self.sma_buffer:
                ts, sma = self.sma_buffer.popleft()
                self.sma_timestamps.append(ts)
                self.sma_values.append(sma)

            while self.sma2_buffer:
                ts, sma2 = self.sma2_buffer.popleft()
                self.sma2_timestamps.append(ts)
                self.sma2_values.append(sma2)

            # Trim SMA1 by max_ticks
            if self.max_ticks is not None:
                while len(self.sma_timestamps) > self.max_ticks:
                    self.sma_timestamps.popleft()
                    self.sma_values.popleft()

            # Trim SMA2 by max_ticks
            if self.max_ticks is not None:
                while len(self.sma2_timestamps) > self.max_ticks:
                    self.sma2_timestamps.popleft()
                    self.sma2_values.popleft()

            # Redraw candlestick
            self.plot_widget.removeItem(self.ohlc_item)
            self.ohlc_item = CandlestickItem(list(self.ohlc_data))
            self.plot_widget.addItem(self.ohlc_item)

            # Update SMA curves
            self.sma_curve.setData(list(self.sma_timestamps),
                                   list(self.sma_values)) if self.sma_timestamps else self.sma_curve.clear()
            self.sma2_curve.setData(list(self.sma2_timestamps),
                                    list(self.sma2_values)) if self.sma2_timestamps else self.sma2_curve.clear()

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

            # Align signals with current OHLC view
            if self.max_ticks is not None and self.ohlc_data:
                min_ts = self.ohlc_data[0][0]
                self.signals = deque([s for s in self.signals if s[0] >= min_ts])

            # Update latest signal text
            if self.signals:
                latest_sig = self.signals[-1][2]
                self.signal_text_label.setText("BUY" if latest_sig == 1 else "SELL")
            else:
                self.signal_text_label.setText("No signals")

            # Plot signals
            signal_points = []
            for ts, price, sig in self.signals:
                color = 'b' if sig == 1 else 'orange'
                symbol = 't1' if sig == 1 else 't'
                signal_points.append({'pos': (ts, price), 'brush': color, 'symbol': symbol, 'size': 15})
            self.signal_scatter.setData(signal_points)

    def start(self):
        self.win.show()
        sys.exit(self.app.exec())


if __name__ == '__main__':
    plotter = RealTimePlotWithCandlestick(
        ticker_name="DEMO",
        max_minutes=10,    # plot data within last 10 minutes
        max_ticks=300,     # max 300 candles/points shown
        update_interval_ms=200  # refresh every 200 ms
    )
    plotter.start()