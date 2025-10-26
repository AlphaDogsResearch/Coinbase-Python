import pytest
import sys
from pathlib import Path

# Ensure repository root is on sys.path for imports
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.risk.risk_manager import RiskManager
from common.interface_order import Order, Side, OrderType


def make_order(order_id: str, symbol: str, side: Side, qty: float, price: float = None, order_type: OrderType = OrderType.Market):
    # timestamp 0 for tests
    return Order(order_id, side, qty, symbol, 0, order_type, price)


def setup_risk_manager(**overrides):
    # Set very permissive defaults unless a particular check is being tested
    params = dict(
        max_order_value=1e12,
        max_position_value=1e12,
        max_leverage=1000.0,
        max_open_orders=10**9,
        max_loss_per_day=1.0,   # 100% of AUM
        max_var_ratio=1.0,       # 100% of PV
        min_order_size=0.0,
        allowed_symbols=None,
    )
    params.update(overrides)
    rm = RiskManager(**params)
    rm.set_aum(1_000_000.0)  # default AUM for leverage computations
    return rm


def test_whitelist_rejects_unlisted_symbol():
    rm = setup_risk_manager(allowed_symbols=["BTCUSDC"], min_order_size=1.0)
    rm.on_mark_price_update("ETHUSDC", 2000.0)
    order = make_order("1", "ETHUSDC", Side.BUY, 2.0, 2000.0)
    assert rm.validate_order(order) is False

    # Allowed symbol should pass if other checks are permissive
    rm.on_mark_price_update("BTCUSDC", 30000.0)
    order_ok = make_order("2", "BTCUSDC", Side.BUY, 2.0, 30000.0)
    assert rm.validate_order(order_ok) is True


def test_min_order_size_enforced():
    rm = setup_risk_manager(min_order_size=5.0)
    rm.on_mark_price_update("BTCUSDC", 30000.0)
    small = make_order("1", "BTCUSDC", Side.BUY, 4.0, 30000.0)
    assert rm.validate_order(small) is False
    ok = make_order("2", "BTCUSDC", Side.BUY, 5.0, 30000.0)
    assert rm.validate_order(ok) is True


def test_price_fallback_mark_price():
    rm = setup_risk_manager(min_order_size=1.0)
    # No order price and no mark price -> reject
    o_no_price = make_order("1", "BTCUSDC", Side.BUY, 1.0, None)
    assert rm.validate_order(o_no_price) is False

    # With mark price fallback -> accept under permissive limits
    rm.on_mark_price_update("BTCUSDC", 35000.0)
    assert rm.validate_order(o_no_price) is True


def test_max_order_value():
    rm = setup_risk_manager(min_order_size=1.0, max_order_value=1000.0)
    rm.on_mark_price_update("BTCUSDC", 100.0)
    # 20 * 100 = 2000 > 1000 -> reject
    big = make_order("1", "BTCUSDC", Side.BUY, 20.0, 100.0)
    assert rm.validate_order(big) is False
    # 5 * 100 = 500 <= 1000 -> ok
    ok = make_order("2", "BTCUSDC", Side.BUY, 5.0, 100.0)
    assert rm.validate_order(ok) is True


def test_max_position_value_and_leverage():
    # Set stringent caps to trigger both checks
    rm = setup_risk_manager(min_order_size=1.0, max_position_value=1000.0, max_leverage=0.5)
    rm.set_aum(1000.0)  # so 1000 notional => 1.0x leverage
    rm.on_mark_price_update("ETHUSDC", 100.0)

    # Current position 5 -> notional 500
    rm.on_position_amount_update("ETHUSDC", 5.0)
    # Add 6 more at price 100 => future notional 1100 > max_position_value -> reject
    o = make_order("1", "ETHUSDC", Side.BUY, 6.0, 100.0)
    assert rm.validate_order(o) is False

    # Smaller add: +4 => future notional 900 -> within position cap, but leverage 900/1000=0.9 > 0.5 -> reject by leverage
    o2 = make_order("2", "ETHUSDC", Side.BUY, 4.0, 100.0)
    assert rm.validate_order(o2) is False

    # Much smaller: +1 => future notional 600 -> leverage 0.6 > 0.5 -> still reject
    o3 = make_order("3", "ETHUSDC", Side.BUY, 1.0, 100.0)
    assert rm.validate_order(o3) is False

    # Relax leverage to 1.0 -> accept
    rm.max_leverage = 1.0
    assert rm.validate_order(o3) is True


