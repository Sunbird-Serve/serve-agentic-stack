/**
 * SERVE AI - Role Selector Landing Page
 * Entry point for selecting user role/view
 */
import { MessageSquare, Users, Settings, ArrowRight } from 'lucide-react';
import { ServeLogo } from '../components/serve/ServeLogo';

const ROLES = [
  {
    id: 'volunteer',
    title: 'Volunteer',
    description: 'Start your volunteer journey with SERVE AI. Chat with our onboarding assistant to get matched with opportunities.',
    icon: MessageSquare,
    color: 'bg-blue-500',
    hoverColor: 'hover:border-blue-400',
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
    description: 'Debug and monitor the system. View telemetry, MCP calls, session states, and conversation logs.',
    icon: Settings,
    color: 'bg-slate-600',
    hoverColor: 'hover:border-slate-400',
  },
];

export const RoleSelector = ({ onSelectRole }) => {
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 flex items-center justify-center p-8" data-testid="role-selector">
      <div className="max-w-4xl w-full">
        {/* Header */}
        <div className="text-center mb-12">
          <div className="flex justify-center mb-6">
            <ServeLogo size="xl" />
          </div>
          <h1 className="text-4xl font-bold text-slate-900 mb-3 tracking-tight">
            Welcome to SERVE AI
          </h1>
          <p className="text-lg text-slate-600 max-w-2xl mx-auto">
            A Digital Public Good volunteer management platform. 
            Select your role to get started.
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
            Powered by SERVE AI • A Digital Public Good
          </p>
        </div>
      </div>
    </div>
  );
};

export default RoleSelector;
