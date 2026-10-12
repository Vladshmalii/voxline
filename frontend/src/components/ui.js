import styled from 'styled-components';

// Shared page skeleton + controls, extracted from the chat service's
// statistics page so every tab keeps the same design language.

export const PageContent = styled.div`
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
`;

export const HeaderSection = styled.div`
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 12px 20px;
  padding: 12px 16px;
  min-height: 69px;
  border-bottom: 1px solid ${({ theme }) => theme.colors.border};
  flex-shrink: 0;
  box-sizing: border-box;

  @media (min-width: 961px) {
    padding: 12px 20px;
  }
`;

export const PageTitle = styled.h2`
  margin: 0;
  font-size: clamp(17px, 2.5vw, 20px);
  font-weight: 600;
  color: ${({ theme }) => theme.colors.primary};
  flex-shrink: 0;
`;

export const HeaderActions = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 12px;
`;

export const ContentScroll = styled.div`
  flex: 1;
  padding: 16px 12px;
  overflow-y: auto;
  box-sizing: border-box;

  @media (min-width: 600px) {
    padding: 20px 16px;
  }

  @media (min-width: 960px) {
    padding: 24px;
  }

  &::-webkit-scrollbar {
    width: 8px;
  }

  &::-webkit-scrollbar-track {
    background: ${({ theme }) => theme.colors.background};
    border-radius: 4px;
  }

  &::-webkit-scrollbar-thumb {
    background: ${({ theme }) => theme.colors.border};
    border-radius: 4px;

    &:hover {
      background: ${({ theme }) => theme.colors.secondary};
    }
  }
`;

export const Card = styled.div`
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 16px;
  background: ${({ theme }) => theme.colors.surface};
  padding: 16px;
`;

export const PrimaryButton = styled.button`
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  background: ${({ theme }) => theme.colors.accent};
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s ease;

  &:hover {
    background: ${({ theme }) => theme.colors.accentHover};
  }

  &:disabled {
    opacity: 0.6;
    cursor: default;
  }
`;

export const SecondaryButton = styled.button`
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  font-size: 14px;
  color: ${({ theme }) => theme.colors.primary};
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;

  &:hover {
    border-color: ${({ theme }) => theme.colors.secondary};
  }

  &:disabled {
    opacity: 0.6;
    cursor: default;
  }
`;

export const DangerButton = styled(SecondaryButton)`
  color: #ef4444;

  &:hover {
    border-color: #ef4444;
    background: rgba(239, 68, 68, 0.08);
  }
`;

export const TextInput = styled.input`
  width: 100%;
  padding: 8px 12px;
  font-size: 14px;
  color: ${({ theme }) => theme.colors.primary};
  background: ${({ theme }) => theme.colors.background};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 8px;
  box-sizing: border-box;
  transition: border-color 0.15s ease;

  &:hover {
    border-color: ${({ theme }) => theme.colors.secondary};
  }

  &:focus {
    outline: none;
    border-color: ${({ theme }) => theme.colors.accentNeon};
  }

  &:disabled {
    opacity: 0.6;
  }

  &:disabled:hover {
    border-color: ${({ theme }) => theme.colors.border};
  }
`;

export const Select = styled.select`
  width: 100%;
  padding: 8px 12px;
  font-size: 14px;
  color: ${({ theme }) => theme.colors.primary};
  background: ${({ theme }) => theme.colors.background};
  border: 1px solid ${({ $invalid, theme }) => ($invalid ? '#ef4444' : theme.colors.border)};
  border-radius: 8px;
  cursor: pointer;
  box-sizing: border-box;
  transition: border-color 0.15s ease;

  &:hover {
    border-color: ${({ theme }) => theme.colors.secondary};
  }

  &:focus {
    outline: none;
    border-color: ${({ $invalid, theme }) => ($invalid ? '#ef4444' : theme.colors.accentNeon)};
  }

  &:disabled {
    opacity: 0.6;
    cursor: default;
  }

  &:disabled:hover {
    border-color: ${({ $invalid, theme }) => ($invalid ? '#ef4444' : theme.colors.border)};
  }
`;

export const TextArea = styled.textarea`
  width: 100%;
  padding: 8px 12px;
  font-size: 13px;
  font-family: Menlo, Monaco, Consolas, 'Courier New', monospace;
  color: ${({ theme }) => theme.colors.primary};
  background: ${({ theme }) => theme.colors.background};
  border: 1px solid ${({ $invalid, theme }) => ($invalid ? '#ef4444' : theme.colors.border)};
  border-radius: 8px;
  box-sizing: border-box;
  resize: vertical;
  min-height: 72px;
  transition: border-color 0.15s ease;

  &:focus {
    outline: none;
    border-color: ${({ $invalid, theme }) => ($invalid ? '#ef4444' : theme.colors.accentNeon)};
  }

  &:disabled {
    opacity: 0.6;
  }
