/**
 * AppHeader — Top bar with dynamic tenant branding, persona badge, and user controls.
 * Reads branding from BrandingContext (data-driven, no hardcoded tenant logic).
 */
import { LogOut, User } from 'lucide-react';
import { Button } from '../ui/button';
import { useBranding } from '../../context/BrandingContext';

const PERSONA_LABELS = {
  Super_Admin: 'Super Admin',
  Need_Admin: 'Need Admin',
  Volunteer_Admin: 'Volunteer Admin',
  Volunteer_Coordinator: 'Volunteer Coordinator',
  Need_Coordinator: 'Need Coordinator',
  Volunteer: 'Volunteer',
};

export function AppHeader({ user, persona, onLogout }) {
  const { appName, logoUrl, primaryColor } = useBranding();
  const personaLabel = PERSONA_LABELS[persona] || persona || 'User';

  return (
    <header className="border-b border-slate-200 bg-white sticky top-0 z-50">
      <div className="flex items-center justify-between h-14 px-4 sm:px-6">
        {/* Brand */}
        <div className="flex items-center gap-3">
          {logoUrl ? (
            <img src={logoUrl} alt={appName} className="w-8 h-8 rounded-lg object-contain" />
          ) : (
            <div
              className="w-8 h-8 rounded-lg flex items-center justify-center"
              style={{ backgroundColor: primaryColor }}
            >
              <span className="text-white font-bold text-sm">
                {appName?.charAt(0) || 'S'}
              </span>
            </div>
          )}
          <h1 className="text-base font-semibold text-slate-900 tracking-tight">
            {appName}
          </h1>
        </div>

        {/* User Info */}
        <div className="flex items-center gap-3">
          {/* Persona Badge */}
          <div className="hidden sm:flex items-center px-2.5 py-1 bg-slate-100 rounded-full">
            <span className="text-xs font-medium text-slate-600">
              {personaLabel}
            </span>
          </div>

          {/* User */}
          {user && (
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-full bg-slate-200 flex items-center justify-center">
                <User className="w-3.5 h-3.5 text-slate-600" />
              </div>
              <span className="hidden md:inline text-sm text-slate-700 font-medium">
                {user.name || user.preferredUsername}
              </span>
            </div>
          )}

          {/* Logout */}
          <Button
            variant="ghost"
            size="sm"
            onClick={onLogout}
            className="text-slate-500 hover:text-red-600"
            title="Sign out"
            aria-label="Sign out"
          >
            <LogOut className="w-4 h-4" />
            <span className="hidden sm:inline ml-1">Sign out</span>
          </Button>
        </div>
      </div>
    </header>
  );
}

export default AppHeader;
