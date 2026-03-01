/*
  # Trading Dashboard Schema

  1. New Tables
    - `strategies`
      - `id` (uuid, primary key)
      - `name` (text) - Strategy name
      - `description` (text) - Strategy description
      - `capital_allocated` (numeric) - Capital allocated to this strategy
      - `status` (text) - active, inactive, paused
      - `created_at` (timestamptz) - Creation timestamp
      
    - `trades`
      - `id` (uuid, primary key)
      - `strategy_id` (uuid, foreign key) - Links to strategies
      - `symbol` (text) - Trading symbol/ticker
      - `side` (text) - buy or sell
      - `quantity` (numeric) - Number of units
      - `entry_price` (numeric) - Entry price
      - `exit_price` (numeric, nullable) - Exit price
      - `entry_time` (timestamptz) - Entry timestamp
      - `exit_time` (timestamptz, nullable) - Exit timestamp
      - `pnl` (numeric, nullable) - Profit/Loss
      - `status` (text) - open or closed
      - `created_at` (timestamptz) - Creation timestamp
      
    - `portfolio_snapshots`
      - `id` (uuid, primary key)
      - `timestamp` (timestamptz) - Snapshot timestamp
      - `total_balance` (numeric) - Total portfolio balance
      - `capital_deployed` (numeric) - Currently deployed capital
      - `available_capital` (numeric) - Available capital
      - `total_pnl` (numeric) - Total profit/loss
      - `max_drawdown` (numeric) - Maximum drawdown percentage
      - `sharpe_ratio` (numeric, nullable) - Sharpe ratio
      - `win_rate` (numeric, nullable) - Win rate percentage
      - `created_at` (timestamptz) - Creation timestamp

  2. Security
    - Enable RLS on all tables
    - Add policies for authenticated users to read all data
    - Add policies for authenticated users to insert/update data
*/

CREATE TABLE IF NOT EXISTS strategies (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  description text DEFAULT '',
  capital_allocated numeric(15,2) NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'active',
  created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trades (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy_id uuid NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
  symbol text NOT NULL,
  side text NOT NULL,
  quantity numeric(15,4) NOT NULL,
  entry_price numeric(15,4) NOT NULL,
  exit_price numeric(15,4),
  entry_time timestamptz NOT NULL DEFAULT now(),
  exit_time timestamptz,
  pnl numeric(15,2),
  status text NOT NULL DEFAULT 'open',
  created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  timestamp timestamptz NOT NULL DEFAULT now(),
  total_balance numeric(15,2) NOT NULL,
  capital_deployed numeric(15,2) NOT NULL DEFAULT 0,
  available_capital numeric(15,2) NOT NULL DEFAULT 0,
  total_pnl numeric(15,2) NOT NULL DEFAULT 0,
  max_drawdown numeric(5,2) DEFAULT 0,
  sharpe_ratio numeric(5,2),
  win_rate numeric(5,2),
  created_at timestamptz DEFAULT now()
);

ALTER TABLE strategies ENABLE ROW LEVEL SECURITY;
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read all strategies"
  ON strategies
  FOR SELECT
  TO authenticated
  USING (true);

CREATE POLICY "Users can insert strategies"
  ON strategies
  FOR INSERT
  TO authenticated
  WITH CHECK (true);

CREATE POLICY "Users can update strategies"
  ON strategies
  FOR UPDATE
  TO authenticated
  USING (true)
  WITH CHECK (true);

CREATE POLICY "Users can read all trades"
  ON trades
  FOR SELECT
  TO authenticated
  USING (true);

CREATE POLICY "Users can insert trades"
  ON trades
  FOR INSERT
  TO authenticated
  WITH CHECK (true);

CREATE POLICY "Users can update trades"
  ON trades
  FOR UPDATE
  TO authenticated
  USING (true)
  WITH CHECK (true);

CREATE POLICY "Users can read all portfolio snapshots"
  ON portfolio_snapshots
  FOR SELECT
  TO authenticated
  USING (true);

CREATE POLICY "Users can insert portfolio snapshots"
  ON portfolio_snapshots
  FOR INSERT
  TO authenticated
  WITH CHECK (true);

CREATE INDEX IF NOT EXISTS idx_trades_strategy_id ON trades(strategy_id);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_timestamp ON portfolio_snapshots(timestamp DESC);