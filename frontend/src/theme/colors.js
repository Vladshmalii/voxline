// Voxline design tokens. A neutral cool-grey scale with one blue accent.
//
// Light = soft grey canvas with white cards. Dark = near-black blue-grey with
// slightly lifted cards. Semantic colours (success / warning / danger / info)
// are the same hue in both modes and are never used as decoration.
//
// Key meaning (names are stable across every styled component):
//   background  app canvas                 surface     cards, tables, panels
//   surfaceAlt  recessed areas, table head hover       row / item hover wash
//   primary     body text                  secondary   supporting text
//   muted       captions, placeholders     border      hairlines around controls
//   divider     quieter inner rules        accent      solid brand fills
//   accentNeon  focus rings, links on dark onAccent     text on an accent fill

export const lightTheme = {
  mode: 'light',
  colors: {
    background: '#F5F6F8',
    surface: '#FFFFFF',
    surfaceAlt: '#EEF1F5',
    raised: '#FFFFFF',
    primary: '#0F172A',
    secondary: '#475569',
    muted: '#64748B',
    border: '#E2E5EB',
    divider: '#EDF0F4',
    hover: '#F1F4F8',
    accent: '#2563EB',
    accentHover: '#1D4ED8',
    accentNeon: '#3B82F6',
    accentNeonHover: '#2563EB',
    accentSoft: '#EAF1FF',
    onAccent: '#FFFFFF',
    success: '#16A34A',
    warning: '#D97706',
    danger: '#DC2626',
    info: '#2563EB',
  },
};

export const darkTheme = {
  mode: 'dark',
  colors: {
    background: '#0B0E14',
    surface: '#131720',
    surfaceAlt: '#0F131A',
    raised: '#283142',
    primary: '#E8ECF3',
    secondary: '#A4ADBD',
    muted: '#7E8899',
    border: '#242A36',
    divider: '#1B212B',
    hover: '#1A202B',
    accent: '#2F6FEB',
    accentHover: '#4D87F5',
    accentNeon: '#6EA0FF',
    accentNeonHover: '#8DB5FF',
    accentSoft: '#16233F',
    onAccent: '#FFFFFF',
    success: '#4ADE80',
    warning: '#FBBF24',
    danger: '#F87171',
    info: '#7DB5FF',
  },
};

const shared = {
  fonts: {
    body: "'Inter Variable', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
    mono: "'JetBrains Mono Variable', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
  },
  radii: { xs: '6px', sm: '8px', md: '12px', lg: '16px', pill: '999px' },
  layout: { sidebar: '264px', sidebarCollapsed: '76px', topbar: '60px' },
};

lightTheme.fonts = darkTheme.fonts = shared.fonts;
lightTheme.radii = darkTheme.radii = shared.radii;
lightTheme.layout = darkTheme.layout = shared.layout;

lightTheme.shadows = {
  card: '0 1px 2px rgba(15, 23, 42, 0.05)',
  lift: '0 1px 2px rgba(15, 23, 42, 0.08), 0 1px 3px rgba(15, 23, 42, 0.06)',
  pop: '0 16px 40px rgba(15, 23, 42, 0.16), 0 2px 6px rgba(15, 23, 42, 0.06)',
};
darkTheme.shadows = {
  card: '0 1px 2px rgba(0, 0, 0, 0.4)',
  lift: '0 1px 2px rgba(0, 0, 0, 0.5)',
  pop: '0 16px 40px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(255, 255, 255, 0.04)',
};