def test_max_open_orders():
    rm = setup_risk_manager(min_order_size=1.0, max_open_orders=2)
    rm.on_mark_price_update("XRPUSDC", 1.0)
    rm.on_open_orders_update("XRPUSDC", 2)
    o = make_order("1", "XRPUSDC", Side.BUY, 1.0, 1.0)
    assert rm.validate_order(o) is False
    rm.on_open_orders_update("XRPUSDC", 1)
    assert rm.validate_order(o) is True


def test_daily_loss_limit():
    # 10% of AUM; with AUM=1000, threshold=100
    rm = setup_risk_manager(min_order_size=1.0, max_loss_per_day=0.10)
    rm.set_aum(1000.0)
    rm.on_mark_price_update("BTCUSDC", 100.0)
    # Exceed per-symbol loss
    rm.update_daily_loss(-200.0, symbol="BTCUSDC")
    o = make_order("1", "BTCUSDC", Side.BUY, 1.0, 100.0)
    assert rm.validate_order(o) is False


def test_var_ratio_check():
    # Max VaR ratio 15%
    rm = setup_risk_manager(min_order_size=1.0, max_var_ratio=0.15)
    rm.on_mark_price_update("ETHUSDC", 100.0)
    rm.set_symbol_var("ETHUSDC", var_value=200.0, portfolio_value=1000.0)  # 20% > 15% -> reject
    o = make_order("1", "ETHUSDC", Side.BUY, 1.0, 100.0)
    assert rm.validate_order(o) is False
    rm.set_symbol_var("ETHUSDC", var_value=100.0, portfolio_value=1000.0)  # 10% <= 15% -> ok
    assert rm.validate_order(o) is True


def test_reporting_includes_symbol_lines():
    rm = setup_risk_manager()
    sym = "BTCUSDC"
    rm.add_symbol(sym)
    rm.on_position_amount_update(sym, 2.0)
    rm.on_mark_price_update(sym, 30000.0)
    text = rm.generate_risk_report_text([sym])
    assert f"[{sym}]" in text
    assert "qty=2.0" in text
    assert "price=30000.0" in text


def test_sell_order_reduces_position_and_passes_under_caps():
    rm = setup_risk_manager(min_order_size=1.0, max_position_value=600.0, max_leverage=10.0)
    sym = "ETHUSDC"
    rm.on_mark_price_update(sym, 100.0)
    # Current long position 10 -> notional 1000 (already above cap), but selling 5 reduces risk
    rm.on_position_amount_update(sym, 10.0)
    sell = make_order("s1", sym, Side.SELL, 5.0, 100.0)
    assert rm.validate_order(sell) is True


def test_per_symbol_min_order_size_override():
    rm = setup_risk_manager(min_order_size=1.0)
    sym = "ETHUSDC"
    rm.add_symbol(sym, min_order_size=7.0)
    rm.on_mark_price_update(sym, 100.0)
    too_small = make_order("m1", sym, Side.BUY, 6.0, 100.0)
    assert rm.validate_order(too_small) is False
    just_ok = make_order("m2", sym, Side.BUY, 7.0, 100.0)
    assert rm.validate_order(just_ok) is True


def test_price_provider_exception_fallback_to_cache():
    rm = setup_risk_manager(min_order_size=1.0)
    sym = "BTCUSDC"
    # Set a provider that raises and ensure cache is used
    def bad_provider(_):
        raise RuntimeError("provider failed")
    rm.set_price_provider(bad_provider)
    rm.on_mark_price_update(sym, 123.0)
    o = make_order("p1", sym, Side.BUY, 1.0, None)
    assert rm.validate_order(o) is True


