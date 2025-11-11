# tests/test_config_loader.py
import json
import os
import tempfile

import pytest

from common.config_loader.basic_config_loader import load_config, create_objects


@pytest.fixture
def temp_config_files():
    """Creates temporary UAT and PROD JSON config_loader files for testing."""
    uat = {
        "default_settings": {
            "module": "builtins",
            "class": "dict",
            "params": {
                "margin_limit": 0.8,
                "selected_symbol": "ETHUSDT",
                "trading_symbols": ["BTCUSDT", "ETHUSDT"],
                "executor_order_type": "@common.interface_order.OrderType.Market",
                "interval_seconds": 1,
            }
        },
        "position": {
            "module": "engine.position.position",
            "class": "Position",
            "params": {
                "symbol": "@default_settings.selected_symbol",
            }
        },

        "risk_manager": {
            "module": "engine.risk.risk_manager",
            "class": "RiskManager",
            "params": {
                "position": "@position",
            }
        },

        "margin_manager": {
            "module": "engine.margin.margin_info_manager",
            "class": "MarginInfoManager"
        },
        "trading_cost_manager": {
            "module": "engine.trading_cost.trading_cost_manager",
            "class": "TradingCostManager"
        },
        "sharpe_calculator": {
            "module": "common.metrics.sharpe_calculator",
            "class": "BinanceFuturesSharpeCalculator"
        },
        "trade_manager": {
            "module": "engine.trades.trades_manager",
            "class": "TradesManager",
            "params": {
                "sharpe_calculator": "@sharpe_calculator",
            }
        },
        "reference_price_manager": {
            "module": "engine.reference_data.reference_price_manager",
            "class": "ReferencePriceManager"
        },
        "position_manager": {
            "module": "engine.position.position_manager",
            "class": "PositionManager",
            "params": {
                "margin_manager": "@margin_manager",
                "trading_cost_manager": "@trading_cost_manager",
                "reference_price_manager": "@reference_price_manager",
            }
        },
        "account": {
            "module": "engine.account.account",
            "class": "Account",
            "params": {
                "margin_limit": "@default_settings.margin_limit",
            }
        },
        "remote_market_data_client": {
            "module": "engine.remote.remote_market_data_client",
            "class": "RemoteMarketDataClient"
        },
        "reference_data_manager": {
            "module": "engine.reference_data.reference_data_manager",
            "class": "ReferenceDataManager",
            "params": {
                "reference_price_manager": "@reference_price_manager",
            }
        },
        "remote_order_client": {
            "module": "engine.remote.remote_order_service_client",
            "class": "RemoteOrderClient",
            "params": {
                "margin_manager": "@margin_manager",
                "position_manager": "@position_manager",
                "account": "@account",
                "trading_cost_manager": "@trading_cost_manager",
                "trade_manager": "@trade_manager",
                "reference_data_manager": "@reference_data_manager",
            }
        },
        "executor": {
            "module": "engine.execution.executor",
            "class": "Executor",
            "params": {
                "order_type": "@default_settings.executor_order_type",
                "remote_order_client": "@remote_order_client",
            }
        },
        "order_manager": {
            "module": "engine.management.order_management_system",
            "class": "FCFSOrderManager",
            "params": {
                "executor": "@executor",
                "risk_manager": "@risk_manager",
                "reference_data_manager": "@reference_data_manager",
            }
        },
        "strategy_manager": {
            "module": "engine.strategies.strategy_manager",
            "class": "StrategyManager",
            "params": {
                "remote_market_data_client": "@remote_market_data_client",
                "order_manager": "@order_manager"
            }
        },
        "strategy_map": {
            "roc_mean_reversion_strategy": {
                "factory": "engine.strategies."
                           "nautilus_strategy_factory.create_roc_mean_reversion_strategy",
                "params": {
                    "symbol": "@default_settings.selected_symbol",
                    "position_manager": "@position_manager",
                    "interval_seconds": "@default_settings.interval_seconds"
                }
            },
            "cci_momentum_strategy": {
                "factory": "engine.strategies."
                           "nautilus_strategy_factory.create_cci_momentum_strategy",
                "params": {
                    "symbol": "@default_settings.selected_symbol",
                    "position_manager": "@position_manager",
                    "interval_seconds": "@default_settings.interval_seconds"
                }
            },
            "apo_mean_reversion_strategy": {
                "factory": "engine.strategies."
                           "nautilus_strategy_factory.create_apo_mean_reversion_strategy",
                "params": {
                    "symbol": "@default_settings.selected_symbol",
                    "position_manager": "@position_manager",
                    "interval_seconds": "@default_settings.interval_seconds"
                }
            },
            "ppo_mean_reversion_strategy": {
                "factory": "engine.strategies."
                           "nautilus_strategy_factory.create_ppo_momentum_strategy",
                "params": {
                    "symbol": "@default_settings.selected_symbol",
                    "position_manager": "@position_manager",
                    "interval_seconds": "@default_settings.interval_seconds"
                }
            },
        },

    }


    # Write both configs to temp files
    with tempfile.TemporaryDirectory() as tmpdir:
        uat_path = os.path.join(tmpdir, "config_uat.json")
        prod_path = os.path.join(tmpdir, "config_prod.json")

        with open(uat_path, "w") as f:
            json.dump(uat, f)

        yield tmpdir


def test_load_config_uat(temp_config_files, monkeypatch):

    """Test that UAT config_loader loads and objects are built correctly."""
    monkeypatch.chdir(temp_config_files)  # simulate running inside temp dir

    config = load_config("uat")
    objs = create_objects(config)



    # Assertions
    assert "default_settings" in objs,f"default_settings not found in objects"
    default_settings = objs["default_settings"]
    assert "position" in objs ,"position not found in objects"
    position = objs["position"]
    assert position.symbol is default_settings["selected_symbol"], "symbol should be the same"
    assert "risk_manager" in objs ,"risk_manager not found in objects"
    assert "margin_manager" in objs ,"margin_manager not found in objects"
    assert "trading_cost_manager" in objs ,"trading_cost_manager not found in objects"
    assert "sharpe_calculator" in objs ,"sharpe_calculator not found in objects"
    assert "trade_manager" in objs ,"trade_manager not found in objects"
    assert "reference_price_manager" in objs,"reference_price_manager not found in objects"
    assert "position_manager" in objs,"position_manager not found in objects"
    position_manager = objs["position_manager"]
    assert "account" in objs ,"account not found in objects"
    assert "remote_market_data_client" in objs ,"remote_market_data_client not found in objects"
    assert "reference_data_manager" in objs ,"reference_data_manager not found in objects"
    assert "remote_order_client" in objs ,"remote_order_client not found in objects"
    remote_order_client = objs["remote_order_client"]
    assert remote_order_client.position_manager is position_manager, "position_manager should be the same"

    assert "executor" in objs ,"executor not found in objects"
    assert "order_manager" in objs ,"order_manager not found in objects"
    assert "strategy_manager" in objs ,"strategy_manager not found in objects"
    assert "strategy_map" in objs ,"strategy_manager not found in objects"

