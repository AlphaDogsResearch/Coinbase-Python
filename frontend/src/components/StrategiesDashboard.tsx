import { useEffect, useState } from 'react';
import { TrendingUp, Activity, DollarSign, Target } from 'lucide-react';
import { getStrategiesWithStats } from '../lib/api';
import { StrategyDetail } from './StrategyDetail';
import type { StrategyWithStats } from '../lib/api';

export function StrategiesDashboard() {
  const [strategies, setStrategies] = useState<StrategyWithStats[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState<StrategyWithStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    try {
      const data = await getStrategiesWithStats();
      setStrategies(data);
      if (data.length > 0) {
        setSelectedStrategy(data[0]);
      }
    } catch (error) {
      console.error('Error loading strategies:', error);
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

  if (strategies.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500">No strategies available</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-gray-900 mb-2">Strategy Performance</h2>
        <p className="text-gray-600">Detailed breakdown of each trading strategy</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <SummaryCard
          label="Active Strategies"
          value={strategies.filter((s) => s.status === 'active').length}
          icon={<Activity className="w-5 h-5" />}
          color="text-blue-600"
          bgColor="bg-blue-50"
        />
        <SummaryCard
          label="Total Capital Allocated"
          value={`$${strategies.reduce((sum, s) => sum + s.capital_allocated, 0).toLocaleString()}`}
          icon={<DollarSign className="w-5 h-5" />}
          color="text-green-600"
          bgColor="bg-green-50"
        />
        <SummaryCard
          label="Total Trades"
          value={strategies.reduce((sum, s) => sum + s.totalTrades, 0)}
          icon={<Target className="w-5 h-5" />}
          color="text-purple-600"
          bgColor="bg-purple-50"
        />
        <SummaryCard
          label="Combined P&L"
          value={`$${strategies.reduce((sum, s) => sum + s.totalPnL, 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}`}
          icon={<TrendingUp className="w-5 h-5" />}
          color="text-emerald-600"
          bgColor="bg-emerald-50"
        />
      </div>

      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        <div className="flex overflow-x-auto border-b border-gray-200">
          {strategies.map((strategy) => (
            <StrategyTab
              key={strategy.id}
              strategy={strategy}
              isActive={selectedStrategy?.id === strategy.id}
              onClick={() => setSelectedStrategy(strategy)}
            />
          ))}
        </div>

        <div className="p-6">
          {selectedStrategy && <StrategyDetail strategy={selectedStrategy} />}
        </div>
      </div>
    </div>
  );
}

interface SummaryCardProps {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  color: string;
  bgColor: string;
}

function SummaryCard({ label, value, icon, color, bgColor }: SummaryCardProps) {
  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
      <div className={`${bgColor} ${color} rounded-lg p-2 inline-flex mb-3`}>
        {icon}
      </div>
      <p className="text-sm font-medium text-gray-600">{label}</p>
      <p className="text-xl font-bold text-gray-900 mt-1">{value}</p>
    </div>
  );
}

interface StrategyTabProps {
  strategy: StrategyWithStats;
  isActive: boolean;
  onClick: () => void;
}

function StrategyTab({ strategy, isActive, onClick }: StrategyTabProps) {
  const statusDot = {
    active: 'bg-green-500',
    paused: 'bg-yellow-500',
    inactive: 'bg-gray-500',
  };

  return (
    <button
      onClick={onClick}
      className={`px-6 py-4 font-medium text-sm whitespace-nowrap border-b-2 transition-colors ${
        isActive
          ? 'border-blue-600 text-blue-600 bg-blue-50/50'
          : 'border-transparent text-gray-600 hover:text-gray-900 hover:bg-gray-50/50'
      }`}
    >
      <div className="flex items-center gap-2">
        <div className={`w-2 h-2 rounded-full ${statusDot[strategy.status as keyof typeof statusDot]}`}></div>
        <span>{strategy.name}</span>
      </div>
    </button>
  );
}
