/**
 * VolunteerChatPage — Public volunteer onboarding chat.
 * No login required. Uses guest-interact endpoint.
 *
 * Layout: Hero/credibility panel (left) + Chat (right)
 * After first message: left panel transforms to progress tracker.
 */
import { useState, useCallback, useRef, useEffect } from 'react';
import { Check, Circle, Users, Clock, School, MessageCircle, Sparkles } from 'lucide-react';
import { ChatThread } from '../components/conversation/ChatThread';
import { ChatInput } from '../components/conversation/ChatInput';
import { orchestratorApi } from '../services/api';

// ─── Progress Steps ──────────────────────────────────────────────────────────

const JOURNEY_STEPS = [
  { key: 'eligibility', label: 'Eligibility Check', agents: ['onboarding'], stages: ['welcome', 'orientation_video', 'eligibility_screening'] },
  { key: 'profile', label: 'Your Details', agents: ['onboarding'], stages: ['contact_capture', 'teaching_profile', 'registration_review', 'onboarding_complete'] },
  { key: 'assessment', label: 'Getting to Know You', agents: ['selection'], stages: ['selection_conversation', 'gathering_preferences'] },
  { key: 'matching', label: 'Get Matched', agents: ['engagement', 'fulfillment', 'delivery_assistant'], stages: ['re_engaging', 'matching_ready', 'active', 'complete', 'activation_started'] },
];

function getActiveStep(messages) {
  // Determine step from latest agent metadata in messages
  const agentMsgs = [...messages].reverse();
  for (const msg of agentMsgs) {
    const agent = msg.metadata?.agent;
    const state = msg.metadata?.state;
    if (!agent) continue;
    for (let i = 0; i < JOURNEY_STEPS.length; i++) {
      if (JOURNEY_STEPS[i].agents.includes(agent)) {
        // Check if we should be in this step or the next one
        if (JOURNEY_STEPS[i].stages.includes(state)) return i;
        return i;
      }
    }
  }
  return 0;
}

// ─── Hero Panel (before conversation starts) ─────────────────────────────────

