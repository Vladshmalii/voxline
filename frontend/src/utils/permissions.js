// Role-based UI gating. Mirrors the access matrix enforced by the call
// backend (src/controller/dependencies/permission.py) — this file is
// UI-only defense in depth; the backend is authoritative on every request.

export const ROLES = {
  ADMIN: 'admin',
  SUPER_ADMIN: 'super_admin',
  OWNER: 'owner',
  STAFF: 'staff',
  VIEWER: 'viewer',
  NONE: 'none',
};

const FULL_ACCESS = new Set([ROLES.ADMIN, ROLES.SUPER_ADMIN]);

export const hasFullAccess = (role) => FULL_ACCESS.has(role);

// Resources with no entry (or an empty set) below get no view access beyond
// admin/super_admin — telephony, messaging, adminStats and users are never listed.
const VIEW_ROLES = {
  dashboard: new Set([ROLES.OWNER, ROLES.STAFF, ROLES.VIEWER]),
  calls: new Set([ROLES.OWNER, ROLES.STAFF, ROLES.VIEWER]),
  campaigns: new Set([ROLES.OWNER, ROLES.STAFF, ROLES.VIEWER]),
  audiences: new Set([ROLES.OWNER, ROLES.STAFF, ROLES.VIEWER]),
  agents: new Set([ROLES.OWNER, ROLES.STAFF, ROLES.VIEWER]),
  models: new Set(),
  sms: new Set([ROLES.OWNER, ROLES.STAFF, ROLES.VIEWER]),
  billing: new Set([ROLES.OWNER, ROLES.STAFF, ROLES.VIEWER]),
  providers: new Set(),
  // VOAD-62: the SMS-moderation queue is for moderators only — staff whose
  // own text ends up in it don't get a view of everyone else's.
  smsModeration: new Set([ROLES.OWNER]),
};

// WRITE implies VIEW; only resources with a write action need an entry.
const WRITE_ROLES = {
  calls: new Set([ROLES.OWNER, ROLES.STAFF]),
  campaigns: new Set([ROLES.OWNER, ROLES.STAFF]),
  audiences: new Set([ROLES.OWNER, ROLES.STAFF]),
  agents: new Set([ROLES.OWNER, ROLES.STAFF]), // create/edit only — delete stays owner-only (VOAD-57)
  sms: new Set([ROLES.OWNER, ROLES.STAFF]),
  billing: new Set([ROLES.OWNER]),
  providers: new Set(),
  // models: nobody but admin/super_admin — left empty.
};

export const canView = (resource, role) =>
  hasFullAccess(role) || (VIEW_ROLES[resource]?.has(role) ?? false);

// Per-minute clients (`billing_enabled: false` from GET /me) have no billing
// section — the backend closes it for them too; this keeps the menu and direct
// links in step. Everything except billing is exactly canView.
export const canViewFor = (resource, user) =>
  canView(resource, user?.role) &&
  !(resource === 'billing' && user?.billing_enabled === false && !hasFullAccess(user?.role));

export const canWrite = (resource, role) =>
  hasFullAccess(role) || (WRITE_ROLES[resource]?.has(role) ?? false);

// Agents: voice preview sits between view and write — staff keeps it, viewer
// doesn't, and it isn't gated by the agent-write (owner-only) tier at all.
export const canPreviewVoice = (role) =>
  hasFullAccess(role) || role === ROLES.OWNER || role === ROLES.STAFF;

export const canManageAgents = (role) => canWrite('agents', role);
// Delete is narrower than the rest of agent write access (VOAD-57): owner+ only.
export const canDeleteAgents = (role) => hasFullAccess(role) || role === ROLES.OWNER;
export const canAssignModels = hasFullAccess;
// Users & Organizations admin page (backend /admin/*: admin / super_admin only).
export const canManageUsers = hasFullAccess;
export const canManageModels = (role) => canWrite('models', role);
export const canManageBilling = (role) => canWrite('billing', role);
// Tariffs are internal: a client never sets (or sees the SMS rate of) its own.
export const canManageTariffs = hasFullAccess;
export const canSendSms = (role) => canWrite('sms', role);
