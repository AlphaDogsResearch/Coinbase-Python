import { useEffect, useState } from 'react';
import { getPortfolioHistory } from '../lib/api';
import type { PortfolioSnapshot } from '../lib/database.types';

export function PortfolioChart() {
  const [data, setData] = useState<PortfolioSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [chartType, setChartType] = useState<'balance' | 'pnl'>('balance');

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    try {
      const history = await getPortfolioHistory(14);
      setData(history);
    } catch (error) {
      console.error('Error loading portfolio history:', error);
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-6 text-center">
        <p className="text-gray-500">No portfolio data available</p>
      </div>
    );
  }

  const minBalance = Math.min(...data.map((d) => d.total_balance));
  const maxBalance = Math.max(...data.map((d) => d.total_balance));
  const rangeBalance = maxBalance - minBalance;
  const canvasHeight = 300;
  const chartPadding = 40;
  const chartWidth = Math.max(800, data.length * 80);

  const getBalance = (d: PortfolioSnapshot) => (chartType === 'balance' ? d.total_balance : d.total_pnl);
  const minValue = Math.min(...data.map(getBalance));
  const maxValue = Math.max(...data.map(getBalance));
  const range = maxValue - minValue || 1;

  const points = data.map((d, i) => {
    const value = getBalance(d);
    const x = (chartWidth / (data.length - 1 || 1)) * i;
    const y = canvasHeight - chartPadding - ((value - minValue) / range) * (canvasHeight - 2 * chartPadding);
    return { x, y, value, date: new Date(d.timestamp) };
  });

  const pathData = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');

  const maxPoint = points.reduce((max, p) => (p.value > max.value ? p : max));
  const minPoint = points.reduce((min, p) => (p.value < min.value ? p : min));

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-lg font-semibold text-gray-900">Portfolio Performance</h3>
          <p className="text-sm text-gray-600">Last 14 days</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setChartType('balance')}
            className={`px-3 py-1 text-sm font-medium rounded transition-colors ${
              chartType === 'balance'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            Balance
          </button>
          <button
            onClick={() => setChartType('pnl')}
            className={`px-3 py-1 text-sm font-medium rounded transition-colors ${
              chartType === 'pnl'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            P&L
          </button>
        </div>
      </div>

      <div className="overflow-x-auto">
        <svg width={chartWidth} height={canvasHeight} className="mx-auto">
          <defs>
            <linearGradient id="balanceGradient" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.3" />
              <stop offset="100%" stopColor="#3b82f6" stopOpacity="0" />
            </linearGradient>
          </defs>

          {points.length > 1 && (
            <>
              <path d={`${pathData} L ${points[points.length - 1].x} ${canvasHeight - chartPadding}`} fill="url(#balanceGradient)" />
              <path d={pathData} stroke="#3b82f6" strokeWidth="2" fill="none" />
            </>
          )}

          {points.map((p, i) => (
            <g key={i}>
              <circle cx={p.x} cy={p.y} r="4" fill="#3b82f6" />
            </g>
          ))}

          {maxPoint && (
            <g>
              <circle cx={maxPoint.x} cy={maxPoint.y} r="6" fill="#10b981" />
              <text x={maxPoint.x} y={maxPoint.y - 15} textAnchor="middle" className="text-xs fill-gray-600 font-semibold">
                High: ${maxPoint.value.toFixed(0)}
              </text>
            </g>
          )}

          {minPoint && (
            <g>
              <circle cx={minPoint.x} cy={minPoint.y} r="6" fill="#ef4444" />
              <text x={minPoint.x} y={minPoint.y + 25} textAnchor="middle" className="text-xs fill-gray-600 font-semibold">
                Low: ${minPoint.value.toFixed(0)}
              </text>
            </g>
          )}

          {points.map((p, i) => {
            if (i % Math.ceil(data.length / 4) === 0 || i === data.length - 1) {
              return (
                <g key={`label-${i}`}>
                  <line x1={p.x} y1={canvasHeight - chartPadding} x2={p.x} y2={canvasHeight - chartPadding + 5} stroke="#e5e7eb" />
                  <text
                    x={p.x}
                    y={canvasHeight - chartPadding + 20}
                    textAnchor="middle"
                    className="text-xs fill-gray-500"
                  >
                    {p.date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                  </text>
                </g>
              );
            }
            return null;
          })}
        </svg>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6 pt-6 border-t border-gray-200">
        <ChartStat
          label="Current"
          value={`$${points[points.length - 1].value.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`}
          color="text-blue-600"
        />
        <ChartStat
          label="Highest"
          value={`$${maxPoint.value.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`}
          color="text-green-600"
        />
        <ChartStat
          label="Lowest"
          value={`$${minPoint.value.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`}
          color="text-red-600"
        />
        <ChartStat
          label="Change"
          value={`${
            points[points.length - 1].value - points[0].value > 0 ? '+' : ''
          }$${(points[points.length - 1].value - points[0].value).toLocaleString('en-US', {
            minimumFractionDigits: 0,
            maximumFractionDigits: 0,
          })}`}
          color={points[points.length - 1].value - points[0].value > 0 ? 'text-green-600' : 'text-red-600'}
        />
      </div>
    </div>
  );
}

interface ChartStatProps {
  label: string;
  value: string;
  color: string;
}

function ChartStat({ label, value, color }: ChartStatProps) {
  return (
    <div>
      <p className="text-xs font-medium text-gray-600 mb-1">{label}</p>
      <p className={`text-lg font-bold ${color}`}>{value}</p>
    </div>
  );
}
