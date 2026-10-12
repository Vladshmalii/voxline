import styled from 'styled-components';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { SecondaryButton, Select } from 'components/ui';

const Bar = styled.div`
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 14px;
`;

const Info = styled.span`
  font-size: 13px;
  color: ${({ theme }) => theme.colors.secondary};
`;

const PageSizeLabel = styled.label`
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: ${({ theme }) => theme.colors.secondary};

  select {
    min-width: 0;
    padding: 4px 8px;
  }
`;

/**
 * Offset/limit pager, optionally with a page-size dropdown.
 * `pageSize`/`onPageSizeChange` are both required together to show the
 * dropdown — omit both where a fixed page size is fine. `onPageSizeChange`
 * only reports the new size; resetting `offset` to 0 is the caller's job
 * (it already owns that state alongside the fetch that uses it).
 */
export const Pagination = ({
  offset,
  limit,
  total,
  onChange,
  disabled,
  pageSize,
  onPageSizeChange,
  pageSizeOptions = [25, 50, 100],
}) => {
  const { theme } = useTheme();
  const { t } = useI18n();
  if (!total) return null;

  const from = offset + 1;
  const to = Math.min(offset + limit, total);

  return (
    <Bar>
      {onPageSizeChange && (
        <PageSizeLabel theme={theme}>
          {t('common.pagination.perPage')}
          <Select
            theme={theme}
            value={pageSize}
            disabled={disabled}
            onChange={(e) => onPageSizeChange(Number(e.target.value))}
          >
            {pageSizeOptions.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </Select>
        </PageSizeLabel>
      )}
      <Info theme={theme}>{t('common.pagination.range', { from, to, total })}</Info>
      <SecondaryButton
        theme={theme}
        type="button"
        disabled={disabled || offset === 0}
        onClick={() => onChange(Math.max(0, offset - limit))}
      >
        {t('common.pagination.prev')}
      </SecondaryButton>
      <SecondaryButton
        theme={theme}
        type="button"
        disabled={disabled || offset + limit >= total}
        onClick={() => onChange(offset + limit)}
      >
        {t('common.pagination.next')}
      </SecondaryButton>
    </Bar>
  );
};
