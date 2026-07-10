/**
 * Sidebar — Capability-driven navigation sidebar.
 * Renders only the nav items the user has access to.
 * Supports collapsible parent items with children.
 */
import { useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import {
  MessageSquare,
  Activity,
  MessagesSquare,
  TrendingUp,
  Bot,
  BarChart3,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import { cn } from '../../lib/utils';

/** Map icon string names to Lucide components */
const ICON_MAP = {
  MessageSquare,
  Activity,
  MessagesSquare,
  TrendingUp,
  Bot,
  BarChart3,
};

function NavItem({ item, isChild = false }) {
  const location = useLocation();
  const [expanded, setExpanded] = useState(() => {
    // Auto-expand if current path matches this item or any child
    if (item.children) {
      return (
        location.pathname === item.path ||
        item.children.some((c) => location.pathname.startsWith(c.path))
      );
    }
    return false;
  });

  const Icon = ICON_MAP[item.icon] || MessageSquare;
  const hasChildren = item.children && item.children.length > 0;

  if (hasChildren) {
    return (
      <div>
        <button
          onClick={() => setExpanded(!expanded)}
          className={cn(
            'w-full flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors',
            'text-slate-600 hover:text-slate-900 hover:bg-slate-100',
            location.pathname.startsWith(item.path) && 'text-slate-900 bg-slate-100'
          )}
          aria-expanded={expanded}
        >
          <Icon className="w-4 h-4 flex-shrink-0" />
          <span className="flex-1 text-left">{item.label}</span>
          {expanded ? (
            <ChevronDown className="w-4 h-4 text-slate-400" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-400" />
          )}
        </button>
        {expanded && (
          <div className="ml-4 mt-1 space-y-1 border-l border-slate-200 pl-3">
            {item.children.map((child) => (
              <NavItem key={child.id} item={child} isChild />
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <NavLink
      to={item.path}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors',
          isChild ? 'text-slate-500 hover:text-slate-900 hover:bg-slate-50' : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100',
          isActive && 'text-blue-700 bg-blue-50 hover:bg-blue-50 hover:text-blue-700'
        )
      }
    >
      {!isChild && <Icon className="w-4 h-4 flex-shrink-0" />}
      {isChild && <span className="w-4" />}
      <span>{item.label}</span>
    </NavLink>
  );
}

export function Sidebar({ navItems }) {
  return (
    <aside className="hidden md:flex md:flex-col md:w-60 border-r border-slate-200 bg-white">
      <nav className="flex-1 px-3 py-4 space-y-1" aria-label="Main navigation">
        {navItems.map((item) => (
          <NavItem key={item.id} item={item} />
        ))}
      </nav>
    </aside>
  );
}

export default Sidebar;
