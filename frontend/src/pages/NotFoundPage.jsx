import styled from 'styled-components';
import { Link } from 'react-router-dom';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';

const Page = styled.div`
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background-color: ${({ theme }) => theme.colors.background};
  padding: 40px 20px;
`;

const Code = styled.div`
  font-size: 72px;
  font-weight: 800;
  color: ${({ theme }) => theme.colors.accent};
  line-height: 1;
  margin-bottom: 16px;
`;

const Text = styled.p`
  font-size: 16px;
  color: ${({ theme }) => theme.colors.secondary};
  margin: 0 0 32px;
`;

const HomeLink = styled(Link)`
  padding: 12px 24px;
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  text-decoration: none;
  color: ${({ theme }) => theme.colors.primary};
  background-color: ${({ theme }) => theme.colors.surface};
  transition: border-color 0.2s, background-color 0.2s;

  &:hover {
    border-color: ${({ theme }) => theme.colors.accentNeon};
    background-color: ${({ theme }) => theme.colors.hover};
  }
`;

export const NotFoundPage = () => {
  const { theme } = useTheme();
  const { t } = useI18n();

  return (
    <Page theme={theme}>
      <Code theme={theme}>404</Code>
      <Text theme={theme}>{t('system.notFoundText')}</Text>
      <HomeLink theme={theme} to="/">
        {t('system.goHome')}
      </HomeLink>
    </Page>
  );
};
