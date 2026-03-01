/*
  # Update RLS Policies for Public Access

  1. Security Changes
    - Update existing RLS policies to allow public read access (for demo/testing)
    - Maintain security for write operations
*/

DROP POLICY IF EXISTS "Users can read all strategies" ON strategies;
DROP POLICY IF EXISTS "Users can read all trades" ON trades;
DROP POLICY IF EXISTS "Users can read all portfolio snapshots" ON portfolio_snapshots;

CREATE POLICY "Public can read strategies"
  ON strategies
  FOR SELECT
  TO anon, authenticated
  USING (true);

CREATE POLICY "Public can read trades"
  ON trades
  FOR SELECT
  TO anon, authenticated
  USING (true);

CREATE POLICY "Public can read portfolio snapshots"
  ON portfolio_snapshots
  FOR SELECT
  TO anon, authenticated
  USING (true);