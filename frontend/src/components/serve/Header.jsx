/**
 * SERVE AI - Header Component
 * Main navigation header with logo and role switcher
 */
import { Users, Settings, MessageSquare, ChevronDown } from 'lucide-react';
import { Button } from '../ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu';

const ROLES = {
  volunteer: { label: 'Volunteer', icon: MessageSquare, color: 'text-blue-600' },
  ops: { label: 'Ops / Coordinator', icon: Users, color: 'text-emerald-600' },
  admin: { label: 'Tech Admin', icon: Settings, color: 'text-slate-600' },
};

export const Header = ({ currentRole, onRoleChange }) => {
  const currentRoleConfig = ROLES[currentRole];
  const RoleIcon = currentRoleConfig?.icon || MessageSquare;

  return (
    <header className="serve-header" data-testid="main-header">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo and Brand */}
          <div className="flex items-center gap-3" data-testid="brand-logo">
            <div className="w-10 h-10 rounded-lg dpga-gradient flex items-center justify-center">
              <span className="text-white font-bold text-lg">S</span>
            </div>
            <div>
              <h1 className="text-lg font-semibold text-slate-900 tracking-tight">
                SERVE AI
              </h1>
              <p className="text-xs text-slate-500">Volunteer Management Platform</p>
            </div>
          </div>

          {/* Role Switcher */}
          <div className="flex items-center gap-4">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button 
                  variant="outline" 
                  className="flex items-center gap-2"
                  data-testid="role-switcher-trigger"
                >
                  <RoleIcon className={`w-4 h-4 ${currentRoleConfig?.color}`} />
                  <span className="hidden sm:inline">{currentRoleConfig?.label}</span>
                  <ChevronDown className="w-4 h-4 text-slate-400" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                {Object.entries(ROLES).map(([key, config]) => {
                  const Icon = config.icon;
                  return (
                    <DropdownMenuItem
                      key={key}
                      onClick={() => onRoleChange(key)}
                      className="flex items-center gap-2 cursor-pointer"
                      data-testid={`role-option-${key}`}
                    >
                      <Icon className={`w-4 h-4 ${config.color}`} />
                      <span>{config.label}</span>
                      {currentRole === key && (
                        <span className="ml-auto text-xs text-slate-400">Active</span>
                      )}
                    </DropdownMenuItem>
                  );
                })}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </div>
    </header>
  );
};

export default Header;
