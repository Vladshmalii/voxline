import { lazy } from 'react';
import {
  FiUsers,
  FiPhoneCall,
  FiMic,
  FiCpu,
  FiServer,
  FiPhone,
  FiMessageSquare,
  FiSend,
  FiTarget,
  FiBarChart2,
  FiDollarSign,
  FiShield,
  FiCheckSquare,
  FiUserCheck,
} from 'react-icons/fi';

// Pages stay code-split so heavy pages load on demand.
const DashboardPage = lazy(() =>
  import('pages/DashboardPage').then((m) => ({ default: m.DashboardPage }))
);
const AgentsPage = lazy(() => import('pages/AgentsPage').then((m) => ({ default: m.AgentsPage })));
const CallsPage = lazy(() => import('pages/CallsPage').then((m) => ({ default: m.CallsPage })));
const CampaignsPage = lazy(() =>
  import('pages/CampaignsPage').then((m) => ({ default: m.CampaignsPage }))
);
const AudiencesPage = lazy(() =>
  import('pages/AudiencesPage').then((m) => ({ default: m.AudiencesPage }))
);
const ModelsPage = lazy(() => import('pages/ModelsPage').then((m) => ({ default: m.ModelsPage })));
const ProvidersPage = lazy(() =>
  import('pages/ProvidersPage').then((m) => ({ default: m.ProvidersPage }))
);
const TelephonyPage = lazy(() =>
  import('pages/TelephonyPage').then((m) => ({ default: m.TelephonyPage }))
);
const MessagingPage = lazy(() =>
  import('pages/MessagingPage').then((m) => ({ default: m.MessagingPage }))
);
const SmsPage = lazy(() => import('pages/SmsPage').then((m) => ({ default: m.SmsPage })));
const SmsStatsPage = lazy(() => import('pages/SmsStatsPage').then((m) => ({ default: m.SmsStatsPage })));
const SmsModerationPage = lazy(() =>
  import('pages/SmsModerationPage').then((m) => ({ default: m.SmsModerationPage }))
);
const BillingPage = lazy(() => import('pages/BillingPage').then((m) => ({ default: m.BillingPage })));
const UsersPage = lazy(() => import('pages/UsersPage').then((m) => ({ default: m.UsersPage })));
const AdminStatsPage = lazy(() =>
  import('pages/AdminStatsPage').then((m) => ({ default: m.AdminStatsPage }))
);

// Flat routes and grouped sidebar share the same permission/resource metadata.
export const NAV_ITEMS = [
  { key: 'callStats', path: '/calls/stats', icon: FiBarChart2, Page: DashboardPage, resource: 'dashboard', group: 'calls' },
  { key: 'callBilling', path: '/calls/billing', icon: FiDollarSign, Page: BillingPage, resource: 'billing', group: 'calls', props: { channel: 'calls' } },
  { key: 'callList', path: '/calls', icon: FiPhoneCall, Page: CallsPage, resource: 'calls', group: 'calls', exact: true },
  { key: 'agents', path: '/agents', icon: FiMic, Page: AgentsPage, group: 'calls' },
  { key: 'audiences', path: '/audiences', icon: FiUsers, Page: AudiencesPage, group: 'calls' },
  { key: 'smsStats', path: '/messages/stats', icon: FiBarChart2, Page: SmsStatsPage, resource: 'sms', group: 'messages' },
  { key: 'smsBilling', path: '/messages/billing', icon: FiDollarSign, Page: BillingPage, resource: 'billing', group: 'messages', props: { channel: 'sms' } },
  { key: 'smsList', path: '/messages', icon: FiSend, Page: SmsPage, resource: 'sms', group: 'messages', exact: true },
  // VOAD-62: owner/admin/super_admin only — see VIEW_ROLES.smsModeration.
  { key: 'smsModeration', path: '/sms-moderation', icon: FiCheckSquare, Page: SmsModerationPage, resource: 'smsModeration', group: 'messages' },
  { key: 'adminStats', path: '/admin-stats', icon: FiShield, Page: AdminStatsPage },
  // Admin-only (canManageUsers): `users` is never in VIEW_ROLES, so only
  // admin/super_admin pass canView.
  { key: 'users', path: '/users', icon: FiUserCheck, Page: UsersPage },
  { key: 'campaigns', path: '/campaigns', icon: FiTarget, Page: CampaignsPage },
  { key: 'models', path: '/models', icon: FiCpu, Page: ModelsPage },
  { key: 'providers', path: '/providers', icon: FiServer, Page: ProvidersPage },
  { key: 'telephony', path: '/telephony', icon: FiPhone, Page: TelephonyPage },
  { key: 'messaging', path: '/messaging', icon: FiMessageSquare, Page: MessagingPage },
];

// Sidebar structure: sections with their pages. A section with a single page
// is rendered without a heading.
const byKey = (...keys) => keys.map((key) => NAV_ITEMS.find((item) => item.key === key));

export const NAV_SECTIONS = [
  { key: 'calls', children: NAV_ITEMS.filter((item) => item.group === 'calls') },
  { key: 'messages', children: NAV_ITEMS.filter((item) => item.group === 'messages') },
  { key: 'campaigns', children: byKey('campaigns') },
  { key: 'platform', children: byKey('models', 'providers', 'telephony', 'messaging') },
  { key: 'admin', children: byKey('adminStats', 'users') },
];
