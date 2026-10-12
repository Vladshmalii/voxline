import styled, { keyframes } from 'styled-components';
import { FiRefreshCw } from 'react-icons/fi';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { SecondaryButton } from 'components/ui';

const spin = keyframes`
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
`;

const Button = styled(SecondaryButton)`
  display: inline-flex;
  align-items: center;
  gap: 6px;

  svg {
    animation: ${({ $busy }) => ($busy ? spin : 'none')} 1s linear infinite;
  }
`;

/**
 * Header refresh button for table views: SecondaryButton + FiRefreshCw that
 * spins while `loading`. Same look/position as the Admin stats and Billing
 * pages (first-class citizen of HeaderActions).
 */
export const RefreshButton = ({ onClick, loading = false }) => {
  const { theme } = useTheme();
  const { t } = useI18n();
  return (
    <Button
      theme={theme}
      type="button"
      $busy={loading}
      disabled={loading}
      onClick={onClick}
      title={t('common.refresh')}
      aria-label={t('common.refresh')}
    >
      <FiRefreshCw size={14} />
    </Button>
  );
};
