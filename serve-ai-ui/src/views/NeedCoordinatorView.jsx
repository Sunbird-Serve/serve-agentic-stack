/**
 * eVidyaloka - Need Coordinator Chat View
 * Chat interface for school coordinators to register teaching needs.
 *
 * Flow:
 *   1. PhoneEntryScreen  — coordinator enters phone number (passed as channel_metadata)
 *   2. Chat + NeedJourneyProgress sidebar — conversation with the Need Agent
 */
import { useState, useRef, useEffect, useCallback } from 'react';
import {
  Send, Loader2, RefreshCw, ArrowLeft, School, Users, Clock,
  Calendar, Phone, CheckCircle2, ChevronRight,
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { ScrollArea } from '../components/ui/scroll-area';
import { orchestratorApi } from '../services/api';

// ── Typing indicator ──────────────────────────────────────────────────────────

const TypingIndicator = () => (
  <div className="typing-indicator" data-testid="typing-indicator">
    <div className="typing-dot" />
    <div className="typing-dot" />
    <div className="typing-dot" />
  </div>
);

// ── Message bubble ────────────────────────────────────────────────────────────

const MessageBubble = ({ message, isUser }) => (
  <div
    className={`message-wrapper ${isUser ? 'user' : 'assistant'} animate-fade-in`}
    data-testid={`message-${isUser ? 'user' : 'assistant'}`}
  >
    <div className={`message-avatar ${isUser ? 'user' : 'assistant'}`}>
      {isUser ? 'C' : 'e'}
    </div>
    <div className={`message-content ${isUser ? 'chat-bubble-user' : 'chat-bubble-assistant'}`}>
      {message.content}
    </div>
  </div>
);

// ── Phone entry pre-screen ────────────────────────────────────────────────────

const PhoneEntryScreen = ({ onSubmit, onBack }) => {
  const [phone, setPhone] = useState('');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const inputRef = useRef(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSubmit = () => {
    const cleaned = phone.trim();
    const digitsOnly = cleaned.replace(/\D/g, '');
    if (digitsOnly.length < 10) {
      setError('Please enter a valid phone number (at least 10 digits)');
      return;
    }
    setError('');
    setIsSubmitting(true);
    onSubmit(cleaned);
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter') handleSubmit();
  };

  return (
    <div
      className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center px-4"
      data-testid="phone-entry-screen"
    >
      <div className="w-full max-w-md">
        {/* Back button */}
        {onBack && (
          <button
            onClick={onBack}
            className="flex items-center gap-1 text-white/50 hover:text-white/80 text-sm mb-6 transition-colors"
          >
            <ArrowLeft size={16} />
            Back
          </button>
        )}

        {/* Card */}
        <div className="glass-card p-8">
          {/* Logo */}
          <div className="text-center mb-8">
            <div className="w-16 h-16 rounded-full bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center mx-auto mb-4 shadow-lg shadow-amber-500/20">
              <School size={30} className="text-white" />
            </div>
            <h1 className="text-2xl font-bold text-white">eVidyaloka</h1>
            <p className="text-white/50 text-sm mt-1">Need Registration</p>
          </div>

          {/* Description */}
          <div className="mb-7 text-center">
            <p className="text-white/70 text-sm leading-relaxed">
              Enter the phone number linked to your school.
              We'll use it to quickly find you on record.
            </p>
          </div>

          {/* Input */}
          <div className="space-y-2">
            <label className="block text-xs font-medium text-white/60 uppercase tracking-wide">
              Phone / WhatsApp Number
            </label>
            <div className="relative">
              <Phone size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
              <Input
                ref={inputRef}
                value={phone}
                onChange={(e) => { setPhone(e.target.value); setError(''); }}
                onKeyPress={handleKeyPress}
                placeholder="+91 98765 43210"
                className="pl-9 bg-white/5 border-white/20 text-white placeholder:text-white/30 focus:border-amber-500/50 text-base py-5"
                data-testid="phone-input"
              />
            </div>
            {error && (
              <p className="text-red-400 text-xs" data-testid="phone-error">{error}</p>
            )}
          </div>

          {/* Submit */}
          <Button
            onClick={handleSubmit}
            disabled={isSubmitting || !phone.trim()}
            className="w-full mt-6 bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700 text-white py-5 text-base font-medium"
            data-testid="phone-submit"
          >
            {isSubmitting ? (
              <Loader2 size={18} className="animate-spin mr-2" />
            ) : (
              <ChevronRight size={18} className="mr-2" />
            )}
            Continue
          </Button>

          <p className="text-center text-white/25 text-xs mt-5">
            Your number is used only to identify your school record
          </p>
        </div>

        {/* What to expect */}
        <div className="mt-4 glass-card p-4">
          <p className="text-xs font-medium text-white/60 mb-3 uppercase tracking-wide">
            What happens next
          </p>
          <ul className="space-y-2">
            {[
              'We verify your coordinator profile',
              'We link you to your school',
              'You describe your teaching support need',
              'We match volunteers for you',
            ].map((step, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-white/50">
                <span className="text-amber-400 font-semibold shrink-0">{i + 1}.</span>
                {step}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
};

// ── Need Journey Progress sidebar ─────────────────────────────────────────────

const STAGES = [
  { id: 'initiated',              label: 'Welcome',     icon: School },
  { id: 'capturing_phone',        label: 'Your Number', icon: Phone },
  { id: 'resolving_coordinator',  label: 'Your Info',   icon: Users },
  { id: 'resolving_school',       label: 'School',      icon: School },
  { id: 'drafting_need',          label: 'Need Details',icon: Clock },
  { id: 'pending_approval',       label: 'Review',      icon: Calendar },
  { id: 'submitted',              label: 'Registered',  icon: CheckCircle2 },
];

const NeedJourneyProgress = ({ state, progressPercent, needDraft }) => {
  const currentIndex = STAGES.findIndex(s => s.id === state);
  const displayStages = STAGES.slice(0, 6); // show up to review

  return (
    <div className="need-journey-card glass-card p-4" data-testid="need-journey-progress">
      <h3 className="text-sm font-semibold text-white/90 mb-3">Need Registration Progress</h3>

      {/* Progress bar */}
      <div className="relative h-2 bg-white/10 rounded-full mb-2 overflow-hidden">
        <div
          className="absolute inset-y-0 left-0 bg-gradient-to-r from-emerald-500 to-teal-400 rounded-full transition-all duration-500"
          style={{ width: `${progressPercent}%` }}
        />
      </div>
      <div className="text-xs text-white/60 mb-4">{progressPercent}% Complete</div>

      {/* Stage indicators */}
      <div className="flex justify-between mb-4">
        {displayStages.map((stage, idx) => {
          const Icon = stage.icon;
          const isActive = idx <= currentIndex;
          const isCurrent = stage.id === state;
          return (
            <div
              key={stage.id}
              className={`flex flex-col items-center ${isCurrent ? 'scale-110' : ''} transition-transform`}
            >
              <div className={`w-8 h-8 rounded-full flex items-center justify-center ${
                isActive ? 'bg-emerald-500/30 text-emerald-400' : 'bg-white/10 text-white/40'
              } ${isCurrent ? 'ring-2 ring-emerald-400' : ''}`}>
                <Icon size={14} />
              </div>
              <span className={`text-[10px] mt-1 text-center leading-tight ${isActive ? 'text-white/80' : 'text-white/40'}`}>
                {stage.label}
              </span>
            </div>
          );
        })}
      </div>

      {/* Captured details */}
      {needDraft && Object.keys(needDraft).length > 0 && (
        <div className="mt-4 pt-4 border-t border-white/10">
          <h4 className="text-xs font-medium text-white/70 mb-2">Captured Details</h4>
          <div className="space-y-1 text-xs">
            {needDraft.coordinator_name && (
              <div className="flex justify-between gap-2">
                <span className="text-white/50 shrink-0">Coordinator</span>
                <span className="text-white/90 text-right">{needDraft.coordinator_name}</span>
              </div>
            )}
            {needDraft.school_name && (
              <div className="flex justify-between gap-2">
                <span className="text-white/50 shrink-0">School</span>
                <span className="text-white/90 text-right">{needDraft.school_name}</span>
              </div>
            )}
            {needDraft.subjects && needDraft.subjects.length > 0 && (
              <div className="flex justify-between gap-2">
                <span className="text-white/50 shrink-0">Subjects</span>
                <span className="text-white/90 text-right capitalize">
                  {needDraft.subjects.join(', ')}
                </span>
              </div>
            )}
            {needDraft.grade_levels && needDraft.grade_levels.length > 0 && (
              <div className="flex justify-between gap-2">
                <span className="text-white/50 shrink-0">Grades</span>
                <span className="text-white/90 text-right">
                  {needDraft.grade_levels.join(', ')}
                </span>
              </div>
            )}
            {needDraft.student_count && (
              <div className="flex justify-between gap-2">
                <span className="text-white/50 shrink-0">Students</span>
                <span className="text-white/90">{needDraft.student_count}</span>
              </div>
            )}
            {needDraft.time_slots && needDraft.time_slots.length > 0 && (
              <div className="flex justify-between gap-2">
                <span className="text-white/50 shrink-0">Time Slots</span>
                <span className="text-white/90 text-right">
                  {needDraft.time_slots.join(', ')}
                </span>
              </div>
            )}
            {needDraft.start_date && (
              <div className="flex justify-between gap-2">
                <span className="text-white/50 shrink-0">Start Date</span>
                <span className="text-white/90">{needDraft.start_date}</span>
              </div>
            )}
            {needDraft.duration_weeks && (
              <div className="flex justify-between gap-2">
                <span className="text-white/50 shrink-0">Duration</span>
                <span className="text-white/90">{needDraft.duration_weeks} weeks</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

// ── Main view ─────────────────────────────────────────────────────────────────

export const NeedCoordinatorView = ({ onBack }) => {
  const [phoneNumber, setPhoneNumber] = useState('');
  const [chatStarted, setChatStarted] = useState(false);
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [journeyState, setJourneyState] = useState({
    currentState: 'initiated',
    progressPercent: 0,
    needDraft: {},
    missingFields: [],
  });

  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  // Auto-scroll on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Focus input when chat is open
  useEffect(() => {
    if (chatStarted) inputRef.current?.focus();
  }, [chatStarted]);

  const updateJourney = useCallback((response) => {
    if (response.journey_progress) {
      setJourneyState({
        currentState: response.state || 'initiated',
        progressPercent: response.journey_progress.progress_percent || 0,
        needDraft: response.journey_progress.confirmed_fields || {},
        missingFields: response.journey_progress.missing_fields || [],
      });
    }
  }, []);

  // Called when coordinator submits their phone number
  const handlePhoneSubmit = async (phone) => {
    setPhoneNumber(phone);
    setChatStarted(true);
    setIsLoading(true);

    try {
      const response = await orchestratorApi.interact(
        null,
        'Hello, I need to register a teaching need for our school',
        'web_ui',
        'need_coordinator',
        { phone_number: phone },
      );
      setSessionId(response.session_id);
      if (response.assistant_message) {
        setMessages([{ role: 'assistant', content: response.assistant_message }]);
      }
      updateJourney(response);
    } catch (error) {
      console.error('Failed to start conversation:', error);
      setMessages([{
        role: 'assistant',
        content: "Hello! Welcome to eVidyaloka. I'm here to help you register teaching support for your school.",
      }]);
    }
    setIsLoading(false);
  };

  const handleSend = async () => {
    if (!inputValue.trim() || isLoading) return;

    const userMessage = inputValue.trim();
    setInputValue('');
    setMessages((prev) => [...prev, { role: 'user', content: userMessage }]);
    setIsLoading(true);

    try {
      const response = await orchestratorApi.interact(
        sessionId,
        userMessage,
        'web_ui',
        'need_coordinator',
        { phone_number: phoneNumber },
      );
      if (response.assistant_message) {
        setMessages((prev) => [...prev, { role: 'assistant', content: response.assistant_message }]);
      }
      updateJourney(response);
    } catch (error) {
      console.error('Message send failed:', error);
      setMessages((prev) => [...prev, {
        role: 'assistant',
        content: 'I apologize, but I encountered an issue. Could you please try again?',
      }]);
    }
    setIsLoading(false);
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Reset: go back to phone entry
  const handleReset = () => {
    setPhoneNumber('');
    setChatStarted(false);
    setMessages([]);
    setSessionId(null);
    setInputValue('');
    setJourneyState({ currentState: 'initiated', progressPercent: 0, needDraft: {}, missingFields: [] });
  };

  // ── Phone entry screen ───────────────────────────────────────────────────
  if (!chatStarted) {
    return <PhoneEntryScreen onSubmit={handlePhoneSubmit} onBack={onBack} />;
  }

  // ── Chat view ─────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900" data-testid="need-coordinator-view">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-white/10 bg-slate-900/80 backdrop-blur-xl">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Button
              variant="ghost"
              size="icon"
              onClick={handleReset}
              className="text-white/70 hover:text-white hover:bg-white/10"
              data-testid="back-button"
            >
              <ArrowLeft size={20} />
            </Button>
            <div className="flex items-center gap-2">
              <div className="w-10 h-10 rounded-full bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center shadow-md shadow-amber-500/20">
                <School size={20} className="text-white" />
              </div>
              <div>
                <h1 className="text-lg font-semibold text-white">Need Registration</h1>
                <p className="text-xs text-white/50">
                  {phoneNumber && (
                    <span className="inline-flex items-center gap-1">
                      <Phone size={10} />
                      {phoneNumber}
                    </span>
                  )}
                </p>
              </div>
            </div>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleReset}
            className="text-white/70 border-white/20 hover:bg-white/10"
            data-testid="reset-button"
          >
            <RefreshCw size={14} className="mr-2" />
            New Request
          </Button>
        </div>
      </header>

      {/* Main content */}
      <div className="max-w-7xl mx-auto px-4 py-6">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Chat area */}
          <div className="lg:col-span-2 flex flex-col h-[calc(100vh-180px)]">
            <ScrollArea className="flex-1 pr-4">
              <div className="space-y-4 pb-4">
                {messages.map((msg, idx) => (
                  <MessageBubble
                    key={idx}
                    message={msg}
                    isUser={msg.role === 'user'}
                  />
                ))}
                {isLoading && (
                  <div className="message-wrapper assistant">
                    <div className="message-avatar assistant">e</div>
                    <TypingIndicator />
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>
            </ScrollArea>

            {/* Input area */}
            <div className="mt-4 flex gap-3">
              <Input
                ref={inputRef}
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyPress={handleKeyPress}
                placeholder="Type your message..."
                disabled={isLoading}
                className="flex-1 bg-white/5 border-white/20 text-white placeholder:text-white/40 focus:border-amber-500/50"
                data-testid="message-input"
              />
              <Button
                onClick={handleSend}
                disabled={isLoading || !inputValue.trim()}
                className="bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700 text-white px-6"
                data-testid="send-button"
              >
                {isLoading ? (
                  <Loader2 size={18} className="animate-spin" />
                ) : (
                  <Send size={18} />
                )}
              </Button>
            </div>
          </div>

          {/* Progress sidebar */}
          <div className="hidden lg:block">
            <NeedJourneyProgress
              state={journeyState.currentState}
              progressPercent={journeyState.progressPercent}
              needDraft={journeyState.needDraft}
            />

            {/* What we need */}
            <div className="glass-card p-4 mt-4">
              <h3 className="text-sm font-semibold text-white/90 mb-2">What We Need to Know</h3>
              <ul className="text-xs text-white/60 space-y-2">
                {[
                  'Your name and school',
                  'Subjects and grade levels',
                  'Number of students',
                  'Preferred time slots',
                  'Start date and duration',
                ].map((item, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className="text-amber-400 shrink-0">{i + 1}.</span>
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default NeedCoordinatorView;
