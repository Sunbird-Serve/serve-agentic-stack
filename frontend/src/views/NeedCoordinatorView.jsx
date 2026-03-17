/**
 * eVidyaloka - Need Coordinator Chat View
 * Chat interface for school coordinators to register teaching needs
 */
import { useState, useRef, useEffect } from 'react';
import { Send, Loader2, RefreshCw, ArrowLeft, School, Users, Clock, Calendar } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { ScrollArea } from '../components/ui/scroll-area';
import { orchestratorApi } from '../services/api';

// Typing indicator component
const TypingIndicator = () => (
  <div className="typing-indicator" data-testid="typing-indicator">
    <div className="typing-dot" />
    <div className="typing-dot" />
    <div className="typing-dot" />
  </div>
);

// Message bubble component
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

// Need Journey Progress component
const NeedJourneyProgress = ({ state, progressPercent, needDraft }) => {
  const stages = [
    { id: 'initiated', label: 'Welcome', icon: School },
    { id: 'resolving_coordinator', label: 'Your Info', icon: Users },
    { id: 'resolving_school', label: 'School', icon: School },
    { id: 'drafting_need', label: 'Need Details', icon: Clock },
    { id: 'pending_approval', label: 'Review', icon: Calendar },
    { id: 'approved', label: 'Confirmed', icon: Users },
  ];

  const currentIndex = stages.findIndex(s => s.id === state);
  
  return (
    <div className="need-journey-card glass-card p-4" data-testid="need-journey-progress">
      <h3 className="text-sm font-semibold text-white/90 mb-3">Need Registration Progress</h3>
      
      {/* Progress bar */}
      <div className="relative h-2 bg-white/10 rounded-full mb-4 overflow-hidden">
        <div 
          className="absolute inset-y-0 left-0 bg-gradient-to-r from-emerald-500 to-teal-400 rounded-full transition-all duration-500"
          style={{ width: `${progressPercent}%` }}
        />
      </div>
      
      <div className="text-xs text-white/60 mb-4">{progressPercent}% Complete</div>
      
      {/* Stage indicators */}
      <div className="flex justify-between mb-4">
        {stages.slice(0, 4).map((stage, idx) => {
          const Icon = stage.icon;
          const isActive = idx <= currentIndex;
          const isCurrent = stage.id === state;
          return (
            <div 
              key={stage.id}
              className={`flex flex-col items-center ${isCurrent ? 'scale-110' : ''}`}
            >
              <div className={`w-8 h-8 rounded-full flex items-center justify-center ${
                isActive ? 'bg-emerald-500/30 text-emerald-400' : 'bg-white/10 text-white/40'
              } ${isCurrent ? 'ring-2 ring-emerald-400' : ''}`}>
                <Icon size={14} />
              </div>
              <span className={`text-[10px] mt-1 ${isActive ? 'text-white/80' : 'text-white/40'}`}>
                {stage.label}
              </span>
            </div>
          );
        })}
      </div>
      
      {/* Current need draft summary */}
      {needDraft && Object.keys(needDraft).length > 0 && (
        <div className="mt-4 pt-4 border-t border-white/10">
          <h4 className="text-xs font-medium text-white/70 mb-2">Captured Details</h4>
          <div className="space-y-1 text-xs">
            {needDraft.coordinator_name && (
              <div className="flex justify-between">
                <span className="text-white/50">Coordinator</span>
                <span className="text-white/90">{needDraft.coordinator_name}</span>
              </div>
            )}
            {needDraft.school_name && (
              <div className="flex justify-between">
                <span className="text-white/50">School</span>
                <span className="text-white/90">{needDraft.school_name}</span>
              </div>
            )}
            {needDraft.subjects && needDraft.subjects.length > 0 && (
              <div className="flex justify-between">
                <span className="text-white/50">Subjects</span>
                <span className="text-white/90">{needDraft.subjects.join(', ')}</span>
              </div>
            )}
            {needDraft.grade_levels && needDraft.grade_levels.length > 0 && (
              <div className="flex justify-between">
                <span className="text-white/50">Grades</span>
                <span className="text-white/90">{needDraft.grade_levels.join(', ')}</span>
              </div>
            )}
            {needDraft.student_count && (
              <div className="flex justify-between">
                <span className="text-white/50">Students</span>
                <span className="text-white/90">{needDraft.student_count}</span>
              </div>
            )}
            {needDraft.time_slots && needDraft.time_slots.length > 0 && (
              <div className="flex justify-between">
                <span className="text-white/50">Time Slots</span>
                <span className="text-white/90">{needDraft.time_slots.join(', ')}</span>
              </div>
            )}
            {needDraft.start_date && (
              <div className="flex justify-between">
                <span className="text-white/50">Start Date</span>
                <span className="text-white/90">{needDraft.start_date}</span>
              </div>
            )}
            {needDraft.duration_weeks && (
              <div className="flex justify-between">
                <span className="text-white/50">Duration</span>
                <span className="text-white/90">{needDraft.duration_weeks} weeks</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export const NeedCoordinatorView = ({ onBack }) => {
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

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Start conversation with greeting
  useEffect(() => {
    const startConversation = async () => {
      setIsLoading(true);
      try {
        const response = await orchestratorApi.interact(
          null, 
          'Hello, I need to register a teaching need for our school',
          'web_ui',
          'need_coordinator'
        );
        setSessionId(response.session_id);
        setMessages([
          { role: 'assistant', content: response.assistant_message },
        ]);
        if (response.journey_progress) {
          setJourneyState({
            currentState: response.state,
            progressPercent: response.journey_progress.progress_percent || 0,
            needDraft: response.journey_progress.confirmed_fields || {},
            missingFields: response.journey_progress.missing_fields || [],
          });
        }
      } catch (error) {
        console.error('Failed to start conversation:', error);
        setMessages([
          {
            role: 'assistant',
            content: 'Hello! Welcome to eVidyaloka. I\'m here to help you register teaching support needs for your school. Could you tell me your name and which school you represent?',
          },
        ]);
      }
      setIsLoading(false);
    };
    startConversation();
  }, []);

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
        'need_coordinator'
      );
      
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: response.assistant_message },
      ]);
      
      if (response.journey_progress) {
        setJourneyState({
          currentState: response.state,
          progressPercent: response.journey_progress.progress_percent || 0,
          needDraft: response.journey_progress.confirmed_fields || {},
          missingFields: response.journey_progress.missing_fields || [],
        });
      }
    } catch (error) {
      console.error('Message send failed:', error);
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: 'I apologize, but I encountered an issue. Could you please try again?',
        },
      ]);
    }
    setIsLoading(false);
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleReset = async () => {
    setMessages([]);
    setSessionId(null);
    setJourneyState({
      currentState: 'initiated',
      progressPercent: 0,
      needDraft: {},
      missingFields: [],
    });
    setIsLoading(true);
    
    try {
      const response = await orchestratorApi.interact(
        null,
        'Hello, I need to register a teaching need for our school',
        'web_ui',
        'need_coordinator'
      );
      setSessionId(response.session_id);
      setMessages([
        { role: 'assistant', content: response.assistant_message },
      ]);
    } catch (error) {
      setMessages([
        {
          role: 'assistant',
          content: 'Hello! Welcome to eVidyaloka. I\'m here to help you register teaching support needs for your school. Could you tell me your name and which school you represent?',
        },
      ]);
    }
    setIsLoading(false);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900" data-testid="need-coordinator-view">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-white/10 bg-slate-900/80 backdrop-blur-xl">
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            {onBack && (
              <Button
                variant="ghost"
                size="icon"
                onClick={onBack}
                className="text-white/70 hover:text-white hover:bg-white/10"
                data-testid="back-button"
              >
                <ArrowLeft size={20} />
              </Button>
            )}
            <div className="flex items-center gap-2">
              <div className="w-10 h-10 rounded-full bg-gradient-to-br from-amber-500 to-orange-600 flex items-center justify-center">
                <School size={20} className="text-white" />
              </div>
              <div>
                <h1 className="text-lg font-semibold text-white">Need Registration</h1>
                <p className="text-xs text-white/60">Register teaching support for your school</p>
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

            {/* Info card */}
            <div className="glass-card p-4 mt-4">
              <h3 className="text-sm font-semibold text-white/90 mb-2">What We Need to Know</h3>
              <ul className="text-xs text-white/60 space-y-2">
                <li className="flex items-start gap-2">
                  <span className="text-amber-400">1.</span>
                  Your name and role as coordinator
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-amber-400">2.</span>
                  School name and location
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-amber-400">3.</span>
                  Subjects and grade levels needed
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-amber-400">4.</span>
                  Number of students
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-amber-400">5.</span>
                  Preferred time slots
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-amber-400">6.</span>
                  Start date and duration
                </li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default NeedCoordinatorView;
