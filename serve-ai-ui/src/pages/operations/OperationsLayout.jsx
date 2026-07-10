/**
 * OperationsLayout — Container for the AI Operations Console.
 * Renders sub-navigation tabs and the active child route via <Outlet />.
 */
import { Outlet, NavLink, useLocation } from 'react-router-dom';
import { cn } from '../../lib/utils';

const TABS = [
  { label: 'Overview', path: '/operations/overview' },
  { label: 'Conversations', path: '/operations/conversations' },
  { label: 'Pipeline', path: '/operations/pipeline' },
  { label: 'Agents & Tools', path: '/operations/agents' },
  { label: 'Evaluation', path: '/operations/evaluation' },
];

export function OperationsLayout() {
  const location = useLocation();

  return (
    <div className="flex flex-col h-full">
      {/* Tab bar */}
      <div className="border-b border-slate-200 bg-white px-4 sm:px-6">
        <nav className="flex gap-1 -mb-px overflow-x-auto" aria-label="Operations tabs">
          {TABS.map((tab) => {
            const isActive = location.pathname === tab.path;
            return (
              <NavLink
                key={tab.path}
                to={tab.path}
                className={cn(
                  'px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 transition-colors',
                  isActive
                    ? 'border-blue-600 text-blue-700'
                    : 'border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300'
                )}
              >
                {tab.label}
              </NavLink>
            );
          })}
        </nav>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto">
        <Outlet />
      </div>
    </div>
  );
}

export default OperationsLayout;
