@echo off
cd /d "%~dp0"
start cmd /k "set PYTHONPATH=%~dp0 && python engine/main.py"
start cmd /k "set PYTHONPATH=%~dp0 && python gateways/binance/run_binance.py"