def test_price_provider_none_rejects_even_with_cache_then_clear_provider():
    rm = setup_risk_manager(min_order_size=1.0)
    sym = "BTCUSDC"
    # Provider returns None -> without cache reject
    rm.set_price_provider(lambda _: None)
    o = make_order("pn1", sym, Side.BUY, 1.0, None)
    assert rm.validate_order(o) is False
    # After caching mark price, still reject (provider returns None short-circuits fallback)
    rm.on_mark_price_update(sym, 456.0)
    assert rm.validate_order(o) is False
    # Clearing provider allows fallback to cached price
    rm.set_price_provider(None)
    assert rm.validate_order(o) is True


def test_add_and_remove_symbol_affects_whitelist():
    # Start with enforced whitelist containing an unrelated symbol so the set is truthy
    rm = setup_risk_manager(allowed_symbols=["DUMMY"], min_order_size=1.0)
    sym = "XRPUSDC"
    rm.on_mark_price_update(sym, 1.0)
    o = make_order("w1", sym, Side.BUY, 1.0, 1.0)
    # Not allowed yet
    assert rm.validate_order(o) is False
    # Add and allow
    rm.add_symbol(sym)
    assert rm.validate_order(o) is True
    # Remove and reject again
    rm.remove_symbol(sym)
    assert rm.validate_order(o) is False


def test_generate_report_includes_global_var_line():
    rm = setup_risk_manager()
    # Set global VaR and Portfolio Value
    rm.set_var(var_value=200.0, portfolio_value=1000.0)
    text = rm.generate_risk_report_text()
    assert "Global VaR=200.0, PV=1000.0, Ratio=0.2000" in text


def test_portfolio_var_assessment_branches():
    rm = setup_risk_manager()
    sym = "BTCUSDC"
    # pv == 0 -> 1
    assert rm.get_portfolio_var_assessment(sym) == 1
    # ratio > 0.8 -> 0
    rm.set_symbol_var(sym, var_value=90.0, portfolio_value=100.0)
    assert rm.get_portfolio_var_assessment(sym) == 0
    # 0.5 < ratio <= 0.8 -> 0.5
    rm.set_symbol_var(sym, var_value=60.0, portfolio_value=100.0)
    assert rm.get_portfolio_var_assessment(sym) == 0.5
    # ratio <= 0.5 -> 1
    rm.set_symbol_var(sym, var_value=40.0, portfolio_value=100.0)
    assert rm.get_portfolio_var_assessment(sym) == 1


def test_periodic_reporting_start_and_stop(tmp_path):
    rm = setup_risk_manager()
    report_file = tmp_path / "risk_report.log"
    rm.start_periodic_risk_reports(str(report_file), interval_seconds=10)
    # Immediately stop to avoid waiting; just covering setup/teardown paths
    rm.stop_periodic_risk_reports()
    # Logger should have been created; file may or may not have content depending on timing, but should exist or be creatable
    # Ensure no exceptions and attribute set
    assert rm._report_logger is not None


def test_calculate_and_get_portfolio_var_and_reset_loss():
    rm = setup_risk_manager()
    # Initially zero
    assert rm.calculate_portfolio_var({}, portfolio_value=500.0) == 0.0
    # Set and retrieve
    rm.set_var(50.0, 500.0)
    assert rm.calculate_portfolio_var({}, portfolio_value=500.0) == 50.0
    assert rm.get_portfolio_var() == 50.0
    # Daily loss updates and reset
    rm.update_daily_loss(-10.0, symbol="BTCUSDC")
    rm.update_daily_loss(5.0, symbol="ETHUSDC")
    # Include global aggregate
    assert rm.symbol_daily_loss.get("BTCUSDC", 0) != 0
    assert rm.symbol_daily_loss.get("__GLOBAL__", 0) != 0
    rm.reset_daily_loss()
    assert rm.symbol_daily_loss.get("BTCUSDC", 0) == 0.0
    assert rm.symbol_daily_loss.get("ETHUSDC", 0) == 0.0
    assert rm.symbol_daily_loss.get("__GLOBAL__", 0) == 0.0


