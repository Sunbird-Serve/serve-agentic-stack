/**
 * Internal Admin Entry - Role Selector
 * Internal route for staff access to different views
 * Not visible to volunteers
 */
import { MessageSquare, Users, Settings, ArrowRight, ShieldCheck, School } from 'lucide-react';

const ROLES = [
  {
    id: 'volunteer',
    title: 'Volunteer View',
    description: 'Preview the volunteer onboarding experience as a volunteer would see it.',
    icon: MessageSquare,
    color: 'bg-blue-500',
    hoverColor: 'hover:border-blue-400',
  },
  {
    id: 'returning_volunteer',
    title: 'Returning Volunteer',
    description: 'Test the re-engagement flow for volunteers who have previously fulfilled needs.',
    icon: ArrowRight,
    color: 'bg-violet-500',
    hoverColor: 'hover:border-violet-400',
  },
  {
    id: 'need_coordinator',
    title: 'Need Coordinator',
    description: 'Register teaching needs for schools. Capture subject, grade, and schedule requirements.',
    icon: School,
    color: 'bg-amber-500',
    hoverColor: 'hover:border-amber-400',
  },
  {
    id: 'ops',
    title: 'Ops / Coordinator',
    description: 'View and manage the volunteer pipeline. Track onboarding progress and review volunteer entries.',
    icon: Users,
    color: 'bg-emerald-500',
    hoverColor: 'hover:border-emerald-400',
  },
  {
    id: 'admin',
    title: 'Tech Admin',
    description: 'Debug and monitor the system. View telemetry, API calls, session states, and conversation logs.',
    icon: Settings,
    color: 'bg-slate-600',
    hoverColor: 'hover:border-slate-400',
  },
];

export const RoleSelector = ({ onSelectRole }) => {
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-100 to-slate-200 flex items-center justify-center p-8" data-testid="role-selector">
      <div className="max-w-4xl w-full">
        {/* Header */}
        <div className="text-center mb-12">
          <div className="flex justify-center mb-6">
            <div className="w-16 h-16 rounded-xl bg-slate-700 flex items-center justify-center">
              <ShieldCheck className="w-8 h-8 text-white" />
            </div>
          </div>
          <h1 className="text-3xl font-bold text-slate-900 mb-3 tracking-tight">
            Internal Access
          </h1>
          <p className="text-base text-slate-600 max-w-lg mx-auto">
            Staff portal for eVidyaloka volunteer management. 
            Select a view to continue.
          </p>
        </div>

        {/* Role Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {ROLES.map((role) => {
            const Icon = role.icon;
            return (
              <button
                key={role.id}
                className={`role-card group text-left ${role.hoverColor}`}
                onClick={() => onSelectRole(role.id)}
                data-testid={`role-card-${role.id}`}
              >
                <div className={`w-12 h-12 rounded-xl ${role.color} flex items-center justify-center mb-4 group-hover:scale-110 transition-transform`}>
                  <Icon className="w-6 h-6 text-white" />
                </div>
                <h3 className="text-xl font-semibold text-slate-900 mb-2">
                  {role.title}
                </h3>
                <p className="text-sm text-slate-500 mb-4 leading-relaxed">
                  {role.description}
                </p>
                <div className="flex items-center text-sm font-medium text-blue-600 group-hover:text-blue-700">
                  Continue
                  <ArrowRight className="w-4 h-4 ml-1 group-hover:translate-x-1 transition-transform" />
                </div>
              </button>
            );
          })}
        </div>

        {/* Footer */}
        <div className="mt-12 text-center">
          <p className="text-sm text-slate-400">
            eVidyaloka Staff Portal • Internal Use Only
          </p>
        </div>
      </div>
    </div>
  );
};

export default RoleSelector;
