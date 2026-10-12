import styled from 'styled-components';
import { Link } from 'react-router-dom';
import { useTheme } from 'contexts/ThemeContext';
import { UserMenu } from 'app/UserMenu';
import { OrgSwitcher } from 'app/OrgSwitcher';

const HeaderStyled = styled.header`
  height: 56px;
  background-color: ${({ theme }) => theme.colors.background};
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  flex-shrink: 0;
`;

const Brand = styled(Link)`
  font-size: 18px;
  font-weight: 800;
  letter-spacing: 0.02em;
  text-decoration: none;
  color: ${({ theme }) => theme.colors.primary};

  span {
    color: ${({ theme }) => theme.colors.accentNeon};
  }
`;

const Right = styled.div`
  display: flex;
  align-items: center;
  gap: 12px;
`;

export const Header = () => {
  const { theme } = useTheme();

  return (
    <HeaderStyled theme={theme}>
      <Brand to="/" theme={theme}>
        <span>V</span>OXLIN<span>E</span>
      </Brand>
      <Right>
        <OrgSwitcher />
        <UserMenu />
      </Right>
    </HeaderStyled>
  );
};
