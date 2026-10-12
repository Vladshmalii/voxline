import styled, { css } from 'styled-components';

// Shared page skeleton + controls. Modern SaaS look: soft grey canvas, white
// cards with a hairline border and a whisper of shadow, 36px controls, 8px
// corners, one blue accent. Tokens come from theme/colors.js.

export const PageContent = styled.div`
  display: flex;
  flex-direction: column;
  min-height: 100%;
`;

export const HeaderSection = styled.div`
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 12px 20px;
  padding: 24px 20px 4px;
  flex-shrink: 0;

  @media (min-width: 961px) {
    padding: 28px 32px 4px;
  }
`;

export const PageTitle = styled.h2`
  margin: 0;
  font-size: clamp(20px, 2.4vw, 24px);
  font-weight: 650;
  line-height: 1.25;
  letter-spacing: -0.02em;
  color: ${({ theme }) => theme.colors.primary};
  flex-shrink: 0;
`;

export const HeaderActions = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 10px;
`;

export const ContentScroll = styled.div`
  flex: 1;
  padding: 20px 20px 48px;

  @media (min-width: 961px) {
    padding: 24px 32px 56px;
  }
`;

export const Card = styled.div`
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.md};
  background: ${({ theme }) => theme.colors.surface};
  box-shadow: ${({ theme }) => theme.shadows.card};
  padding: 20px;
`;

const buttonBase = css`
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 36px;
  padding: 0 14px;
  font-size: 13.5px;
  font-weight: 550;
  line-height: 1;
  border-radius: ${({ theme }) => theme.radii.sm};
  cursor: pointer;
  white-space: nowrap;
  transition: background-color 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease,
    color 0.15s ease;

  &:disabled {
    opacity: 0.5;
    cursor: default;
  }
`;

export const PrimaryButton = styled.button`
  ${buttonBase}
  color: ${({ theme }) => theme.colors.onAccent};
  background: ${({ theme }) => theme.colors.accent};
  border: 1px solid transparent;
  box-shadow: ${({ theme }) => theme.shadows.lift};

  &:hover:not(:disabled) {
    background: ${({ theme }) => theme.colors.accentHover};
  }
`;

export const SecondaryButton = styled.button`
  ${buttonBase}
  color: ${({ theme }) => theme.colors.primary};
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  box-shadow: ${({ theme }) => theme.shadows.card};

  &:hover:not(:disabled) {
    background: ${({ theme }) => theme.colors.hover};
    border-color: ${({ theme }) => theme.colors.muted};
  }
`;

export const DangerButton = styled(SecondaryButton)`
  color: ${({ theme }) => theme.colors.danger};

  &:hover:not(:disabled) {
    background: ${({ theme }) => theme.colors.danger}14;
    border-color: ${({ theme }) => theme.colors.danger};
  }
`;

const fieldBase = css`
  width: 100%;
  height: 36px;
  padding: 0 12px;
  font-size: 14px;
  color: ${({ theme }) => theme.colors.primary};
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ $invalid, theme }) => ($invalid ? theme.colors.danger : theme.colors.border)};
  border-radius: ${({ theme }) => theme.radii.sm};
  transition: border-color 0.15s ease, box-shadow 0.15s ease;

  &::placeholder {
    color: ${({ theme }) => theme.colors.muted};
  }

  &:hover:not(:disabled):not(:focus) {
    border-color: ${({ $invalid, theme }) => ($invalid ? theme.colors.danger : theme.colors.muted)};
  }

  &:focus {
    outline: none;
    border-color: ${({ $invalid, theme }) => ($invalid ? theme.colors.danger : theme.colors.accentNeon)};
    box-shadow: 0 0 0 3px
      ${({ $invalid, theme }) => ($invalid ? theme.colors.danger : theme.colors.accentNeon)}33;
  }

  &:disabled {
    opacity: 0.6;
    background: ${({ theme }) => theme.colors.surfaceAlt};
  }
`;

export const TextInput = styled.input`
  ${fieldBase}
`;

export const Select = styled.select`
  ${fieldBase}
  cursor: pointer;
`;

export const TextArea = styled.textarea`
  ${fieldBase}
  height: auto;
  padding: 9px 12px;
  font-family: ${({ theme }) => theme.fonts.mono};
  font-size: 12.5px;
  line-height: 1.55;
  resize: vertical;
  min-height: 84px;
`;

export const FieldLabel = styled.label`
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 550;
  color: ${({ theme }) => theme.colors.primary};
`;

export const FieldGroup = styled.div`
  margin-bottom: 16px;
`;

export const FieldHint = styled.div`
  margin-top: 5px;
  font-size: 12px;
  color: ${({ $error, theme }) => ($error ? theme.colors.danger : theme.colors.muted)};
`;

export const CheckboxLabel = styled.label`
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  color: ${({ theme }) => theme.colors.primary};
  cursor: pointer;
  user-select: none;

  input {
    width: 16px;
    height: 16px;
    accent-color: ${({ theme }) => theme.colors.accent};
    cursor: pointer;
  }
`;

export const TableContainer = styled.div`
  width: 100%;
  overflow-x: auto;
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.md};
  background: ${({ theme }) => theme.colors.surface};
  box-shadow: ${({ theme }) => theme.shadows.card};
`;

export const Table = styled.table`
  width: 100%;
  border-collapse: collapse;
  font-size: 13.5px;
`;

export const TableHeader = styled.thead`
  position: sticky;
  top: 0;
  z-index: 10;
  background: ${({ theme }) => theme.colors.surfaceAlt};
  box-shadow: inset 0 -1px 0 ${({ theme }) => theme.colors.border};
