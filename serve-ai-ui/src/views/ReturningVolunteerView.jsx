/**
 * Returning Volunteer View — test entry point for the engagement agent.
 * Passes persona='returning_volunteer' and an optional volunteer_id
 * so the engagement agent can load real fulfillment history.
 */
import { useState, useRef, useEffect } from 'react';
import { Send, Loader2, RefreshCw, ArrowLeft, RotateCcw } from 'lucide-react';
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

export const ReturningVolunteerView = ({ onBack }) => {
  const [volunteerId, setVolunteerId] = useState('');
  const [volunteerName, setVolunteerName] = useState('');
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
    if (!volunteerId.trim()) return;
    setStarted(true);
    setIsLoading(true);
    try {
      const channelMetadata = {
        volunteer_id: volunteerId.trim(),
        volunteer_name: volunteerName.trim() || undefined,
      };
      const response = await orchestratorApi.interact(
        null,
        'Hi',
        'web_ui',
        'returning_volunteer',
        channelMetadata,
      );
      setSessionId(response.session_id);
      setSessionState(response.state);
      setMessages([{ role: 'assistant', content: response.assistant_message }]);
    } catch (err) {
      console.error('Failed to start engagement session:', err);
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
        'returning_volunteer',
      );
      setSessionId(response.session_id);
      setSessionState(response.state);
      setMessages((prev) => [...prev, { role: 'assistant', content: response.assistant_message }]);
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
  };

  // ── Setup screen ──────────────────────────────────────────────────────────
  if (!started) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-violet-50 to-slate-100 flex items-center justify-center p-8">
        <div className="max-w-md w-full bg-white rounded-2xl shadow-sm border border-slate-200 p-8">
          <div className="flex items-center gap-3 mb-6">
            {onBack && (
              <button onClick={onBack} className="text-slate-400 hover:text-slate-600">
                <ArrowLeft className="w-5 h-5" />
              </button>
            )}
            <div className="w-10 h-10 rounded-xl bg-violet-100 flex items-center justify-center">
              <RotateCcw className="w-5 h-5 text-violet-600" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Returning Volunteer</h2>
              <p className="text-sm text-slate-500">Engagement agent test</p>
            </div>
          </div>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">
                Volunteer ID <span className="text-red-500">*</span>
              </label>
              <Input
                value={volunteerId}
                onChange={(e) => setVolunteerId(e.target.value)}
                placeholder="Serve Registry volunteer osid"
                onKeyPress={(e) => e.key === 'Enter' && handleStart()}
              />
              <p className="text-xs text-slate-400 mt-1">
                Used to load fulfillment history from Serve Registry.
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">
                Volunteer Name <span className="text-slate-400">(optional)</span>
              </label>
              <Input
                value={volunteerName}
                onChange={(e) => setVolunteerName(e.target.value)}
                placeholder="e.g. Priya Sharma"
                onKeyPress={(e) => e.key === 'Enter' && handleStart()}
              />
            </div>
            <Button
              onClick={handleStart}
              disabled={!volunteerId.trim()}
              className="w-full bg-violet-600 hover:bg-violet-700 text-white"
            >
              Start Re-engagement Session
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
            <div className="w-9 h-9 rounded-full bg-violet-100 flex items-center justify-center">
              <RotateCcw className="w-4 h-4 text-violet-600" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Returning Volunteer</h2>
              <p className="text-sm text-slate-500">
                ID: {volunteerId}
                {sessionState && <span className="ml-2 text-violet-500">· {sessionState}</span>}
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
              className="bg-violet-600 hover:bg-violet-700 text-white"
            >
              {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ReturningVolunteerView;
