/**
 * TypingIndicator — Animated dots shown while agent is processing.
 * Shows reassurance messages if response takes longer than expected.
 */
import { useState, useEffect } from 'react';

export function TypingIndicator() {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setElapsed(s => s + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const message = elapsed >= 15
    ? "Almost there — just finishing up…"
    : elapsed >= 8
      ? "Setting things up for you — this may take a moment…"
      : null;

  return (
    <div className="flex flex-col items-start gap-1.5">
      <div className="typing-indicator" aria-label="Agent is typing">
        <div className="typing-dot" />
        <div className="typing-dot" />
        <div className="typing-dot" />
      </div>
      {message && (
        <p className="text-xs text-slate-400 animate-fade-in pl-1">
          {message}
        </p>
      )}
    </div>
  );
}

export default TypingIndicator;
