// Voxline palette (light/dark). The accent is a violet used for solid UI (buttons, stats, profile icon); the brighter
// neon violet (`accentNeon`) is reserved for the logo, borders & effects.

const ACCENT = '#6E56CF';
const ACCENT_HOVER = '#5B44B8';
const ACCENT_NEON = '#9A7FFF';
const ACCENT_NEON_HOVER = '#8668F5';

export const lightTheme = {
  mode: 'light',
  colors: {
    background: '#FFFFFF',
    surface: '#F9FAFB',
    primary: '#0D0D0D',
    secondary: '#6B6B6B',
    muted: '#8E8E8E',
    border: '#E5E5E5',
    divider: '#ECECEC',
    hover: '#F3F4F6',
    accent: ACCENT,
    accentHover: ACCENT_HOVER,
    accentNeon: ACCENT_NEON,
    accentNeonHover: ACCENT_NEON_HOVER,
  },
};

export const darkTheme = {
  mode: 'dark',
  colors: {
    background: '#0D0D0D',
    surface: '#1A1A1A',
    primary: '#ECECEC',
    secondary: '#ACACAC',
    muted: '#8E8E8E',
    border: '#2D2D2D',
    divider: '#363636',
    hover: '#2A2A2A',
    accent: ACCENT,
    accentHover: ACCENT_HOVER,
    accentNeon: ACCENT_NEON,
    accentNeonHover: ACCENT_NEON_HOVER,
  },
};