function HeroPanel() {
  return (
    <div className="flex flex-col h-full p-6 lg:p-8 justify-center">
      {/* Logo */}
      <div className="flex items-center gap-3 mb-8">
        <img src="/serve-logo.jpeg" alt="SERVE" className="h-12 w-auto" />
        <div>
          <p className="text-xs text-slate-500">Transforming Intent to Impact</p>
        </div>
      </div>

      {/* Value proposition */}
      <div className="mb-8">
        <h2 className="text-2xl lg:text-3xl font-bold text-slate-900 leading-tight mb-3">
          Teach a child.<br />Change a life.
        </h2>
        <p className="text-slate-600 text-sm leading-relaxed">
          Join volunteers teaching students in rural India online — just 2 hours a week from your home.
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3 mb-8">
        <div className="text-center p-3 bg-blue-50 rounded-xl">
          <Users className="w-4 h-4 text-blue-600 mx-auto mb-1" />
          <p className="text-lg font-bold text-slate-900">300+</p>
          <p className="text-[10px] text-slate-500">Volunteers</p>
        </div>
        <div className="text-center p-3 bg-emerald-50 rounded-xl">
          <Clock className="w-4 h-4 text-emerald-600 mx-auto mb-1" />
          <p className="text-lg font-bold text-slate-900">10,000+</p>
          <p className="text-[10px] text-slate-500">Teaching Hrs</p>
        </div>
        <div className="text-center p-3 bg-violet-50 rounded-xl">
          <School className="w-4 h-4 text-violet-600 mx-auto mb-1" />
          <p className="text-lg font-bold text-slate-900">140+</p>
          <p className="text-[10px] text-slate-500">Schools</p>
        </div>
      </div>

      {/* How it works */}
      <div className="mb-6">
        <p className="text-xs font-semibold text-slate-400 uppercase mb-3">How it works</p>
        <div className="space-y-2.5">
          {['Quick eligibility check', 'Share your details', 'Getting to know you', 'Get matched to a school'].map((step, i) => (
            <div key={i} className="flex items-center gap-2.5">
              <div className="w-5 h-5 rounded-full bg-slate-100 flex items-center justify-center shrink-0">
                <span className="text-[10px] font-bold text-slate-500">{i + 1}</span>
              </div>
              <span className="text-sm text-slate-700">{step}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Time estimate */}
      <div className="flex items-center gap-2 text-xs text-slate-500 bg-slate-50 rounded-lg px-3 py-2">
        <Sparkles className="w-3.5 h-3.5 text-amber-500" />
        Takes about 5 minutes — no sign-up needed
      </div>
    </div>
  );
}

// ─── Progress Panel (during conversation) ────────────────────────────────────

function ProgressPanel({ activeStep }) {
  const tips = [
    'You can pause and come back anytime',
    'Your information is kept confidential',
    'No payment is ever involved',
    'Teach from anywhere with internet',
  ];
  const tipIndex = Math.floor(Date.now() / 30000) % tips.length;

  return (
    <div className="flex flex-col h-full p-6 lg:p-8">
      {/* Logo */}
      <div className="flex items-center gap-3 mb-8">
        <img src="/serve-logo.jpeg" alt="SERVE" className="h-10 w-auto" />
      </div>

      {/* Progress steps */}
      <div className="mb-8">
        <p className="text-xs font-semibold text-slate-400 uppercase mb-4">Your Progress</p>
        <div className="space-y-3">
          {JOURNEY_STEPS.map((step, i) => {
            const isCompleted = i < activeStep;
            const isActive = i === activeStep;
            return (
              <div key={step.key} className="flex items-center gap-3">
                <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${
                  isCompleted ? 'bg-emerald-100' : isActive ? 'bg-blue-100' : 'bg-slate-100'
                }`}>
                  {isCompleted ? (
                    <Check className="w-3.5 h-3.5 text-emerald-600" />
                  ) : isActive ? (
                    <Circle className="w-3 h-3 text-blue-600 fill-blue-600" />
                  ) : (
                    <Circle className="w-3 h-3 text-slate-300" />
                  )}
                </div>
                <span className={`text-sm ${
                  isActive ? 'font-medium text-slate-900' : isCompleted ? 'text-slate-600' : 'text-slate-400'
                }`}>
                  {step.label}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Time estimate */}
      <div className="mb-6 px-3 py-2.5 bg-blue-50 rounded-lg">
        <p className="text-xs text-blue-700 font-medium">
          ⏱️ ~{Math.max(1, (JOURNEY_STEPS.length - activeStep) * 2)} min remaining
        </p>
      </div>

      {/* Tip */}
      <div className="mt-auto px-3 py-2.5 bg-slate-50 rounded-lg">
        <p className="text-[11px] text-slate-500">
          💡 <span className="font-medium">Tip:</span> {tips[tipIndex]}
        </p>
      </div>
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export function VolunteerChatPage() {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [hasStarted, setHasStarted] = useState(false);
  const sessionIdRef = useRef(null);
  const guestIdRef = useRef(
    localStorage.getItem('serve_guest_id') || `guest_${Date.now().toString(36)}`
  );

  // Persist guest ID
  useEffect(() => {
    localStorage.setItem('serve_guest_id', guestIdRef.current);
  }, []);

  const activeStep = getActiveStep(messages);

  const sendMessage = useCallback(async (content) => {
    if (!content.trim() || loading) return;
    if (!hasStarted) setHasStarted(true);

    const userMsg = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: content.trim(),
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setLoading(true);

    try {
      const response = await orchestratorApi.guestInteract(
        sessionIdRef.current,
        content.trim(),
        guestIdRef.current,
        'web_ui',
        'new_volunteer'
      );

      if (response.session_id) {
        sessionIdRef.current = response.session_id;
      }
      if (response.debug_info?.guest_id) {
        guestIdRef.current = response.debug_info.guest_id;
        localStorage.setItem('serve_guest_id', response.debug_info.guest_id);
      }

      // Progress message
      if (response.preliminary_message) {
        setMessages((prev) => [...prev, {
          id: `progress-${Date.now()}`,
          role: 'assistant',
          content: response.preliminary_message,
          timestamp: new Date().toISOString(),
          metadata: { type: 'progress', agent: response.active_agent, state: response.state },
        }]);
      }

      // Assistant message
      setMessages((prev) => [...prev, {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: response.assistant_message,
        timestamp: new Date().toISOString(),
        metadata: { agent: response.active_agent, state: response.state },
      }]);

      // Auto-continue
      if (response.auto_continue) {
        const followup = await orchestratorApi.guestInteract(
          sessionIdRef.current,
          '__auto_continue__',
          guestIdRef.current
        );
        if (followup.preliminary_message) {
          setMessages((prev) => [...prev, {
            id: `progress-f-${Date.now()}`,
            role: 'assistant',
            content: followup.preliminary_message,
            timestamp: new Date().toISOString(),
            metadata: { agent: followup.active_agent, state: followup.state },
          }]);
        }
        if (followup.assistant_message) {
          setMessages((prev) => [...prev, {
            id: `assistant-f-${Date.now()}`,
            role: 'assistant',
            content: followup.assistant_message,
            timestamp: new Date().toISOString(),
            metadata: { agent: followup.active_agent, state: followup.state },
          }]);
        }
      }
    } catch (error) {
      console.error('Failed to send message:', error);
      setMessages((prev) => [...prev, {
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: 'Something went wrong. Please try again.',
        timestamp: new Date().toISOString(),
      }]);
    }

    setLoading(false);
  }, [loading, hasStarted]);

  return (
    <div className="min-h-screen bg-white flex">
      {/* Left Panel — Hero or Progress (hidden on mobile when chat is active) */}
      <aside className={`${hasStarted ? 'hidden lg:flex' : 'hidden md:flex'} w-[380px] lg:w-[420px] bg-gradient-to-b from-slate-50 to-white border-r border-slate-100 flex-col shrink-0`}>
        {hasStarted ? <ProgressPanel activeStep={activeStep} /> : <HeroPanel />}
      </aside>

      {/* Right Panel — Chat */}
      <div className="flex-1 flex flex-col min-w-0 h-screen">
        {/* Mobile header */}
        <header className="border-b border-slate-100 px-4 py-3 flex items-center gap-3 shrink-0">
          <img src="/serve-logo.jpeg" alt="SERVE" className="h-8 w-auto" />
          <div className="flex-1 min-w-0">
            <h1 className="text-sm font-semibold text-slate-900">SERVE — Volunteer Onboarding</h1>
            <p className="text-[11px] text-slate-500">Transforming Intent to Impact</p>
          </div>
          {hasStarted && (
            <div className="hidden sm:flex lg:hidden items-center gap-1.5 px-2.5 py-1 bg-blue-50 rounded-full">
              <Circle className="w-2.5 h-2.5 text-blue-600 fill-blue-600" />
              <span className="text-[10px] font-medium text-blue-700">{JOURNEY_STEPS[activeStep]?.label}</span>
            </div>
          )}
        </header>

        {/* Welcome prompt for empty state (mobile) */}
        {!hasStarted && messages.length === 0 && (
          <div className="md:hidden flex-1 flex flex-col items-center justify-center p-6 text-center">
            <div className="w-14 h-14 rounded-2xl bg-amber-50 flex items-center justify-center mb-4">
              <MessageCircle className="w-7 h-7 text-amber-600" />
            </div>
            <h2 className="text-lg font-semibold text-slate-900 mb-2">Ready to make a difference?</h2>
            <p className="text-sm text-slate-500 mb-4 max-w-xs">
              Join 300+ volunteers teaching students in rural areas. Takes just 5 minutes to get started.
            </p>
            <div className="grid grid-cols-3 gap-2 mb-6 w-full max-w-xs">
              <div className="text-center p-2 bg-blue-50 rounded-lg">
                <p className="text-sm font-bold text-slate-900">300+</p>
                <p className="text-[9px] text-slate-500">Volunteers</p>
              </div>
              <div className="text-center p-2 bg-emerald-50 rounded-lg">
                <p className="text-sm font-bold text-slate-900">10K+</p>
                <p className="text-[9px] text-slate-500">Hours</p>
              </div>
              <div className="text-center p-2 bg-violet-50 rounded-lg">
                <p className="text-sm font-bold text-slate-900">140+</p>
                <p className="text-[9px] text-slate-500">Schools</p>
              </div>
            </div>
            <p className="text-xs text-slate-400">Type "Hi" below to start ↓</p>
          </div>
        )}

        {/* Chat area */}
        <div className={`flex-1 flex flex-col overflow-hidden ${!hasStarted && messages.length === 0 ? 'hidden md:flex' : ''}`}>
          <ChatThread messages={messages} loading={loading} />
        </div>

        <div className="shrink-0">
          <ChatInput onSend={sendMessage} loading={loading} placeholder={hasStarted ? "Type your message..." : "Type 'Hi' to start your journey..."} />
        </div>
      </div>
    </div>
  );
}

export default VolunteerChatPage;
