/**
 * SERVE AI - Logo Component
 * Custom SVG logo aligned with DPGA branding
 */

export const ServeLogo = ({ size = 'md', className = '' }) => {
  const sizes = {
    sm: 'w-8 h-8',
    md: 'w-12 h-12',
    lg: 'w-16 h-16',
    xl: 'w-24 h-24',
  };

  return (
    <div className={`${sizes[size]} ${className}`}>
      <svg
        viewBox="0 0 100 100"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="w-full h-full"
      >
        {/* Background circle with gradient */}
        <defs>
          <linearGradient id="dpga-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#0066CC" />
            <stop offset="100%" stopColor="#00AEEF" />
          </linearGradient>
          <linearGradient id="light-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#00AEEF" />
            <stop offset="100%" stopColor="#0066CC" />
          </linearGradient>
        </defs>
        
        {/* Main circle */}
        <circle cx="50" cy="50" r="45" fill="url(#dpga-gradient)" />
        
        {/* Connection nodes representing volunteers */}
        <circle cx="50" cy="28" r="8" fill="white" opacity="0.95" />
        <circle cx="28" cy="62" r="8" fill="white" opacity="0.95" />
        <circle cx="72" cy="62" r="8" fill="white" opacity="0.95" />
        
        {/* Connection lines */}
        <line x1="50" y1="36" x2="32" y2="56" stroke="white" strokeWidth="3" opacity="0.7" strokeLinecap="round" />
        <line x1="50" y1="36" x2="68" y2="56" stroke="white" strokeWidth="3" opacity="0.7" strokeLinecap="round" />
        <line x1="36" y1="62" x2="64" y2="62" stroke="white" strokeWidth="3" opacity="0.7" strokeLinecap="round" />
        
        {/* Center connection hub */}
        <circle cx="50" cy="50" r="6" fill="white" />
        <circle cx="50" cy="50" r="3" fill="url(#light-gradient)" />
      </svg>
    </div>
  );
};

export default ServeLogo;
