// Allo AI palette (light/dark). The accent is an electric violet used for solid UI (buttons, stats, profile icon);
// the brighter acoustic cyan neon (`accentNeon`) is reserved for the logo, waveform meters, active calls & glowing borders.

const ACCENT = '#7928CA';
const ACCENT_HOVER = '#6B21A8';
const ACCENT_NEON = '#00F2FE';
const ACCENT_NEON_HOVER = '#38BDF8';

export const lightTheme = {
  mode: 'light',
  colors: {
    background: '#F8FAFC',
    surface: '#FFFFFF',
    primary: '#0F172A',
    secondary: '#475569',
    muted: '#94A3B8',
    border: '#E2E8F0',
    divider: '#F1F5F9',
    hover: '#F1F5F9',
    accent: ACCENT,
    accentHover: ACCENT_HOVER,
    accentNeon: '#0284C7',
    accentNeonHover: '#0369A1',
    accentCyan: '#00F2FE',
    accentMagenta: '#FF0080',
    stateLive: '#10B981',
  },
};

export const darkTheme = {
  mode: 'dark',
  colors: {
    background: '#050711',
    surface: '#0A0F26',
    primary: '#F8FAFC',
    secondary: '#94A3B8',
    muted: '#64748B',
    border: '#1E264F',
    divider: '#1E264F',
    hover: '#12183A',
    accent: ACCENT,
    accentHover: ACCENT_HOVER,
    accentNeon: ACCENT_NEON,
    accentNeonHover: ACCENT_NEON_HOVER,
    accentCyan: '#00F2FE',
    accentMagenta: '#FF0080',
    stateLive: '#10B981',
  },
};