def test_price_zero_triggers_fallback_and_missing_reject():
    rm = setup_risk_manager(min_order_size=1.0)
    sym = "BTCUSDC"
    # price=0 with no mark -> reject
    o0 = make_order("z0", sym, Side.BUY, 1.0, 0.0)
    assert rm.validate_order(o0) is False
    # With mark price, should fall back and pass
    rm.on_mark_price_update(sym, 99.0)
    assert rm.validate_order(o0) is True


def test_aum_zero_skips_leverage_check():
    # Leverage cap would be violated if AUM > 0, but with AUM=0 it is skipped
    rm = setup_risk_manager(min_order_size=1.0, max_position_value=1e9, max_leverage=0.01)
    rm.set_aum(0.0)
    sym = "ETHUSDC"
    rm.on_mark_price_update(sym, 100.0)
    o = make_order("a0", sym, Side.BUY, 100.0, 100.0)  # notional 10_000 << position cap
    assert rm.validate_order(o) is True


def test_open_orders_from_position_object_path():
    from engine.position.position import Position
    sym = "LTCUSDC"
    rm = setup_risk_manager(min_order_size=1.0, max_open_orders=2)
    pos = Position(symbol=sym, position_amount=2.0)
    pos.set_open_orders(2)
    rm.add_symbol(sym, position=pos)
    rm.on_mark_price_update(sym, 10.0)
    o = make_order("po1", sym, Side.BUY, 1.0, 10.0)
    assert rm.validate_order(o) is False  # 2 >= 2 -> reject via Position.get_open_orders path
    pos.set_open_orders(1)
    assert rm.validate_order(o) is True


def test_open_orders_update_with_string_is_cast():
    rm = setup_risk_manager(min_order_size=1.0, max_open_orders=2)
    sym = "ADAUSDC"
    rm.on_mark_price_update(sym, 1.0)
    rm.on_open_orders_update(sym, "2")  # should be cast to int
    o = make_order("os1", sym, Side.BUY, 1.0, 1.0)
    assert rm.validate_order(o) is False


def test_missing_side_treated_as_buy():
    rm = setup_risk_manager(min_order_size=1.0)
    sym = "SOLUSDC"
    rm.on_mark_price_update(sym, 10.0)
    # Construct order with side=None
    o = Order("ms1", None, 1.0, sym, 0, OrderType.Market, 10.0)
    assert rm.validate_order(o) is True


def test_negative_qty_uses_abs_for_min_size():
    rm = setup_risk_manager(min_order_size=5.0)
    sym = "DOGEUSDC"
    rm.on_mark_price_update(sym, 0.1)
    # Negative qty, abs=4 -> reject; abs=5 -> pass
    o_small = make_order("n1", sym, Side.BUY, -4.0, 0.1)
    assert rm.validate_order(o_small) is False
    o_ok = make_order("n2", sym, Side.BUY, -5.0, 0.1)
    assert rm.validate_order(o_ok) is True


def test_daily_loss_at_threshold_allows():
    rm = setup_risk_manager(min_order_size=1.0, max_loss_per_day=0.10)
    rm.set_aum(1000.0)
    sym = "BTCUSDC"
    rm.on_mark_price_update(sym, 100.0)
    # Exactly at threshold (100) should pass; rule rejects only if strictly greater
    rm.update_daily_loss(-100.0, symbol=sym)
    o = make_order("dl1", sym, Side.BUY, 1.0, 100.0)
    assert rm.validate_order(o) is True


def test_var_ratio_at_threshold_allows():
    rm = setup_risk_manager(min_order_size=1.0, max_var_ratio=0.15)
    sym = "ETHUSDC"
    rm.on_mark_price_update(sym, 100.0)
    rm.set_symbol_var(sym, var_value=150.0, portfolio_value=1000.0)  # exactly 15%
    o = make_order("vr1", sym, Side.BUY, 1.0, 100.0)
    assert rm.validate_order(o) is True