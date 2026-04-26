import React from 'react';
import { Outlet, Link, useLocation } from 'react-router-dom';
import { Activity, BarChart3, Database, Settings, Radio, Waves, Globe2, LibraryBig, BrainCircuit, BadgeCheck, ScanSearch, Boxes, RefreshCcw, Loader2, RadioTower } from 'lucide-react';
import { useAppActions, useGlobalActivity, useUiState } from '../../app/store/AppStore';
import { cn } from '../../shared/utils';

const navigation = [
  { name: 'Mission Control', href: '/', icon: Activity },
  { name: 'Live Monitor', href: '/spectrum', icon: Activity },
  { name: 'Capture Lab', href: '/capture', icon: Database },
  { name: 'Dataset Builder', href: '/dataset-builder', icon: LibraryBig },
  { name: 'Training', href: '/training', icon: BrainCircuit },
  { name: 'Retraining', href: '/retraining', icon: RefreshCcw },
  { name: 'Validation', href: '/validation', icon: BadgeCheck },
  { name: 'Inference', href: '/inference', icon: ScanSearch },
  { name: 'Models', href: '/models', icon: Boxes },
  { name: 'Waterfall', href: '/waterfall', icon: BarChart3 },
  { name: 'Recordings', href: '/recordings', icon: Radio },
  { name: 'Demodulation', href: '/demodulation', icon: Waves },
  { name: 'KiwiSDR Map', href: '/kiwisdr', icon: Globe2 },
  { name: 'Settings', href: '/settings', icon: Settings },
];

export const AppLayout: React.FC = () => {
  const location = useLocation();
  const ui = useUiState();
  const globalActivity = useGlobalActivity();
  const { setUiState } = useAppActions();

  return (
    <div className="app-shell flex h-screen">
      {/* Sidebar */}
      <div className={cn(
        "app-sidebar flex flex-col border-r shadow-2xl transition-all duration-300",
        ui.sidebarCollapsed ? "w-16" : "w-64"
      )}>
        {/* Header */}
        <div className="border-b p-4" style={{ borderColor: 'var(--app-sidebar-border)' }}>
          <div className="flex items-center justify-between">
            {!ui.sidebarCollapsed && (
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.22em]" style={{ color: 'var(--app-accent)' }}>RF Lab</div>
                <h1 className="text-xl font-bold">Spectrum Lab</h1>
              </div>
            )}
            <button
              onClick={() => setUiState({ sidebarCollapsed: !ui.sidebarCollapsed })}
              className="rounded-md p-2 hover:bg-white/5"
              style={{ color: 'var(--app-sidebar-text)' }}
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
                  "flex items-center rounded-2xl px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-amber-300 text-slate-950"
                    : "hover:bg-white/5"
                )}
                style={isActive ? { background: 'var(--app-accent)', color: 'var(--app-accent-foreground)' } : { color: 'var(--app-sidebar-text)' }}
              >
                <item.icon className="w-5 h-5 mr-3" />
                {!ui.sidebarCollapsed && item.name}
              </Link>
            );
          })}
        </nav>

        {/* Footer */}
        <div className="border-t p-4" style={{ borderColor: 'var(--app-sidebar-border)' }}>
          <div className="text-xs" style={{ color: 'var(--app-sidebar-muted)' }}>
            {!ui.sidebarCollapsed && "Acquisition + Dataset + QC"}
          </div>
        </div>
      </div>

      {/* Main content */}
      <div className="flex flex-1 flex-col overflow-hidden app-shell">
        {globalActivity?.visible && (
          <div className="pointer-events-none fixed bottom-6 right-6 z-50 max-w-[calc(100vw-2rem)]">
            <div
              className="w-[min(28rem,calc(100vw-2rem))] overflow-hidden rounded-[1.35rem] border border-white/20 text-white shadow-[0_22px_70px_rgba(15,23,42,0.30)] backdrop-blur-2xl"
              style={{ background: 'linear-gradient(135deg, rgba(15,23,42,0.78), rgba(30,41,59,0.56))' }}
            >
              <div className="flex items-center gap-3 px-5 py-4">
                <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-white/15 bg-white/10">
                  {globalActivity.kind === 'capturing' ? (
                    <RadioTower className="h-5 w-5 animate-pulse text-emerald-300" />
                  ) : (
                    <Loader2 className="h-5 w-5 animate-spin text-amber-300" />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-sm font-semibold">
                    <span className="h-2 w-2 rounded-full bg-emerald-300 shadow-[0_0_18px_rgba(110,231,183,0.85)]" />
                    <span className="truncate">{globalActivity.title}</span>
                  </div>
                  {globalActivity.detail && <div className="mt-1 truncate text-xs text-slate-200/90">{globalActivity.detail}</div>}
                </div>
              </div>
              <div className="h-1 overflow-hidden bg-white/10">
                <div className="h-full w-1/2 animate-[pulse_1.4s_ease-in-out_infinite] rounded-full bg-gradient-to-r from-amber-300 via-emerald-300 to-sky-300" />
              </div>
            </div>
          </div>
        )}

        {/* Top bar */}
        <header className="app-surface border-b px-6 py-4 shadow-sm backdrop-blur">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">
              {navigation.find(item => item.href === location.pathname)?.name || 'Spectrum Lab'}
            </h2>
            <div className="flex items-center space-x-4">
              <select
                value={ui.theme}
                onChange={(event) => setUiState({ theme: event.target.value as typeof ui.theme })}
                className="rounded-full border px-3 py-2 text-sm"
                style={{ background: 'var(--app-surface-strong)', borderColor: 'var(--app-border)', color: 'var(--app-text)' }}
              >
                <option value="light">White</option>
                <option value="dark">Dark</option>
                <option value="laboratory">Laboratory</option>
              </select>
              {/* Status indicator */}
              <div className="flex items-center space-x-2">
                <div className="h-2 w-2 rounded-full bg-emerald-500"></div>
                <span className="text-sm app-muted-text">Shared backend active</span>
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
