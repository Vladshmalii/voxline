// The Voxline mark: a rounded tile with a voice-level meter.
export const Logo = ({ size = 32 }) => (
  <svg width={size} height={size} viewBox="0 0 32 32" role="img" aria-hidden="true" focusable="false">
    <defs>
      <linearGradient id="vx-tile" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="#4F8BFF" />
        <stop offset="1" stopColor="#1D4ED8" />
      </linearGradient>
    </defs>
    <rect width="32" height="32" rx="9" fill="url(#vx-tile)" />
    <g fill="#fff">
      <rect x="6" y="13" width="3" height="6" rx="1.5" opacity="0.7" />
      <rect x="11.2" y="9" width="3" height="14" rx="1.5" />
      <rect x="16.4" y="6" width="3" height="20" rx="1.5" />
      <rect x="21.6" y="10" width="3" height="12" rx="1.5" />
      <rect x="26.8" y="14" width="0" height="4" rx="1.5" />
    </g>
  </svg>
);
