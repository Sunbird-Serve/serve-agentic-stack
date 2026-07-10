/**
 * MobileNav — Collapsed navigation for viewports < 768px.
 * Shows a bottom navigation bar with top-level items.
 */
import { NavLink } from 'react-router-dom';
import {
  MessageSquare,
  Activity,
  MessagesSquare,
  TrendingUp,
  Bot,
  BarChart3,
} from 'lucide-react';
import { cn } from '../../lib/utils';

const ICON_MAP = {
  MessageSquare,
  Activity,
  MessagesSquare,
  TrendingUp,
  Bot,
  BarChart3,
};

export function MobileNav({ navItems }) {
  // Show only top-level items in mobile nav
  const topItems = navItems.map((item) => ({
    id: item.id,
    label: item.label,
    icon: item.icon,
    // For parent items with children, link to first child path
    path: item.children?.length ? item.children[0].path : item.path,
  }));

  return (
    <nav
      className="md:hidden fixed bottom-0 left-0 right-0 z-50 bg-white border-t border-slate-200"
      aria-label="Mobile navigation"
    >
      <div className="flex items-center justify-around px-2 py-2">
        {topItems.map((item) => {
          const Icon = ICON_MAP[item.icon] || MessageSquare;
          return (
            <NavLink
              key={item.id}
              to={item.path}
              className={({ isActive }) =>
                cn(
                  'flex flex-col items-center gap-1 px-3 py-1.5 rounded-md text-xs font-medium transition-colors',
                  isActive
                    ? 'text-blue-700'
                    : 'text-slate-500 hover:text-slate-900'
                )
              }
            >
              <Icon className="w-5 h-5" />
              <span>{item.label}</span>
            </NavLink>
          );
        })}
      </div>
    </nav>
  );
}

export default MobileNav;
