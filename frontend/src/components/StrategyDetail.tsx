import { useEffect, useState } from 'react';
import { TrendingUp, TrendingDown, Target, DollarSign, PieChart, Zap } from 'lucide-react';
import { getTradesByStrategy } from '../lib/api';
import type { StrategyWithStats } from '../lib/api';
import type { Trade } from '../lib/database.types';

interface StrategyDetailProps {
  strategy: StrategyWithStats;
}

export function StrategyDetail({ strategy }: StrategyDetailProps) {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadTrades();
  }, [strategy.id]);

  async function loadTrades() {
    try {
      const data = await getTradesByStrategy(strategy.id);
      setTrades(data);
    } catch (error) {
      console.error('Error loading trades:', error);
    } finally {
      setLoading(false);
    }
  }

  const closedTrades = trades.filter((t) => t.status === 'closed');
  const openTrades = trades.filter((t) => t.status === 'open');
  const totalCapitalUsed = openTrades.reduce((sum, t) => sum + t.entry_price * t.quantity, 0);
  const avgWinSize = closedTrades.filter((t) => (t.pnl || 0) > 0).reduce((sum, t) => sum + (t.pnl || 0), 0) / Math.max(closedTrades.filter((t) => (t.pnl || 0) > 0).length, 1);
  const avgLossSize = Math.abs(closedTrades.filter((t) => (t.pnl || 0) < 0).reduce((sum, t) => sum + (t.pnl || 0), 0) / Math.max(closedTrades.filter((t) => (t.pnl || 0) < 0).length, 1));
  const profitFactor = avgWinSize > 0 ? (closedTrades.filter((t) => (t.pnl || 0) > 0).length * avgWinSize) / Math.max(closedTrades.filter((t) => (t.pnl || 0) < 0).length * avgLossSize, 1) : 0;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <DetailMetricCard
          label="Capital Allocated"
          value={`$${strategy.capital_allocated.toLocaleString()}`}
          icon={<DollarSign className="w-5 h-5" />}
          color="bg-blue-500"
        />
        <DetailMetricCard
          label="Capital Deployed"
          value={`$${totalCapitalUsed.toLocaleString('en-US', { maximumFractionDigits: 0 })}`}
          subtitle={`${((totalCapitalUsed / strategy.capital_allocated) * 100).toFixed(1)}% utilized`}
          icon={<PieChart className="w-5 h-5" />}
          color="bg-purple-500"
        />
        <DetailMetricCard
          label="Total P&L"
          value={`${strategy.totalPnL > 0 ? '+' : ''}$${strategy.totalPnL.toLocaleString('en-US', { minimumFractionDigits: 2 })}`}
          icon={strategy.totalPnL > 0 ? <TrendingUp className="w-5 h-5" /> : <TrendingDown className="w-5 h-5" />}
          color={strategy.totalPnL > 0 ? 'bg-emerald-500' : 'bg-red-500'}
          valueColor={strategy.totalPnL > 0 ? 'text-emerald-600' : 'text-red-600'}
        />
        <DetailMetricCard
          label="Win Rate"
          value={`${strategy.winRate.toFixed(1)}%`}
          icon={<Target className="w-5 h-5" />}
          color="bg-orange-500"
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatBox label="Total Trades" value={strategy.totalTrades} color="text-blue-600" />
        <StatBox label="Open Trades" value={openTrades.length} color="text-yellow-600" />
        <StatBox label="Closed Trades" value={closedTrades.length} color="text-green-600" />
        <StatBox label="Profit Factor" value={profitFactor.toFixed(2)} color="text-purple-600" />
      </div>

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Trade History</h3>
        {trades.length === 0 ? (
          <p className="text-sm text-gray-500 py-8">No trades yet</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 bg-gray-50">
                  <th className="text-left py-3 px-4 font-semibold text-gray-700">Symbol</th>
                  <th className="text-left py-3 px-4 font-semibold text-gray-700">Side</th>
                  <th className="text-right py-3 px-4 font-semibold text-gray-700">Quantity</th>
                  <th className="text-right py-3 px-4 font-semibold text-gray-700">Entry Price</th>
                  <th className="text-right py-3 px-4 font-semibold text-gray-700">Exit Price</th>
                  <th className="text-right py-3 px-4 font-semibold text-gray-700">Entry Value</th>
                  <th className="text-right py-3 px-4 font-semibold text-gray-700">P&L</th>
                  <th className="text-right py-3 px-4 font-semibold text-gray-700">Return %</th>
                  <th className="text-left py-3 px-4 font-semibold text-gray-700">Status</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((trade) => (
                  <TradeDetailRow key={trade.id} trade={trade} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {openTrades.length > 0 && (
        <div className="bg-blue-50 rounded-lg border border-blue-200 p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <Zap className="w-5 h-5 text-blue-600" />
            Open Positions
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-blue-200">
                  <th className="text-left py-3 px-4 font-semibold text-gray-700">Symbol</th>
                  <th className="text-right py-3 px-4 font-semibold text-gray-700">Quantity</th>
                  <th className="text-right py-3 px-4 font-semibold text-gray-700">Entry Price</th>
                  <th className="text-right py-3 px-4 font-semibold text-gray-700">Entry Value</th>
                  <th className="text-left py-3 px-4 font-semibold text-gray-700">Entry Time</th>
                </tr>
              </thead>
              <tbody>
                {openTrades.map((trade) => (
                  <tr key={trade.id} className="border-b border-blue-100 hover:bg-blue-100/50 transition-colors">
                    <td className="py-3 px-4 font-medium text-gray-900">{trade.symbol}</td>
                    <td className="py-3 px-4 text-right text-gray-900">{trade.quantity.toLocaleString()}</td>
                    <td className="py-3 px-4 text-right text-gray-900">${trade.entry_price.toFixed(2)}</td>
                    <td className="py-3 px-4 text-right font-semibold text-blue-600">
                      ${(trade.entry_price * trade.quantity).toLocaleString('en-US', { minimumFractionDigits: 2 })}
                    </td>
                    <td className="py-3 px-4 text-sm text-gray-600">
                      {new Date(trade.entry_time).toLocaleDateString()} {new Date(trade.entry_time).toLocaleTimeString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

interface DetailMetricCardProps {
  label: string;
  value: string;
  subtitle?: string;
  icon: React.ReactNode;
  color: string;
  valueColor?: string;
}

function DetailMetricCard({ label, value, subtitle, icon, color, valueColor }: DetailMetricCardProps) {
  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
      <div className="flex items-start justify-between mb-3">
        <div className={`${color} text-white rounded-lg p-2`}>
          {icon}
        </div>
      </div>
      <p className="text-xs font-medium text-gray-600 mb-1">{label}</p>
      <p className={`text-xl font-bold ${valueColor || 'text-gray-900'}`}>{value}</p>
      {subtitle && <p className="text-xs text-gray-500 mt-1">{subtitle}</p>}
    </div>
  );
}

interface StatBoxProps {
  label: string;
  value: number | string;
  color: string;
}

function StatBox({ label, value, color }: StatBoxProps) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <p className="text-xs font-medium text-gray-600 mb-2">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>{value}</p>
    </div>
  );
}

interface TradeDetailRowProps {
  trade: Trade;
}

function TradeDetailRow({ trade }: TradeDetailRowProps) {
  const entryValue = trade.entry_price * trade.quantity;
  const exitValue = trade.exit_price && trade.status === 'closed' ? trade.exit_price * trade.quantity : null;
  const returnPercent = exitValue && entryValue > 0 ? ((exitValue - entryValue) / entryValue) * 100 : null;
  const isProfitable = (trade.pnl || 0) > 0;
  const isOpen = trade.status === 'open';

  return (
    <tr className={`border-b border-gray-100 hover:bg-gray-50 transition-colors ${isOpen ? 'bg-yellow-50' : ''}`}>
      <td className="py-3 px-4 font-medium text-gray-900">{trade.symbol}</td>
      <td className="py-3 px-4 text-left">
        <span className={`px-2 py-1 text-xs font-medium rounded ${trade.side === 'buy' ? 'bg-blue-100 text-blue-800' : 'bg-orange-100 text-orange-800'}`}>
          {trade.side.toUpperCase()}
        </span>
      </td>
      <td className="py-3 px-4 text-right text-gray-900">{trade.quantity.toLocaleString()}</td>
      <td className="py-3 px-4 text-right text-gray-900">${trade.entry_price.toFixed(4)}</td>
      <td className="py-3 px-4 text-right text-gray-900">{trade.exit_price ? `$${trade.exit_price.toFixed(4)}` : '-'}</td>
      <td className="py-3 px-4 text-right font-semibold text-gray-900">
        ${entryValue.toLocaleString('en-US', { minimumFractionDigits: 2 })}
      </td>
      <td className="py-3 px-4 text-right">
        {trade.pnl !== null ? (
          <span className={`font-semibold ${isProfitable ? 'text-emerald-600' : 'text-red-600'}`}>
            {isProfitable ? '+' : ''}${trade.pnl.toFixed(2)}
          </span>
        ) : (
          <span className="text-gray-400">-</span>
        )}
      </td>
      <td className="py-3 px-4 text-right">
        {returnPercent !== null ? (
          <span className={`font-semibold ${returnPercent > 0 ? 'text-emerald-600' : 'text-red-600'}`}>
            {returnPercent > 0 ? '+' : ''}{returnPercent.toFixed(2)}%
          </span>
        ) : (
          <span className="text-gray-400">-</span>
        )}
      </td>
      <td className="py-3 px-4 text-left">
        <span className={`px-2 py-1 text-xs font-medium rounded ${isOpen ? 'bg-blue-100 text-blue-800' : 'bg-gray-100 text-gray-800'}`}>
          {trade.status.toUpperCase()}
        </span>
      </td>
    </tr>
  );
}
