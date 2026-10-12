import styled from 'styled-components';
import { HiSun, HiMoon } from 'react-icons/hi2';
import { useTheme } from 'contexts/ThemeContext';

// Two visible options, the active one raised: clearer than a bare switch.
const Segmented = styled.div`
  display: inline-flex;
  padding: 3px;
  gap: 2px;
  background: ${({ theme }) => theme.colors.surfaceAlt};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.sm};
`;

const Option = styled.button`
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 26px;
  border: none;
  border-radius: ${({ theme }) => theme.radii.xs};
  background: ${({ $active, theme }) => ($active ? theme.colors.raised : 'transparent')};
  box-shadow: ${({ $active, theme }) => ($active ? theme.shadows.lift : 'none')};
  color: ${({ $active, theme }) => ($active ? theme.colors.primary : theme.colors.muted)};

  &:hover {
    color: ${({ theme }) => theme.colors.primary};
  }

  svg {
    font-size: 16px;
  }
`;

export const ToggleTheme = () => {
  const { isDark, toggleTheme } = useTheme();
  const choose = (wantDark) => {
    if (wantDark !== isDark) toggleTheme();
  };

  return (
    <Segmented role="group" aria-label="Theme">
      <Option type="button" $active={!isDark} aria-pressed={!isDark} aria-label="Light" onClick={() => choose(false)}>
        <HiSun />
      </Option>
      <Option type="button" $active={isDark} aria-pressed={isDark} aria-label="Dark" onClick={() => choose(true)}>
        <HiMoon />
      </Option>
    </Segmented>
  );
};
