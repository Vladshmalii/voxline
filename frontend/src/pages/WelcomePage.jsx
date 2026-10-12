import styled from 'styled-components';
import { useTheme } from '../contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';

const Wrap = styled.div`
  padding: 32px;
`;

const Title = styled.h1`
  margin: 0 0 8px;
  font-size: 24px;
  font-weight: 700;
  color: ${({ theme }) => theme.colors.primary};
`;

const Sub = styled.p`
  margin: 0;
  font-size: 14px;
  color: ${({ theme }) => theme.colors.secondary};
`;

export const WelcomePage = () => {
  const { theme } = useTheme();
  const { t } = useI18n();

  return (
    <Wrap>
      <Title theme={theme}>{t('welcome.title')}</Title>
      <Sub theme={theme}>{t('welcome.sub')}</Sub>
    </Wrap>
  );
};
