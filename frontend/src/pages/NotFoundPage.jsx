import styled from 'styled-components';
import { Link } from 'react-router-dom';
import { useI18n } from 'contexts/I18nContext';
import { Logo } from 'app/Logo';

const Page = styled.div`
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 24px;
  text-align: center;
  background-color: ${({ theme }) => theme.colors.background};
`;

const Code = styled.div`
  margin-top: 18px;
  font-size: clamp(72px, 14vw, 132px);
  font-weight: 800;
  line-height: 1;
  letter-spacing: -0.05em;
  background: linear-gradient(135deg, #4f8bff, #1d4ed8);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
`;

const Text = styled.p`
  font-size: 16px;
  color: ${({ theme }) => theme.colors.secondary};
  margin: 0 0 18px;
`;

const HomeLink = styled(Link)`
  display: inline-flex;
  align-items: center;
  height: 38px;
  padding: 0 18px;
  border-radius: ${({ theme }) => theme.radii.sm};
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
  color: ${({ theme }) => theme.colors.onAccent};
  background-color: ${({ theme }) => theme.colors.accent};
  box-shadow: ${({ theme }) => theme.shadows.lift};

  &:hover {
    background-color: ${({ theme }) => theme.colors.accentHover};
  }
`;

export const NotFoundPage = () => {
  const { t } = useI18n();

  return (
    <Page>
      <Logo size={44} />
      <Code>404</Code>
      <Text>{t('system.notFoundText')}</Text>
      <HomeLink to="/">{t('system.goHome')}</HomeLink>
    </Page>
  );
};
