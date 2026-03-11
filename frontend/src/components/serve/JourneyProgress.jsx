/**
 * eVidyaloka - Journey Progress Component
 * Shows volunteer's progress through onboarding stages
 */
import { Check, Circle, Clock } from 'lucide-react';
import { Progress } from '../ui/progress';

const STAGES = [
  { key: 'init', label: 'Welcome' },
  { key: 'intent_discovery', label: 'Your Motivation' },
  { key: 'purpose_orientation', label: 'About eVidyaloka' },
  { key: 'eligibility_confirmation', label: 'Your Info' },
  { key: 'capability_discovery', label: 'Your Skills' },
  { key: 'profile_confirmation', label: 'Review' },
  { key: 'onboarding_complete', label: 'Welcome Aboard!' },
];

export const JourneyProgress = ({ currentState, progressPercent = 0, className = '' }) => {
  const currentIndex = STAGES.findIndex(s => s.key === currentState);

  return (
    <div className={`progress-container ${className}`} data-testid="journey-progress">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-slate-700">Your Journey</h3>
        <span className="text-sm text-slate-500">{progressPercent}% Complete</span>
      </div>
      
      <Progress value={progressPercent} className="h-2 mb-4" />
      
      <div className="space-y-1">
        {STAGES.map((stage, index) => {
          const isCompleted = index < currentIndex;
          const isActive = index === currentIndex;
          const isPending = index > currentIndex;

          return (
            <div
              key={stage.key}
              className={`progress-step ${isActive ? 'opacity-100' : 'opacity-70'}`}
              data-testid={`progress-step-${stage.key}`}
            >
              <div
                className={`progress-step-indicator ${
                  isCompleted ? 'completed' : isActive ? 'active' : 'pending'
                }`}
              >
                {isCompleted ? (
                  <Check className="w-3 h-3" />
                ) : isActive ? (
                  <Circle className="w-3 h-3 fill-current" />
                ) : (
                  <Clock className="w-3 h-3" />
                )}
              </div>
              <span
                className={`text-sm ${
                  isActive
                    ? 'font-medium text-slate-900'
                    : isCompleted
                    ? 'text-slate-600'
                    : 'text-slate-400'
                }`}
              >
                {stage.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default JourneyProgress;
