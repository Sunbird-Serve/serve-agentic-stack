/**
 * Recommended Volunteer View — entry point for volunteers who arrive via referral.
 * Collects phone number upfront (used for identity verification), then passes
 * persona='recommended_volunteer' and sends "I was recommended" as the initial message.
 */
import { useState, useRef, useEffect } from 'react';
import { Send, Loader2, RefreshCw, ArrowLeft, UserPlus } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { ScrollArea } from '../components/ui/scroll-area';
import { orchestratorApi } from '../services/api';

const TypingIndicator = () => (
  <div className="typing-indicator">
    <div className="typing-dot" />
    <div className="typing-dot" />
    <div className="typing-dot" />
  </div>
);

const MessageBubble = ({ message, isUser }) => (
  <div className={`message-wrapper ${isUser ? 'user' : 'assistant'} animate-fade-in`}>
    <div className={`message-avatar ${isUser ? 'user' : 'assistant'}`}>
      {isUser ? 'V' : 'e'}
    </div>
    <div className={`message-content ${isUser ? 'chat-bubble-user' : 'chat-bubble-assistant'}`}>
      {message.content}
    </div>
  </div>
);

export const RecommendedVolunteerView = ({ onBack }) => {
  const [volunteerPhone, setVolunteerPhone] = useState('');
  const [started, setStarted] = useState(false);
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [sessionState, setSessionState] = useState(null);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (started) inputRef.current?.focus();
  }, [started]);

  const handleStart = async () => {
    if (!volunteerPhone.trim()) return;
    setStarted(true);
    setIsLoading(true);
    try {
      const channelMetadata = {
        volunteer_phone: volunteerPhone.trim(),
      };
      const response = await orchestratorApi.interact(
        null,
        'I was recommended to volunteer',
        'web_ui',
        'recommended_volunteer',
        channelMetadata,
      );
      setSessionId(response.session_id);
      setSessionState(response.state);
      setMessages([{ role: 'assistant', content: response.assistant_message }]);

      if (response.auto_continue) {
        const followUp = await orchestratorApi.interact(
          response.session_id,
          '__auto_continue__',
          'web_ui',
          'recommended_volunteer',
        );
        setSessionState(followUp.state);
        const newMsgs = [];
        if (followUp.preliminary_message) newMsgs.push({ role: 'assistant', content: followUp.preliminary_message });
        newMsgs.push({ role: 'assistant', content: followUp.assistant_message });
        setMessages((prev) => [...prev, ...newMsgs]);
      }
    } catch (err) {
      console.error('Failed to start recommended volunteer session:', err);
      setMessages([{ role: 'assistant', content: 'Could not connect. Please check the backend is running.' }]);
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
        'recommended_volunteer',
      );
      setSessionId(response.session_id);
      setSessionState(response.state);
      if (response.preliminary_message) {
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: response.preliminary_message },
          { role: 'assistant', content: response.assistant_message },
        ]);
      } else {
        setMessages((prev) => [...prev, { role: 'assistant', content: response.assistant_message }]);
      }

      if (response.auto_continue) {
        const followUp = await orchestratorApi.interact(
          response.session_id,
          '__auto_continue__',
          'web_ui',
          'recommended_volunteer',
        );
        setSessionState(followUp.state);
        const newMsgs = [];
        if (followUp.preliminary_message) newMsgs.push({ role: 'assistant', content: followUp.preliminary_message });
        newMsgs.push({ role: 'assistant', content: followUp.assistant_message });
        setMessages((prev) => [...prev, ...newMsgs]);
      }
    } catch (err) {
      console.error('Failed to send message:', err);
      setMessages((prev) => [...prev, { role: 'assistant', content: 'Something went wrong. Please try again.' }]);
    }
    setIsLoading(false);
    inputRef.current?.focus();
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  const handleReset = () => {
    setStarted(false);
    setMessages([]);
    setSessionId(null);
    setSessionState(null);
    setInputValue('');
    setVolunteerPhone('');
  };

  // ── Setup screen — collect phone number ───────────────────────────────
  if (!started) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-teal-50 to-slate-100 flex items-center justify-center p-8">
        <div className="max-w-md w-full bg-white rounded-2xl shadow-sm border border-slate-200 p-8">
          <div className="flex items-center gap-3 mb-6">
            {onBack && (
              <button onClick={onBack} className="text-slate-400 hover:text-slate-600">
                <ArrowLeft className="w-5 h-5" />
              </button>
            )}
            <div className="w-10 h-10 rounded-xl bg-teal-100 flex items-center justify-center">
              <UserPlus className="w-5 h-5 text-teal-600" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Recommended Volunteer</h2>
              <p className="text-sm text-slate-500">Referral onboarding</p>
            </div>
          </div>

          <p className="text-sm text-slate-600 mb-6 leading-relaxed">
            Welcome! If someone recommended you to volunteer with eVidyaloka,
            enter your registered phone number below to get started.
          </p>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">
                Mobile Number <span className="text-red-500">*</span>
              </label>
              <Input
                value={volunteerPhone}
                onChange={(e) => setVolunteerPhone(e.target.value)}
                placeholder="e.g. 9876543210"
                onKeyPress={(e) => e.key === 'Enter' && handleStart()}
              />
              <p className="text-xs text-slate-400 mt-1">
                Used to verify your registration with eVidyaloka.
              </p>
            </div>
            <Button
              onClick={handleStart}
              disabled={!volunteerPhone.trim()}
              className="w-full bg-teal-600 hover:bg-teal-700 text-white"
            >
              Start Conversation
            </Button>
          </div>
        </div>
      </div>
    );
  }

  // ── Chat screen ───────────────────────────────────────────────────────────
  return (
    <div className="flex h-screen bg-white">
      <div className="flex-1 flex flex-col max-w-3xl mx-auto w-full">
        {/* Header */}
        <div className="p-4 border-b border-slate-200 flex items-center justify-between bg-white">
          <div className="flex items-center gap-3">
            {onBack && (
              <Button variant="ghost" size="sm" onClick={onBack}>
                <ArrowLeft className="w-4 h-4" />
              </Button>
            )}
            <div className="w-9 h-9 rounded-full bg-teal-100 flex items-center justify-center">
              <UserPlus className="w-4 h-4 text-teal-600" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Recommended Volunteer</h2>
              <p className="text-sm text-slate-500">
                Phone: {volunteerPhone}
                {sessionState && <span className="ml-2 text-teal-500">· {sessionState}</span>}
              </p>
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={handleReset}>
            <RefreshCw className="w-4 h-4 mr-2" />
            Reset
          </Button>
        </div>

        {/* Messages */}
        <ScrollArea className="flex-1 p-4 bg-slate-50">
          <div className="space-y-4 pb-4">
            {messages.map((msg, idx) => (
              <MessageBubble key={idx} message={msg} isUser={msg.role === 'user'} />
            ))}
            {isLoading && (
              <div className="message-wrapper assistant">
                <div className="message-avatar assistant">e</div>
                <div className="message-content chat-bubble-assistant">
                  <TypingIndicator />
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        </ScrollArea>

        {/* Input */}
        <div className="chat-input-container px-4 pb-4 pt-2 bg-white border-t border-slate-100">
          <div className="flex gap-2">
            <Input
              ref={inputRef}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="Type your message..."
              disabled={isLoading}
              className="flex-1"
            />
            <Button
              onClick={handleSend}
              disabled={!inputValue.trim() || isLoading}
              className="bg-teal-600 hover:bg-teal-700 text-white"
            >
              {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default RecommendedVolunteerView;
