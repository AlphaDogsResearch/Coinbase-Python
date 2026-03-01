import { useState } from 'react';
import { BarChart3, Layers, TrendingUp } from 'lucide-react';
import { PortfolioDashboard } from './components/PortfolioDashboard';
import { StrategiesDashboard } from './components/StrategiesDashboard';

type View = 'portfolio' | 'strategies';

function App() {
  const [activeView, setActiveView] = useState<View>('portfolio');

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100">
      <nav className="bg-white border-b border-gray-200 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center space-x-3">
              <div className="bg-gradient-to-br from-blue-500 to-blue-600 rounded-lg p-2">
                <TrendingUp className="w-6 h-6 text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-gray-900">AlgoTrade Dashboard</h1>
                <p className="text-xs text-gray-500">Real-time trading analytics</p>
              </div>
            </div>

            <div className="flex space-x-2">
              <NavButton
                icon={<BarChart3 className="w-5 h-5" />}
                label="Portfolio"
                isActive={activeView === 'portfolio'}
                onClick={() => setActiveView('portfolio')}
              />
              <NavButton
                icon={<Layers className="w-5 h-5" />}
                label="Strategies"
                isActive={activeView === 'strategies'}
                onClick={() => setActiveView('strategies')}
              />
            </div>
          </div>
        </div>
      </nav>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {activeView === 'portfolio' ? <PortfolioDashboard /> : <StrategiesDashboard />}
      </main>
    </div>
  );
}

interface NavButtonProps {
  icon: React.ReactNode;
  label: string;
  isActive: boolean;
  onClick: () => void;
}

function NavButton({ icon, label, isActive, onClick }: NavButtonProps) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center space-x-2 px-4 py-2 rounded-lg font-medium transition-all ${
        isActive
          ? 'bg-blue-50 text-blue-600 shadow-sm'
          : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
      }`}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

export default App;
