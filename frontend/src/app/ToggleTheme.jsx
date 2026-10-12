import styled from 'styled-components';
import { HiSun, HiMoon } from 'react-icons/hi2';
import { useTheme } from 'contexts/ThemeContext';

const ToggleContainer = styled.div`
  display: flex;
  align-items: center;
  gap: 10px;
`;

const SunIcon = styled(HiSun)`
  color: ${({ $isDark }) => (!$isDark ? '#212121' : '#9E9E9E')};
  font-size: 20px;
  transition: color 0.3s ease;
`;

const MoonIcon = styled(HiMoon)`
  color: ${({ $isDark }) => ($isDark ? '#FFFFFF' : '#9E9E9E')};
  font-size: 20px;
  transition: color 0.3s ease;
`;

const SwitchLabel = styled.label`
  position: relative;
  display: inline-block;
  width: 50px;
  height: 28px;
  cursor: pointer;
`;

const SwitchInput = styled.input`
  opacity: 0;
  width: 0;
  height: 0;
`;

const SwitchSlider = styled.span`
  position: absolute;
  inset: 0;
  background-color: ${({ theme }) => theme.colors.border};
  border-radius: 28px;
  transition: background-color 0.3s ease;

  &::before {
    content: '';
    position: absolute;
    height: 22px;
    width: 22px;
    left: ${({ $isDark }) => ($isDark ? '24px' : '3px')};
    top: 3px;
    background-color: #ffffff;
    border-radius: 50%;
    transition: all 0.3s ease;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
  }
`;

export const ToggleTheme = () => {
  const { isDark, toggleTheme, theme } = useTheme();

  return (
    <ToggleContainer>
      <SunIcon $isDark={isDark} />
      <SwitchLabel>
        <SwitchInput type="checkbox" checked={isDark} onChange={toggleTheme} />
        <SwitchSlider theme={theme} $isDark={isDark} />
      </SwitchLabel>
      <MoonIcon $isDark={isDark} />
    </ToggleContainer>
  );
};
