import { useEffect, useState } from 'react';
import { TrendingUp, TrendingDown, DollarSign, PieChart, AlertTriangle, Activity, Zap } from 'lucide-react';
import { getLatestPortfolioSnapshot } from '../lib/api';
import { PortfolioChart } from './PortfolioChart';
import type { PortfolioSnapshot } from '../lib/database.types';

export function PortfolioDashboard() {
  const [snapshot, setSnapshot] = useState<PortfolioSnapshot | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    try {
      const data = await getLatestPortfolioSnapshot();
      setSnapshot(data);
    } catch (error) {
      console.error('Error loading portfolio data:', error);
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  if (!snapshot) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500">No portfolio data available</p>
      </div>
    );
  }

  const utilizationRate = (snapshot.capital_deployed / snapshot.total_balance) * 100;
  const isProfitable = snapshot.total_pnl > 0;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900 mb-2">Portfolio Overview</h2>
        <p className="text-gray-600">Real-time portfolio metrics and performance indicators</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <MetricCard
          title="Total Balance"
          value={`$${snapshot.total_balance.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          icon={<DollarSign className="w-6 h-6" />}
          color="bg-blue-500"
        />

        <MetricCard
          title="Capital Deployed"
          value={`$${snapshot.capital_deployed.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          subtitle={`${utilizationRate.toFixed(1)}% utilized`}
          icon={<PieChart className="w-6 h-6" />}
          color="bg-purple-500"
        />

        <MetricCard
          title="Available Capital"
          value={`$${snapshot.available_capital.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          icon={<Activity className="w-6 h-6" />}
          color="bg-green-500"
        />

        <MetricCard
          title="Total P&L"
          value={`${isProfitable ? '+' : ''}$${snapshot.total_pnl.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          icon={isProfitable ? <TrendingUp className="w-6 h-6" /> : <TrendingDown className="w-6 h-6" />}
          color={isProfitable ? 'bg-emerald-500' : 'bg-red-500'}
          valueColor={isProfitable ? 'text-emerald-600' : 'text-red-600'}
        />
      </div>

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Risk Metrics</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <RiskMetric
            label="Maximum Drawdown"
            value={`${snapshot.max_drawdown?.toFixed(2) || '0.00'}%`}
            description="Largest peak-to-trough decline"
            icon={<AlertTriangle className="w-5 h-5 text-orange-500" />}
          />

          <RiskMetric
            label="Sharpe Ratio"
            value={snapshot.sharpe_ratio?.toFixed(2) || 'N/A'}
            description="Risk-adjusted return metric"
            icon={<Activity className="w-5 h-5 text-blue-500" />}
          />

          <RiskMetric
            label="Win Rate"
            value={snapshot.win_rate ? `${snapshot.win_rate.toFixed(1)}%` : 'N/A'}
            description="Percentage of profitable trades"
            icon={<TrendingUp className="w-5 h-5 text-green-500" />}
          />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <PortfolioChart />
        </div>

        <div className="space-y-6">
          <div className="bg-gradient-to-br from-gray-50 to-gray-100 rounded-lg border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Capital Allocation</h3>
            <div className="space-y-4">
              <AllocationBar
                label="Deployed Capital"
                value={snapshot.capital_deployed}
                total={snapshot.total_balance}
                color="bg-blue-500"
              />
              <AllocationBar
                label="Available Capital"
                value={snapshot.available_capital}
                total={snapshot.total_balance}
                color="bg-green-500"
              />
            </div>
          </div>

          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <Zap className="w-5 h-5 text-yellow-500" />
              Quick Stats
            </h3>
            <div className="space-y-3">
              <QuickStat
                label="Return on Capital"
                value={snapshot.total_balance > 0 ? `${((snapshot.total_pnl / snapshot.total_balance) * 100).toFixed(2)}%` : '0%'}
                color={snapshot.total_pnl > 0 ? 'text-emerald-600' : 'text-gray-600'}
              />
              <QuickStat
                label="Portfolio Growth"
                value={`$${snapshot.total_pnl.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
                color={snapshot.total_pnl > 0 ? 'text-emerald-600' : 'text-red-600'}
              />
              <QuickStat
                label="Capital Efficiency"
                value={`${(((snapshot.total_balance - snapshot.available_capital) / snapshot.total_balance) * 100).toFixed(1)}%`}
                color="text-blue-600"
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

interface MetricCardProps {
  title: string;
  value: string;
  subtitle?: string;
  icon: React.ReactNode;
  color: string;
  valueColor?: string;
}

function MetricCard({ title, value, subtitle, icon, color, valueColor }: MetricCardProps) {
  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
      <div className="flex items-start justify-between mb-4">
        <div className={`${color} text-white rounded-lg p-3`}>
          {icon}
        </div>
      </div>
      <div>
        <p className="text-sm font-medium text-gray-600 mb-1">{title}</p>
        <p className={`text-2xl font-bold ${valueColor || 'text-gray-900'}`}>{value}</p>
        {subtitle && <p className="text-xs text-gray-500 mt-1">{subtitle}</p>}
      </div>
    </div>
  );
}

interface RiskMetricProps {
  label: string;
  value: string;
  description: string;
  icon: React.ReactNode;
}

function RiskMetric({ label, value, description, icon }: RiskMetricProps) {
  return (
    <div className="flex items-start space-x-3">
      <div className="mt-1">{icon}</div>
      <div>
        <p className="text-sm font-medium text-gray-600">{label}</p>
        <p className="text-xl font-bold text-gray-900 mt-1">{value}</p>
        <p className="text-xs text-gray-500 mt-1">{description}</p>
      </div>
    </div>
  );
}

interface AllocationBarProps {
  label: string;
  value: number;
  total: number;
  color: string;
}

function AllocationBar({ label, value, total, color }: AllocationBarProps) {
  const percentage = (value / total) * 100;

  return (
    <div>
      <div className="flex justify-between items-center mb-2">
        <span className="text-sm font-medium text-gray-700">{label}</span>
        <span className="text-sm font-semibold text-gray-900">
          ${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          <span className="text-gray-500 ml-1">({percentage.toFixed(1)}%)</span>
        </span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-3">
        <div
          className={`${color} h-3 rounded-full transition-all duration-500`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}

interface QuickStatProps {
  label: string;
  value: string;
  color: string;
}

function QuickStat({ label, value, color }: QuickStatProps) {
  return (
    <div className="flex justify-between items-center py-2 border-b border-gray-100 last:border-0">
      <span className="text-sm text-gray-600">{label}</span>
      <span className={`text-sm font-semibold ${color}`}>{value}</span>
    </div>
  );
}
