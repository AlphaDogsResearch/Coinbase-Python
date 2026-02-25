# Validate with Pine Trades

Align `engine/strategies/*.py` behavior with Pine trade exports, using the research notebook for logic and calculations when there is any ambiguity.

## Objective

Deliver parity between:
1. Research logic (indicator math + signal/risk semantics)
2. Pine strategy behavior (reference trade CSV)
3. Python strategy + backtest/validator output

Primary objective: make sure Pine and `engine/strategies/*.py` align.

This skill is incomplete if it only explains mismatch. It must include concrete code/config fixes for discrepancies when they are found.

## When to Use This Skill

Use when the user asks to:
- Validate Pine CSV trades against Python backtest trades
- Fix `reference != generated` mismatches
- Align strategy Python code to research and Pine behavior
- Improve `validate_runner` parity diagnostics

Triggers: validate runner, pine reference mismatch, parity, backtest discrepancy, strategy vs pine mismatch

## Non-Negotiables

- The objective is parity: Pine and strategy Python must align.
- When in doubt, go back to the research notebook and re-derive logic.
- When in doubt, research notebook logic and calculations are the source of truth.
- Do not guess indicator or signal semantics from comments.
- Always map notebook logic to code line-by-line before changing behavior.
- Always run and report **strict** validation first. Strict output is the pass/fail gate.
- Do not use relaxed tolerances as evidence of parity.
- Use relaxed tolerances only as a temporary diagnostic tool to locate root cause after strict fails.
- Any logic change must be validated against the relevant file(s) in `research/` before implementation and again after implementation.
- If mismatch remains after one fix pass, return to research/Pine and continue until root cause is explained.
- Include discrepancy fixes (code/config/validator), not analysis-only reports.

## Prerequisites

Read these first:
1. Research notebook in `research/` for the target strategy
2. Matching Pine script in `pine/`
3. `engine/backtest/validate_runner.py`
4. Strategy file in `engine/strategies/*_strategy.py`
5. `engine/strategies/indicators.py`
6. `engine/backtest/engine.py` and `engine/backtest/models.py`

## Workflow

### 1) Strict Validation (Gate)

```bash
python -m engine.backtest.validate_runner \
  --reference-file engine/backtest/pine_reference_list_of_trades/<FILE>.csv \
  --execution-timing next_bar_open \
  --strategy-config engine/backtest/configs/validate_pine_parity.json
```

Capture:
- `reference_trade_count`, `generated_trade_count`
- `matched_count`, `mismatched_count`
- `reference_net_pnl`, `generated_net_pnl`, `net_pnl_diff`
- summary + pairs artifact paths

### 2) Classify Discrepancies

Use pairs CSV and classify by dominant type:
- `MISSING_REFERENCE`: overtrading
- `MISSING_GENERATED`: undertrading
- `time mismatch`: fill timing or timezone mismatch
- `side mismatch`: signal logic mismatch
- large PnL gap with close timing: sizing/commission/config mismatch

### 3) Build Research-to-Code Parity Map

Create a direct mapping for:
- Indicator math (MA type, std-dev definition, smoothing, warmup)
- Entry/exit conditions (`momentum`, `mean_reversion`, `midpoint`, `breakout`)
- Risk behavior (`stop_loss`, `max_holding`, cooldown, flip order)
- Sizing and cost assumptions (`notional_amount`, commission)
- Timestamp semantics (timezone, bar-open/bar-close execution)

### 4) Fix Discrepancies (Required)

Implement fixes in this order:
1. **Timestamp parity**
   - Normalize reference timezone if needed (for example `--reference-utc-offset-hours 8` for UTC+8 CSVs).
2. **Execution parity**
   - Match Pine fill semantics (`bar_close` vs `next_bar_open`).
3. **Config parity**
   - Match Pine/research sizing and risk parameters (for example `notional_amount=100`, same stop/max-hold toggles).
4. **Indicator parity**
   - Match research/Pine formulas exactly.
5. **Signal/risk parity**
   - Align entry/exit crossing logic and exit priority ordering.
   - Before changing any signal/risk/position-state logic, map the exact logic from `research/` to Pine and Python line-by-line.
6. **Comparison quality**
   - Improve pairing/alignment if indexing creates false mismatches.

Do not stop after diagnosis. Apply fixes for discovered discrepancies and re-run validation to confirm improvement.

### 5) Re-Run Strict and Quantify Before/After

Run strict. Use relaxed only if strict still fails and only to isolate cause.

```bash
python -m engine.backtest.validate_runner \
  --reference-file <CSV> \
  --execution-timing next_bar_open \
  --strategy-config engine/backtest/configs/validate_pine_parity.json

# Optional diagnostic only (NOT acceptance):
python -m engine.backtest.validate_runner \
  --reference-file <CSV> \
  --execution-timing next_bar_open \
  --strategy-config engine/backtest/configs/validate_pine_parity.json \
  --time-tolerance-minutes 60 \
  --price-tolerance 2.0
```

Report deltas:
- trade-count convergence
- match-rate improvement
- PnL diff improvement
- remaining dominant mismatch type and exact suspected cause
- If relaxed was used, explicitly label it as diagnostic and not a parity pass.

### 6) Documentation Update

Update `engine/backtest/README.md` with reproducible commands used for parity runs, including timezone/fill options.

## Acceptance Criteria

- Validation runs successfully on target Pine CSV.
- Strict validation results are reported and treated as the authoritative parity result.
- Discrepancy root causes are backed by code + artifact evidence.
- At least one concrete discrepancy fix is applied when mismatch exists.
- Every logic change cites the corresponding `research/` logic it was derived from.
- Pine and strategy Python behavior are aligned or remaining gaps are explicitly narrowed with a concrete next fix.
- Before/after metrics are reported.
- README includes runnable parity command examples.
- Backtest runner still executes basic sanity run.