`;

export const FieldLabel = styled.label`
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 500;
  color: ${({ theme }) => theme.colors.primary};
`;

export const FieldGroup = styled.div`
  margin-bottom: 14px;
`;

export const FieldHint = styled.div`
  margin-top: 4px;
  font-size: 12px;
  color: ${({ $error, theme }) => ($error ? '#ef4444' : theme.colors.secondary)};
`;

export const CheckboxLabel = styled.label`
  display: flex;
  align-items: center;
  gap: 8px;
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
  border-radius: 16px;
  background: ${({ theme }) => theme.colors.surface};

  &::-webkit-scrollbar {
    height: 8px;
  }

  &::-webkit-scrollbar-track {
    background: ${({ theme }) => theme.colors.background};
    border-radius: 4px;
  }

  &::-webkit-scrollbar-thumb {
    background: ${({ theme }) => theme.colors.border};
    border-radius: 4px;

    &:hover {
      background: ${({ theme }) => theme.colors.secondary};
    }
  }
`;

export const Table = styled.table`
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 13px;
  border-radius: 12px;

  thead tr:first-child th:first-child {
    border-top-left-radius: 12px;
  }

  thead tr:first-child th:last-child {
    border-top-right-radius: 12px;
  }

  tbody tr:last-child td:first-child {
    border-bottom-left-radius: 12px;
  }

  tbody tr:last-child td:last-child {
    border-bottom-right-radius: 12px;
  }
`;

export const TableHeader = styled.thead`
  position: sticky;
  top: 0;
  z-index: 10;
  background-color: ${({ theme }) => theme.colors.background};
`;

export const TableHeaderCell = styled.th`
  padding: 12px 16px;
  text-align: left;
  vertical-align: middle;
  font-size: 12px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.secondary};
  text-transform: uppercase;
  letter-spacing: 0.5px;
  white-space: nowrap;
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-top: none;
  ${({ $align }) => $align === 'right' && 'text-align: right;'}
  ${({ $align }) => $align === 'center' && 'text-align: center;'}

  &:first-of-type {
    border-left: none;
  }
  &:last-of-type {
    border-right: none;
  }
`;

export const TableRow = styled.tr`
  transition: background-color 0.15s ease;

  &:hover {
    background-color: ${({ theme }) =>
      theme.colors.primary === '#0D0D0D' ? '#f8f8f8' : 'rgba(255,255,255,0.04)'};
  }
`;

export const TableCell = styled.td`
  padding: 10px 16px;
  font-size: 13px;
  color: ${({ theme }) => theme.colors.primary};
  vertical-align: middle;
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-top: none;
  ${({ $align }) => $align === 'right' && 'text-align: right;'}
  ${({ $align }) => $align === 'center' && 'text-align: center;'}

  &:first-of-type {
    border-left: none;
  }
  &:last-of-type {
    border-right: none;
  }
`;

export const UploadArea = styled.textarea`
  width: 100%;
  min-height: 140px;
  font-family: monospace;
  font-size: 13px;
  padding: 10px;
  border-radius: 8px;
  border: 1px solid ${({ theme }) => theme.colors.border};
  background: ${({ theme }) => theme.colors.background};
  color: ${({ theme }) => theme.colors.primary};
  resize: vertical;
`;

export const ResultTable = styled.table`
  width: 100%;
  font-size: 12.5px;
  border-collapse: collapse;

  th,
  td {
    text-align: left;
    padding: 4px 8px;
    border-bottom: 1px solid ${({ theme }) => theme.colors.border};
  }
`;

export const Badge = styled.span`
  display: inline-block;
  padding: 3px 10px;
  font-size: 11px;
  font-weight: 600;
  border-radius: 999px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: ${({ $color }) => $color || '#6b7280'};
  background: ${({ $color }) => `${$color || '#6b7280'}1f`};
`;

export const EmptyState = styled.div`
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 200px;
  padding: 20px;
  color: ${({ theme }) => theme.colors.secondary};
  text-align: center;
`;

export const EmptyStateTitle = styled.h2`
  font-size: 20px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.primary};
  margin: 0 0 8px 0;
`;

export const EmptyStateText = styled.p`
  font-size: 14px;
  color: ${({ theme }) => theme.colors.secondary};
  margin: 0;
`;

export const RowActions = styled.div`
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
`;

export const RowActionButton = styled.button`
  padding: 5px 10px;
  font-size: 12px;
  color: ${({ $danger, theme }) => ($danger ? '#ef4444' : theme.colors.primary)};
  background: transparent;
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 6px;
  cursor: pointer;
  white-space: nowrap;
  transition: border-color 0.15s ease, background 0.15s ease;

  &:hover {
    border-color: ${({ $danger, theme }) => ($danger ? '#ef4444' : theme.colors.secondary)};
    background: ${({ $danger }) => ($danger ? 'rgba(239, 68, 68, 0.08)' : 'transparent')};
  }

  &:disabled {
    opacity: 0.5;
    cursor: default;
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
