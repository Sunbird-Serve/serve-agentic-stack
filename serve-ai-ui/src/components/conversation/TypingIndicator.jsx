/**
 * TypingIndicator — Animated dots shown while agent is processing.
 */
export function TypingIndicator() {
  return (
    <div className="typing-indicator" aria-label="Agent is typing">
      <div className="typing-dot" />
      <div className="typing-dot" />
      <div className="typing-dot" />
    </div>
  );
}

export default TypingIndicator;
