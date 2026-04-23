import React from 'react';
import { Outlet, Link, useLocation } from 'react-router-dom';
import { Activity, BarChart3, Database, Settings, Radio, Waves, Globe2 } from 'lucide-react';
import { useAppActions, useUiState } from '../../app/store/AppStore';
import { cn } from '../../shared/utils';

const navigation = [
  { name: 'Spectrum', href: '/', icon: Activity },
  { name: 'Waterfall', href: '/waterfall', icon: BarChart3 },
  { name: 'Recordings', href: '/recordings', icon: Radio },
  { name: 'Demodulation', href: '/demodulation', icon: Waves },
  { name: 'Signal Analysis', href: '/modulated-analysis', icon: Database },
  { name: 'KiwiSDR Map', href: '/kiwisdr', icon: Globe2 },
  { name: 'Settings', href: '/settings', icon: Settings },
];

export const AppLayout: React.FC = () => {
  const location = useLocation();
  const ui = useUiState();
  const { setUiState } = useAppActions();

  return (
    <div className="h-screen flex bg-gray-50">
      {/* Sidebar */}
      <div className={cn(
        "bg-white shadow-lg transition-all duration-300 flex flex-col",
        ui.sidebarCollapsed ? "w-16" : "w-64"
      )}>
        {/* Header */}
        <div className="p-4 border-b border-gray-200">
          <div className="flex items-center justify-between">
            {!ui.sidebarCollapsed && (
              <h1 className="text-xl font-bold text-gray-900">Spectrum Lab</h1>
            )}
            <button
              onClick={() => setUiState({ sidebarCollapsed: !ui.sidebarCollapsed })}
              className="p-2 rounded-md hover:bg-gray-100"
            >
              <Activity className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-4 space-y-2">
          {navigation.map((item) => {
            const isActive = location.pathname === item.href;
            return (
              <Link
                key={item.name}
                to={item.href}
                className={cn(
                  "flex items-center px-3 py-2 rounded-md text-sm font-medium transition-colors",
                  isActive
                    ? "bg-blue-100 text-blue-700"
                    : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
                )}
              >
                <item.icon className="w-5 h-5 mr-3" />
                {!ui.sidebarCollapsed && item.name}
              </Link>
            );
          })}
        </nav>

        {/* Footer */}
        <div className="p-4 border-t border-gray-200">
          <div className="text-xs text-gray-500">
            {!ui.sidebarCollapsed && "Spectrum Lab v1.0"}
          </div>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar */}
        <header className="bg-white shadow-sm border-b border-gray-200 px-6 py-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-gray-900">
              {navigation.find(item => item.href === location.pathname)?.name || 'Spectrum Lab'}
            </h2>
            <div className="flex items-center space-x-4">
              {/* Status indicator */}
              <div className="flex items-center space-x-2">
                <div className="w-2 h-2 bg-green-500 rounded-full"></div>
                <span className="text-sm text-gray-600">Connected</span>
              </div>
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
};
