/**
 * eVidyaloka - Volunteer Chat View
 * Chat interface for volunteer interaction with the onboarding assistant
 */
import { useState, useRef, useEffect } from 'react';
import { Send, Loader2, RefreshCw, ArrowLeft, BookOpen } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { ScrollArea } from '../components/ui/scroll-area';
import { JourneyProgress } from '../components/serve/JourneyProgress';
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
      {isUser ? 'Y' : 'e'}
    </div>
    <div className={`message-content ${isUser ? 'chat-bubble-user' : 'chat-bubble-assistant'}`}>
      {message.content}
    </div>
  </div>
);

export const VolunteerView = ({ onBack }) => {
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [journeyState, setJourneyState] = useState({
    currentState: 'init',
    progressPercent: 0,
    confirmedFields: {},
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
        const response = await orchestratorApi.interact(null, 'Hello, I want to volunteer');
        setSessionId(response.session_id);
        setMessages([
          { role: 'assistant', content: response.assistant_message },
        ]);
        if (response.journey_progress) {
          setJourneyState({
            currentState: response.state,
            progressPercent: response.journey_progress.progress_percent || 0,
            confirmedFields: response.journey_progress.confirmed_fields || {},
            missingFields: response.journey_progress.missing_fields || [],
          });
        }
      } catch (error) {
        console.error('Failed to start conversation:', error);
        setMessages([
          {
            role: 'assistant',
            content: 'Welcome to eVidyaloka! I\'m here to help you get started as a volunteer. What brings you here today?',
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
      const response = await orchestratorApi.interact(sessionId, userMessage);
      setSessionId(response.session_id);
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: response.assistant_message },
      ]);
      if (response.journey_progress) {
        setJourneyState({
          currentState: response.state,
          progressPercent: response.journey_progress.progress_percent || 0,
          confirmedFields: response.journey_progress.confirmed_fields || {},
          missingFields: response.journey_progress.missing_fields || [],
        });
      }
    } catch (error) {
      console.error('Failed to send message:', error);
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: 'I apologize, but I encountered an issue. Please try again.',
        },
      ]);
    }
    setIsLoading(false);
    inputRef.current?.focus();
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleReset = () => {
    setSessionId(null);
    setMessages([]);
    setJourneyState({
      currentState: 'init',
      progressPercent: 0,
      confirmedFields: {},
      missingFields: [],
    });
    window.location.reload();
  };

  return (
    <div className="flex h-screen bg-white" data-testid="volunteer-view">
      {/* Chat Area */}
      <div className="flex-1 flex flex-col max-w-3xl mx-auto w-full">
        {/* Header */}
        <div className="p-4 border-b border-slate-200 flex items-center justify-between bg-white">
          <div className="flex items-center gap-3">
            {onBack && (
              <Button
                variant="ghost"
                size="sm"
                onClick={onBack}
                className="mr-2"
                data-testid="back-btn"
              >
                <ArrowLeft className="w-4 h-4" />
              </Button>
            )}
            <div className="w-9 h-9 rounded-full bg-amber-100 flex items-center justify-center">
              <BookOpen className="w-4 h-4 text-amber-600" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-900">
                eVidyaloka
              </h2>
              <p className="text-sm text-slate-500">
                Let's get you started as a volunteer
              </p>
            </div>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleReset}
            data-testid="reset-conversation-btn"
          >
            <RefreshCw className="w-4 h-4 mr-2" />
            Start Over
          </Button>
        </div>

        {/* Messages */}
        <ScrollArea className="flex-1 p-4 bg-slate-50">
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
                <div className="message-content chat-bubble-assistant">
                  <TypingIndicator />
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        </ScrollArea>

        {/* Input Area */}
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
              data-testid="chat-input"
            />
            <Button
              onClick={handleSend}
              disabled={!inputValue.trim() || isLoading}
              className="bg-amber-500 hover:bg-amber-600 text-white"
              data-testid="send-message-btn"
            >
              {isLoading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Send className="w-4 h-4" />
              )}
            </Button>
          </div>
        </div>
      </div>

      {/* Journey Progress Sidebar */}
      <div className="hidden lg:block w-80 border-l border-slate-200 p-4 bg-white">
        <JourneyProgress
          currentState={journeyState.currentState}
          progressPercent={journeyState.progressPercent}
        />

        {Object.keys(journeyState.confirmedFields).length > 0 && (
          <div className="mt-6 p-4 bg-slate-50 rounded-lg border border-slate-200">
            <h4 className="text-sm font-semibold text-slate-700 mb-3">
              Your Profile
            </h4>
            <div className="space-y-2">
              {Object.entries(journeyState.confirmedFields).map(([key, value]) => (
                <div key={key} className="text-sm">
                  <span className="text-slate-500 capitalize">
                    {key.replace(/_/g, ' ')}:
                  </span>{' '}
                  <span className="text-slate-900">
                    {Array.isArray(value) ? value.join(', ') : String(value)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default VolunteerView;
