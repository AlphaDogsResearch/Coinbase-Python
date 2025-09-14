from engine.tracking.in_memory_tracker import InMemoryTracker

# class BacktestReport:
#     def __init__(self, price_series: pd.Series, strategy_returns: pd.Series, trades: Optional[pd.DataFrame] = None):
#         self.price_series = price_series
#         self.strategy_returns = strategy_returns
#         self.trades = trades
#
#         self.start_date = price_series.index.min()
#         self.end_date = price_series.index.max()
#         self.duration = self.end_date - self.start_date
#
#         self.equity_curve = (1 + strategy_returns.fillna(0)).cumprod()
#         self.final_equity = self.equity_curve.iloc[-1]
#         self.equity_peak = self.equity_curve.cummax().max()
#
#         self.return_pct = (self.final_equity - 1) * 100
#         self.bh_return_pct = (price_series.iloc[-1] / price_series.iloc[0] - 1) * 100
#
#     def compute_metrics(self) -> Dict[str, Any]:
#         metrics = {
#             "Start": self.start_date,
#             "End": self.end_date,
#             "Duration": self.duration,
#             "Exposure Time [%]": self._exposure(),
#             "Equity Final [$]": self.final_equity,
#             "Equity Peak [$]": self.equity_peak,
#             "Return [%]": self.return_pct,
#             "Buy & Hold Return [%]": self.bh_return_pct,
#             "Return (Ann.) [%]": self._annualized_return() * 100,
#             "Volatility (Ann.) [%]": self._annualized_volatility() * 100,
#             "Sharpe Ratio": self._sharpe_ratio(),
#             "Sortino Ratio": self._sortino_ratio(),
#             "Calmar Ratio": self._calmar_ratio(),
#             "Max. Drawdown [%]": self._max_drawdown()[0] * 100,
#             "Avg. Drawdown [%]": self._average_drawdown()[0] * 100,
#             "Max. Drawdown Duration": self._max_drawdown()[1],
#             "Avg. Drawdown Duration": self._average_drawdown()[1],
#         }
#
#         if self.trades is not None:
#             metrics.update(self._trade_stats())
#
#         return metrics
#
#     # --- Performance Metrics --- check
#
#     def _annualized_return(self) -> float:
#         periods = len(self.strategy_returns)
#         return (self.final_equity) ** (252 / periods) - 1 if periods > 0 else 0
#
#     def _annualized_volatility(self) -> float:
#         return self.strategy_returns.std(ddof=0) * np.sqrt(252)
#
#     def _sharpe_ratio(self, risk_free_rate: float = 0.0) -> float:
#         excess_returns = self.strategy_returns - (risk_free_rate / 252)
#         std = excess_returns.std(ddof=0)
#         return excess_returns.mean() / std * np.sqrt(252) if std != 0 else np.nan
#
#     def _sortino_ratio(self) -> float:
#         negative_returns = self.strategy_returns[self.strategy_returns < 0]
#         downside_deviation = negative_returns.std(ddof=0) * np.sqrt(252)
#         return self._annualized_return() / downside_deviation if downside_deviation != 0 else np.nan
#
#     def _calmar_ratio(self) -> float:
#         max_dd, _ = self._max_drawdown()
#         return self._annualized_return() / abs(max_dd) if max_dd != 0 else np.nan
#
#     # --- Drawdowns ---
#
#     def _max_drawdown(self) -> (float, timedelta):
#         peak = self.equity_curve.cummax()
#         drawdowns = (self.equity_curve - peak) / peak
#         max_dd = drawdowns.min()
#
#         end = drawdowns.idxmin()
#         start = peak[:end][peak[:end] == peak[:end].max()].last_valid_index()
#         duration = end - start if start and end else timedelta(0)
#
#         return max_dd, duration
#
#     def _average_drawdown(self) -> (float, timedelta):
#         peak = self.equity_curve.cummax()
#         drawdowns = (self.equity_curve - peak) / peak
#         is_drawdown = drawdowns < 0
#
#         drawdown_periods = []
#         current_period = []
#
#         for i, flag in enumerate(is_drawdown):
#             if flag:
#                 current_period.append(drawdowns.index[i])
#             elif current_period:
#                 drawdown_periods.append(current_period)
#                 current_period = []
#
#         if not drawdown_periods:
#             return 0.0, timedelta(0)
#
#         dd_values = [drawdowns.loc[period].min() for period in drawdown_periods]
#         dd_durations = [period[-1] - period[0] for period in drawdown_periods]
#
#         avg_dd = np.mean(dd_values) if dd_values else 0.0
#         avg_duration = np.mean(dd_durations) if dd_durations else timedelta(0)
#
#         return avg_dd, avg_duration
#
#     # --- Exposure and Trades ---
#
#     def _exposure(self) -> float:
#         active_days = self.strategy_returns[self.strategy_returns != 0].count()
#         return (active_days / len(self.strategy_returns)) * 100 if len(self.strategy_returns) > 0 else 0.0
#
#     def _trade_stats(self) -> Dict[str, Any]:
#         returns = self.trades["Return"]
#         durations = self.trades["Duration"]
#
#         num_trades = len(returns)
#
#         return {
#             "# Trades": num_trades,
#             "Win Rate [%]": (returns > 0).sum() / num_trades * 100 if num_trades > 0 else 0,
#             "Best Trade [%]": returns.max() * 100 if num_trades > 0 else np.nan,
#             "Worst Trade [%]": returns.min() * 100 if num_trades > 0 else np.nan,
#             "Avg. Trade [%]": returns.mean() * 100 if num_trades > 0 else np.nan,
#             "Max. Trade Duration": durations.max() if num_trades > 0 else timedelta(0),
#             "Avg. Trade Duration": durations.mean() if num_trades > 0 else timedelta(0),
#             "Profit Factor": returns[returns > 0].sum() / abs(returns[returns < 0].sum()) if (
#                         returns[returns < 0].sum() != 0) else np.nan,
#             "Expectancy [%]": returns.mean() * 100 if num_trades > 0 else np.nan,
#             "SQN": (returns.mean() / returns.std(ddof=0)) * np.sqrt(num_trades) if returns.std(ddof=0) != 0 else np.nan
#         }
