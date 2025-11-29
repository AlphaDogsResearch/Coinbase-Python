"""Run the Risk Engine standalone and wire it to the Coinbase gateway.

This module:
- Instantiates CoinbaseAdvancedGateway
- Registers listeners to feed account/wallet and mark prices into RiskManager
- Exposes a simple Strategy-facing listener to validate trades via RiskManager

Run with:
  python -m engine.risk.run_risk_engine

Environment:
- Reads API keys from gateways/coinbase/vault/coinbase_keys (.env format)
- Uses sandbox by default; set IS_PROD=1 to run against production
"""

import os
import logging
from typing import Optional
from dotenv import load_dotenv

from common.config_logging import to_stdout
from engine.risk.risk_manager import RiskManager
from common.interface_order import Order
from gateways.coinbase.coinbase_gateway import CoinbaseAdvancedGateway

# -------------------------
# Setup helpers
# -------------------------

def _load_keys_from_vault():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    vault_env = os.path.join(base_dir, '..', '..', 'gateways', 'coinbase', 'vault', 'coinbase_keys')
    vault_env = os.path.normpath(vault_env)
    if os.path.exists(vault_env):
        load_dotenv(dotenv_path=vault_env)
    return os.getenv("COINBASE_TRADING_KEY_ID"), os.getenv("COINBASE_TRADING_SECRET")


def _make_gateway(symbols, is_prod: bool) -> CoinbaseAdvancedGateway:
    api_key, api_secret = _load_keys_from_vault()
    gw = CoinbaseAdvancedGateway(
        symbols=symbols,
        api_key=api_key,
        api_secret=api_secret,
        is_sand_box=not is_prod,
    )
    return gw

# -------------------------
# Strategy-facing listener
# -------------------------
class StrategyTradeValidator:
    """Adapter for strategies to check orders via RiskManager."""
    def __init__(self, risk_mgr: RiskManager):
        self._risk = risk_mgr

    def is_order_allowed(self, order: Order) -> bool:
        return self._risk.validate_order(order)

# -------------------------
# Main wiring
# -------------------------

def main():
    to_stdout()
    logging.info("Starting Risk Engine runner")

    is_prod = os.getenv('IS_PROD') == '1'
    symbols = [os.getenv('SYMBOL', 'BTC-USD')]

    # Instantiate gateway and risk manager
    gw = _make_gateway(symbols, is_prod=is_prod)
    risk_mgr = RiskManager()

    # Configure price provider from gateway mark price cache
    def price_provider(symbol: str) -> Optional[float]:
        return gw.get_mark_price(symbol)
    risk_mgr.set_price_provider(price_provider)

    # Wire wallet balance to AUM updates TODO
    # def wallet_listener(wallet_snapshot: dict):
    #     # simple: sum balances if numeric
    #     total = 0.0
    #     if isinstance(wallet_snapshot, dict):
    #         for _, v in wallet_snapshot.items():
    #             try:
    #                 total += float(v)
    #             except Exception:
    #                 continue
    #     risk_mgr.on_wallet_balance_update(total)
    # gw.register_wallet_balance_callback(wallet_listener)

    # Wire mark price updates
    def mark_price_listener(exchange: str, mid: float):
        for sym in symbols:
            # best effort: update symbol price with latest mid
            risk_mgr.on_mark_price_update(sym, mid)
    gw.register_mark_price_callback(mark_price_listener)

    # Depth listener (optional): can be used to compute spreads or additional constraints
    def depth_listener(exchange: str, venue_book):
        # no-op for now; placeholder where you could compute spread/volatility
        pass
    gw.register_depth_callback(depth_listener)

    # Provide strategy validator instance
    validator = StrategyTradeValidator(risk_mgr)
    logging.info("Risk Engine ready; connecting gateway...")

    # Try to fetch initial AUM from gateway before live updates
    try:
        # Prefer public method if available
        if hasattr(gw, 'get_wallet_balances') and callable(getattr(gw, 'get_wallet_balances')):
            snapshot = gw.get_wallet_balances()
        elif hasattr(gw, 'list_wallet_balances') and callable(getattr(gw, 'list_wallet_balances')):
            snapshot = gw.list_wallet_balances()
        elif hasattr(gw, '_get_wallet_balances') and callable(getattr(gw, '_get_wallet_balances')):
            # Fallback to internal method if necessary
            snapshot = gw._get_wallet_balances()
        else:
            snapshot = None

        if isinstance(snapshot, dict):
            total = 0.0
            for _, v in snapshot.items():
                try:
                    total += float(v)
                except Exception:
                    continue
            risk_mgr.set_aum(total)
            logging.info(f"Initialized AUM from gateway snapshot: {total}")
    except Exception:
        logging.debug("Failed to initialize AUM from gateway balances", exc_info=True)

    # Start websocket (blocks)
    gw.connect()


if __name__ == '__main__':
    main()
