/**
 * ChatInput — Text input with send button for the conversation workspace.
 */
import { useState, useRef, useEffect } from 'react';
import { Send, Loader2 } from 'lucide-react';
import { Button } from '../ui/button';

export function ChatInput({ onSend, disabled = false, loading = false, placeholder = 'Type your message...' }) {
  const [value, setValue] = useState('');
  const inputRef = useRef(null);

  // Focus input on mount
  useEffect(() => {
    if (!disabled) {
      inputRef.current?.focus();
    }
  }, [disabled]);

  const handleSend = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled || loading) return;
    onSend(trimmed);
    setValue('');
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex items-end gap-2 p-4 border-t border-slate-200 bg-white">
      <textarea
        ref={inputRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={disabled || loading}
        rows={1}
        className="flex-1 resize-none rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50 max-h-32 overflow-y-auto"
        style={{ minHeight: '40px' }}
        aria-label="Message input"
      />
      <Button
        onClick={handleSend}
        disabled={!value.trim() || disabled || loading}
        size="icon"
        className="h-10 w-10 rounded-xl bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-40"
        aria-label="Send message"
      >
        {loading ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <Send className="w-4 h-4" />
        )}
      </Button>
    </div>
  );
}

export default ChatInput;
