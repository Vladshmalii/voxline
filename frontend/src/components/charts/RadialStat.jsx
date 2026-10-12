import styled from 'styled-components';

// A single-proportion ring (answer rate) — not part-to-whole across many
// categories (that stays BarList elsewhere on this page), just one ratio, so
// a radial gauge is the right form here.

const Svg = styled.svg`
  flex-shrink: 0;
`;

const Track = styled.circle`
  fill: none;
  stroke: ${({ theme }) => theme.colors.hover};
`;

const Arc = styled.circle`
  fill: none;
  stroke-linecap: round;
`;

export const RadialStat = ({ theme, ratio, size = 26, stroke = 3, color }) => {
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  const pct = ratio == null ? 0 : Math.max(0, Math.min(1, ratio));
  const dash = circumference * pct;

  return (
    <Svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <Track theme={theme} cx={size / 2} cy={size / 2} r={r} strokeWidth={stroke} />
      <Arc
        cx={size / 2}
        cy={size / 2}
        r={r}
        strokeWidth={stroke}
        stroke={color || theme.colors.accent}
        strokeDasharray={`${dash} ${circumference - dash}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      >
        <title>{ratio == null ? '—' : `${Math.round(ratio * 100)}%`}</title>
      </Arc>
    </Svg>
  );
};
