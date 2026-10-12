import { useI18n } from 'contexts/I18nContext';
import { Badge } from 'components/ui';
import { KINDS, getStatusMeta, statusLabel } from 'utils/statusMap';

export const ActiveBadge = ({ active }) => {
  const { t } = useI18n();
  return (
    <Badge $color={active ? '#16a34a' : '#6b7280'}>
      {t(active ? 'common.active' : 'common.inactive')}
    </Badge>
  );
};

const ICON_STYLE = { verticalAlign: '-2px', marginRight: 5 };

/**
 * Badge for any status-like enum value (attempt status, call lifecycle,
 * outcome, sentiment, SMS status, client status). Looks everything up in
 * utils/statusMap.js. Pass `kind` (KINDS.*) whenever the value is ambiguous;
 * without it the call/attempt/outcome/... kinds are tried in that order.
 */
export const StatusBadge = ({ value, kind, icon = true }) => {
  const { t } = useI18n();
  if (!value) return '—';
  const meta = getStatusMeta(value, kind);
  const Icon = meta.icon;
  return (
    <Badge $color={meta.color}>
      {icon && Icon && <Icon size={11} style={ICON_STYLE} aria-hidden="true" />}
      {statusLabel(t, value, kind)}
    </Badge>
  );
};

// CampaignStatusEnum shares the raw value `completed` with the call kinds, so
// it keeps its own badge and always looks up under KINDS.CAMPAIGN.
export const CampaignStatusBadge = ({ value }) => <StatusBadge value={value} kind={KINDS.CAMPAIGN} />;
