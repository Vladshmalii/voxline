import { useMemo, useState } from 'react';
import styled from 'styled-components';

// Total and completed trend, with an optional failed series, in plain SVG — no
// charting library, matching the app's existing convention (see
// DashboardPage's hand-rolled BarList; package.json carries none). Crosshair
// + tooltip on hover; every plotted point also carries a native <title>, so
// the raw numbers are reachable without JS hover too.

// The viewBox is in the same order of magnitude as the card's real rendered
// width (a full-width dashboard card is ~1100-1300px) — SVG stroke-width and
// font-size are viewBox units, not screen pixels, so a narrow viewBox like
// 640 on a ~1300px-wide card scaled everything up ~2x (thick lines, huge
// axis text). vector-effect="non-scaling-stroke" below is a second
// safeguard so lines stay a true 2px regardless of how wide the card ends
// up being.
const WIDTH = 1200;
const HEIGHT = 190;
const PAD_TOP = 14;
const PAD_BOTTOM = 26;
const PAD_LEFT = 6;
const PAD_RIGHT = 6;
const GRID_LINES = 3;

const ChartArea = styled.div`
  position: relative;
`;

const Legend = styled.div`
  display: flex;
  gap: 14px;
  margin-bottom: 6px;
`;

const LegendItem = styled.div`
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: ${({ theme }) => theme.colors.secondary};
`;

const Dot = styled.span`
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: ${({ $color }) => $color};
  flex-shrink: 0;
`;

const Svg = styled.svg`
  display: block;
  width: 100%;
  height: auto;
  overflow: visible;
`;

const AxisLabel = styled.text`
  font-size: 12px;
  fill: ${({ theme }) => theme.colors.muted};
`;

const Tooltip = styled.div`
  position: absolute;
  pointer-events: none;
  top: 0;
  left: ${({ $left }) => $left}%;
  transform: translate(-50%, 0);
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.sm};
  padding: 8px 10px;
  font-size: 12px;
  color: ${({ theme }) => theme.colors.primary};
  white-space: nowrap;
  box-shadow: ${({ theme }) => theme.shadows.pop};
  z-index: 2;
`;

const TooltipDate = styled.div`
  font-weight: 600;
  margin-bottom: 4px;
`;

const TooltipRow = styled.div`
  display: flex;
  align-items: center;
  gap: 6px;
  font-variant-numeric: tabular-nums;

  & + & {
    margin-top: 2px;
  }
`;

/**
 * @param data {Array<{date: string, total: number, completed?: number, success?: number, failed?: number}>}
 */