`;

export const TableHeaderCell = styled.th`
  padding: 11px 16px;
  text-align: left;
  vertical-align: middle;
  font-size: 12px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.secondary};
  white-space: nowrap;
  ${({ $align }) => $align === 'right' && 'text-align: right;'}
  ${({ $align }) => $align === 'center' && 'text-align: center;'}
`;

export const TableRow = styled.tr`
  border-bottom: 1px solid ${({ theme }) => theme.colors.divider};
  transition: background-color 0.1s ease;

  &:last-child {
    border-bottom: none;
  }

  &:hover {
    background-color: ${({ theme }) => theme.colors.hover};
  }
`;

export const TableCell = styled.td`
  padding: 12px 16px;
  font-size: 13.5px;
  color: ${({ theme }) => theme.colors.primary};
  vertical-align: middle;
  ${({ $align }) => $align === 'right' && 'text-align: right;'}
  ${({ $align }) => $align === 'center' && 'text-align: center;'}
`;

export const UploadArea = styled.textarea`
  width: 100%;
  min-height: 140px;
  font-family: ${({ theme }) => theme.fonts.mono};
  font-size: 12.5px;
  padding: 12px;
  border-radius: ${({ theme }) => theme.radii.sm};
  border: 1px dashed ${({ theme }) => theme.colors.border};
  background: ${({ theme }) => theme.colors.surface};
  color: ${({ theme }) => theme.colors.primary};
  resize: vertical;

  &:focus {
    outline: none;
    border-style: solid;
    border-color: ${({ theme }) => theme.colors.accentNeon};
    box-shadow: 0 0 0 3px ${({ theme }) => theme.colors.accentNeon}33;
  }
`;

export const ResultTable = styled.table`
  width: 100%;
  font-size: 12.5px;
  border-collapse: collapse;

  th,
  td {
    text-align: left;
    padding: 7px 8px;
    border-bottom: 1px solid ${({ theme }) => theme.colors.divider};
  }

  th {
    font-weight: 600;
    color: ${({ theme }) => theme.colors.secondary};
  }
`;

// A soft status pill. The colour (any hex) is pulled toward the text colour so
// the label keeps contrast in both modes.
export const Badge = styled.span`
  display: inline-flex;
  align-items: center;
  padding: 2px 9px;
  font-size: 12px;
  font-weight: 550;
  line-height: 1.5;
  border-radius: ${({ theme }) => theme.radii.pill};
  white-space: nowrap;
  color: ${({ $color, theme }) =>
    `color-mix(in srgb, ${$color || '#64748B'} 78%, ${theme.colors.primary})`};
  background: ${({ $color }) => `${$color || '#64748B'}1f`};
`;

export const EmptyState = styled.div`
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 220px;
  padding: 28px;
  color: ${({ theme }) => theme.colors.secondary};
  text-align: center;
  border: 1px dashed ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.md};
`;

export const EmptyStateTitle = styled.h2`
  font-size: 18px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.primary};
  margin: 0 0 6px 0;
`;

export const EmptyStateText = styled.p`
  font-size: 14px;
  color: ${({ theme }) => theme.colors.secondary};
  margin: 0;
  max-width: 46ch;
`;

export const RowActions = styled.div`
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
`;

export const RowActionButton = styled.button`
  height: 28px;
  padding: 0 10px;
  font-size: 12.5px;
  font-weight: 550;
  color: ${({ $danger, theme }) => ($danger ? theme.colors.danger : theme.colors.primary)};
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.xs};
  cursor: pointer;
  white-space: nowrap;
  transition: background-color 0.12s ease, border-color 0.12s ease;

  &:hover:not(:disabled) {
    background: ${({ $danger, theme }) => ($danger ? `${theme.colors.danger}14` : theme.colors.hover)};
    border-color: ${({ $danger, theme }) => ($danger ? theme.colors.danger : theme.colors.muted)};
  }

  &:disabled {
    opacity: 0.5;
    cursor: default;
  }
`;

// Segmented control: one rail, the active option raised on it. Used for period
// pickers, tabs and any "pick one of a few" choice.
export const Segmented = styled.div`
  display: inline-flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 2px;
  max-width: 100%;
  padding: 3px;
  overflow-x: auto;
  scrollbar-width: none;
  background: ${({ theme }) => theme.colors.surfaceAlt};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.sm};

  &::-webkit-scrollbar {
    display: none;
  }
`;

export const SegmentOption = styled.button`
  flex-shrink: 0;
  height: 28px;
  padding: 0 12px;
  font-size: 13px;
  font-weight: ${({ $active }) => ($active ? 600 : 500)};
  white-space: nowrap;
  border: none;
  border-radius: ${({ theme }) => theme.radii.xs};
  cursor: ${({ $active }) => ($active ? 'default' : 'pointer')};
  color: ${({ $active, theme }) => ($active ? theme.colors.primary : theme.colors.secondary)};
  background: ${({ $active, theme }) => ($active ? theme.colors.raised : 'transparent')};
  box-shadow: ${({ $active, theme }) => ($active ? theme.shadows.lift : 'none')};
  transition: background-color 0.12s ease, color 0.12s ease, box-shadow 0.12s ease;

  &:hover:not(:disabled) {
    color: ${({ theme }) => theme.colors.primary};
  }
`;

// Status colours/labels/icons live in utils/statusMap.js.

export const formatDateTime = (value) => {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
};
