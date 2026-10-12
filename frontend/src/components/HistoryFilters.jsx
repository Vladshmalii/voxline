import styled, { keyframes } from 'styled-components';
import { Card, SecondaryButton } from './ui';

export const FilterCard = styled(Card)`
  margin-bottom: 18px;
  padding: 18px 20px;
  @media (max-width: 600px) { padding: 14px; }
`;
export const FilterHeader = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  h3 {
    display: flex; align-items: center; gap: 8px; margin: 0; font-size: 14px;
    color: ${({ theme }) => theme.colors.primary};
  }
  h3 svg { color: ${({ theme }) => theme.colors.accent}; font-size: 18px; }
`;
export const FilterGrid = styled.div`
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  @media (max-width: 1100px) { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  @media (max-width: 600px) { grid-template-columns: 1fr; }
`;

export const Filter = styled.label`
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  font-size: 12px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.secondary};
  input, select { min-width: 0; height: 38px; }
`;
export const SearchFilter = styled(Filter)`
  grid-column: span 2;
  @media (max-width: 600px) { grid-column: auto; }
`;
export const StatusFilter = styled(Filter)`
  @media (min-width: 601px) and (max-width: 1100px) { grid-column: span 2; }
`;
export const PeriodBar = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 16px;
`;
export const PeriodButton = styled(SecondaryButton)`
  padding: 6px 11px;
  font-size: 12px;
  border-color: ${({ theme, $active }) => $active ? theme.colors.accent : theme.colors.border};
  color: ${({ theme, $active }) => $active ? theme.colors.accent : theme.colors.secondary};
  background: ${({ $active }) => $active ? 'rgba(110, 86, 207, 0.08)' : 'transparent'};
`;
export const FilterNote = styled.span`
  font-size: 12px;
  color: ${({ theme }) => theme.colors.secondary};
`;
export const AdvancedToggle = styled(SecondaryButton)`
  font-size: 12px;
  padding: 7px 10px;
  margin-top: 16px;
  svg { transition: transform 180ms ease; transform: rotate(${({ $open }) => $open ? '180deg' : '0deg'}); }
  @media (prefers-reduced-motion: reduce) { svg { transition: none; } }
`;
const appear = keyframes`
  from { opacity: 0; transform: translateY(-5px); }
  to { opacity: 1; transform: translateY(0); }
`;
export const AdvancedGrid = styled(FilterGrid)`
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid ${({ theme }) => theme.colors.border};
  animation: ${appear} 180ms ease;
  @media (prefers-reduced-motion: reduce) { animation: none; }
`;
export const Chips = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 14px;
`;
export const Chip = styled.button`
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  padding: 5px 9px;
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 7px;
  color: ${({ theme }) => theme.colors.accent};
  background: ${({ theme }) => theme.colors.background};
  font-size: 12px;
  cursor: pointer;
  span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  svg { flex-shrink: 0; }
  &:hover { border-color: ${({ theme }) => theme.colors.accent}; }
`;
export const ResultsBar = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
  font-size: 13px;
  color: ${({ theme }) => theme.colors.secondary};
  label { display: flex; align-items: center; gap: 8px; }
  select { width: auto; font-size: 12px; }
`;
const spin = keyframes`
  to { transform: rotate(360deg); }
`;

export const RefreshButton = styled(SecondaryButton)`
  padding: 8px 10px;
  font-size: 16px;

  svg {
    animation: ${({ $busy }) => ($busy ? spin : 'none')} 0.8s linear infinite;
  }
`;