export const TrendChart = ({
  theme,
  data,
  totalColor,
  completedColor = '#16A34A',
  failedColor = '#DC2626',
  totalLabel = 'Total',
  completedLabel = 'Success',
  failedLabel = 'Failed',
  showFailed = true,
  formatDate,
  formatDateShort,
}) => {
  const [hoverIndex, setHoverIndex] = useState(null);

  const { points, ticks, maxValue } = useMemo(() => {
    const plotWidth = WIDTH - PAD_LEFT - PAD_RIGHT;
    const plotHeight = HEIGHT - PAD_TOP - PAD_BOTTOM;
    const maxValue = Math.max(1, ...data.map((d) => d.total));
    const step = data.length > 1 ? plotWidth / (data.length - 1) : 0;
    const points = data.map((d, i) => {
      const successCount = d.success ?? d.completed ?? 0;
      const failedCount = d.failed ?? Math.max(0, d.total - successCount);
      return {
        ...d,
        success: successCount,
        failed: failedCount,
        x: PAD_LEFT + step * i,
        yTotal: PAD_TOP + plotHeight * (1 - d.total / maxValue),
        ySuccess: PAD_TOP + plotHeight * (1 - successCount / maxValue),
        yFailed: PAD_TOP + plotHeight * (1 - failedCount / maxValue),
      };
    });
    const tickCount = Math.min(6, data.length);
    const ticks =
      tickCount > 1
        ? Array.from({ length: tickCount }, (_, i) =>
            points[Math.round((i * (points.length - 1)) / (tickCount - 1))]
          )
        : points;
    return { points, ticks, maxValue };
  }, [data]);

  if (points.length === 0) return null;

  const linePath = (key) =>
    points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p[key]}`).join(' ');

  const areaPath = () => {
    const plotHeight = HEIGHT - PAD_TOP - PAD_BOTTOM;
    const baseline = PAD_TOP + plotHeight;
    return (
      `M ${points[0].x} ${baseline} ` +
      points.map((p) => `L ${p.x} ${p.yTotal}`).join(' ') +
      ` L ${points[points.length - 1].x} ${baseline} Z`
    );
  };

  const handleMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const index = Math.round(ratio * (points.length - 1));
    setHoverIndex(index);
  };

  const hovered = hoverIndex != null ? points[hoverIndex] : null;
  const gridValues = Array.from({ length: GRID_LINES + 1 }, (_, i) => (maxValue / GRID_LINES) * i);

  return (
    <div>
      <Legend>
        <LegendItem theme={theme}>
          <Dot $color={totalColor} />
          {totalLabel}
        </LegendItem>
        <LegendItem theme={theme}>
          <Dot $color={completedColor} />
          {completedLabel}
        </LegendItem>
        {showFailed && <LegendItem theme={theme}>
          <Dot $color={failedColor} />
          {failedLabel}
        </LegendItem>}
      </Legend>

      <ChartArea>
        <Svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          onMouseMove={handleMove}
          onMouseLeave={() => setHoverIndex(null)}
        >
          {gridValues.map((v) => {
            const plotHeight = HEIGHT - PAD_TOP - PAD_BOTTOM;
            const y = PAD_TOP + plotHeight * (1 - v / maxValue);
            return (
              <line
                key={v}
                x1={PAD_LEFT}
                x2={WIDTH - PAD_RIGHT}
                y1={y}
                y2={y}
                stroke={theme.colors.divider}
                strokeWidth={1}
                vectorEffect="non-scaling-stroke"
              />
            );
          })}

          <path d={areaPath()} fill={totalColor} opacity={0.10} stroke="none" />
          <path
            d={linePath('yTotal')}
            fill="none"
            stroke={totalColor}
            strokeWidth={2}
            vectorEffect="non-scaling-stroke"
          />
          <path
            d={linePath('ySuccess')}
            fill="none"
            stroke={completedColor}
            strokeWidth={2}
            vectorEffect="non-scaling-stroke"
          />
          {showFailed && <path
            d={linePath('yFailed')}
            fill="none"
            stroke={failedColor}
            strokeWidth={1.75}
            strokeDasharray="4 3"
            vectorEffect="non-scaling-stroke"
          />}

          {points.map((p, i) => (
            <g key={p.date}>
              <circle cx={p.x} cy={p.yTotal} r={hoverIndex === i ? 4 : 0} fill={totalColor}>
                <title>
                  {formatDate(p.date)}: {totalLabel} {p.total}
                </title>
              </circle>
              <circle cx={p.x} cy={p.ySuccess} r={hoverIndex === i ? 4 : 0} fill={completedColor}>
                <title>
                  {formatDate(p.date)}: {completedLabel} {p.success}
                </title>
              </circle>
              {showFailed && <circle cx={p.x} cy={p.yFailed} r={hoverIndex === i ? 4 : 0} fill={failedColor}>
                <title>
                  {formatDate(p.date)}: {failedLabel} {p.failed}
                </title>
              </circle>}
            </g>
          ))}

          {hovered && (
            <line
              x1={hovered.x}
              x2={hovered.x}
              y1={PAD_TOP}
              y2={HEIGHT - PAD_BOTTOM}
              stroke={theme.colors.secondary}
              strokeWidth={1}
              strokeDasharray="3 3"
              vectorEffect="non-scaling-stroke"
            />
          )}

          {ticks.map((p) => (
            <AxisLabel key={p.date} theme={theme} x={p.x} y={HEIGHT - 6} textAnchor="middle">
              {formatDateShort(p.date)}
            </AxisLabel>
          ))}
        </Svg>

        {hovered && (
          <Tooltip theme={theme} $left={(hovered.x / WIDTH) * 100}>
            <TooltipDate>{formatDate(hovered.date)}</TooltipDate>
            <TooltipRow>
              <Dot $color={totalColor} />
              {totalLabel}: <strong>{hovered.total}</strong>
            </TooltipRow>
            <TooltipRow>
              <Dot $color={completedColor} />
              {completedLabel}: <strong>{hovered.success}</strong>
            </TooltipRow>
            {showFailed && <TooltipRow>
              <Dot $color={failedColor} />
              {failedLabel}: <strong>{hovered.failed}</strong>
            </TooltipRow>}
          </Tooltip>
        )}
      </ChartArea>
    </div>
  );
};
