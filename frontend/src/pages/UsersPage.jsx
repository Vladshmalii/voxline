import { useState, useMemo, useCallback, useEffect } from 'react';
import styled from 'styled-components';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { useUser } from 'contexts/UserContext';
import { CrudPage } from 'components/CrudPage';
import { Modal } from 'components/Modal';
import { toast } from 'components/Toaster';
import { Badge, Select, SecondaryButton, PrimaryButton, EmptyStateText, RowActionButton, Segmented, SegmentOption } from 'components/ui';
import { adminApi } from 'utils/authApi';
import { ROLES, canManageUsers } from 'utils/permissions';

const ROLE_VALUES = [ROLES.ADMIN, ROLES.SUPER_ADMIN, ROLES.OWNER, ROLES.STAFF, ROLES.VIEWER, ROLES.NONE];

const Tabs = Segmented;
const Tab = SegmentOption;

const MembershipRow = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;

  > span {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: ${({ theme }) => theme.colors.primary};
    font-size: 14px;
  }

  select {
    width: auto;
  }
`;

const BadgeList = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
`;

// Membership editor: one row per organization the user belongs to (role changes
// apply immediately), plus an add row for the organizations they are not in.
const MembershipsModal = ({ user, orgs, onClose, onChanged }) => {
  const { theme } = useTheme();
  const { t } = useI18n();
  const [memberships, setMemberships] = useState(user.memberships || []);
  const [newOrg, setNewOrg] = useState('');
  const [newRole, setNewRole] = useState(ROLES.VIEWER);
  const [busy, setBusy] = useState(false);

  const orgName = (uuid) => orgs.find((o) => o.uuid === uuid)?.name || uuid;
  const available = orgs.filter((o) => !memberships.some((m) => m.organization_uuid === o.uuid));

  const run = async (fn, apply) => {
    setBusy(true);
    try {
      await fn();
      apply();
      onChanged();
    } catch (e) {
      toast(e.message || t('users.memberships.saveFailed'), 'error');
    } finally {
      setBusy(false);
    }
  };

  const changeRole = (uuid, role) =>
    run(
      () => adminApi.setMembership(uuid, user.id, role),
      () =>
        setMemberships((list) =>
          list.map((m) => (m.organization_uuid === uuid ? { ...m, role } : m))
        )
    );

  const remove = (uuid) =>
    run(
      () => adminApi.removeMembership(uuid, user.id),
      () => setMemberships((list) => list.filter((m) => m.organization_uuid !== uuid))
    );

  const add = () => {
    if (!newOrg) return;
    run(
      () => adminApi.setMembership(newOrg, user.id, newRole),
      () => {
        setMemberships((list) => [...list, { organization_uuid: newOrg, role: newRole }]);
        setNewOrg('');
      }
    );
  };

  const roleOptions = ROLE_VALUES.map((r) => (
    <option key={r} value={r}>
      {t(`users.roles.${r}`)}
    </option>
  ));

  return (
    <Modal
      title={`${t('users.memberships.title')} — ${user.email}`}
      onClose={onClose}
      footer={
        <SecondaryButton theme={theme} type="button" onClick={onClose}>
          {t('common.close')}
        </SecondaryButton>
      }
    >
      {memberships.length === 0 && (
        <EmptyStateText theme={theme}>{t('users.memberships.none')}</EmptyStateText>
      )}
      {memberships.map((m) => (
        <MembershipRow key={m.organization_uuid} theme={theme}>
          <span title={m.organization_uuid}>{orgName(m.organization_uuid)}</span>
          <Select
            theme={theme}
            value={m.role}
            disabled={busy}
            onChange={(e) => changeRole(m.organization_uuid, e.target.value)}
          >
            {roleOptions}
          </Select>
          <RowActionButton
            theme={theme}
            type="button"
            $danger
            disabled={busy}
            onClick={() => remove(m.organization_uuid)}
          >
            {t('users.memberships.remove')}
          </RowActionButton>
        </MembershipRow>
      ))}
      {available.length > 0 && (
        <MembershipRow theme={theme}>
          <Select theme={theme} value={newOrg} onChange={(e) => setNewOrg(e.target.value)}>
            <option value="">{t('users.memberships.pickOrg')}</option>
            {available.map((o) => (
              <option key={o.uuid} value={o.uuid}>
                {o.name}
              </option>
            ))}
          </Select>
          <Select theme={theme} value={newRole} onChange={(e) => setNewRole(e.target.value)}>
            {roleOptions}
          </Select>
          <PrimaryButton theme={theme} type="button" disabled={busy || !newOrg} onClick={add}>
            {t('users.memberships.add')}
          </PrimaryButton>
        </MembershipRow>
      )}
    </Modal>
  );
};

export const UsersPage = () => {
  const { theme } = useTheme();
  const { t } = useI18n();
  const me = useUser();
  const [tab, setTab] = useState('users');
  const [orgs, setOrgs] = useState([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [editing, setEditing] = useState(null); // user whose memberships are open

  const loadOrgs = useCallback(() => {
    adminApi
      .listOrganizations()
      .then((data) => setOrgs(Array.isArray(data) ? data : []))
      .catch((e) => toast(e.message, 'error'));
  }, []);

  useEffect(() => {
    loadOrgs();
  }, [loadOrgs]);

  const roleLabel = useCallback((role) => t(`users.roles.${role}`), [t]);

  const tabs = (
    <Tabs theme={theme}>
      {['users', 'organizations'].map((key) => (
        <Tab key={key} theme={theme} type="button" $active={tab === key} onClick={() => setTab(key)}>
          {t(`users.tabs.${key}`)}
        </Tab>
      ))}
    </Tabs>
  );

  const userApi = useMemo(
    () => ({
      list: () => adminApi.listUsers(),
      // POST /admin/users, then the optional first membership.
      create: async (payload) => {
        const { organization_uuid: orgUuid, role, ...userFields } = payload;
        const created = await adminApi.createUser(userFields);
        if (orgUuid) await adminApi.setMembership(orgUuid, created.id, role || ROLES.VIEWER);
        setRefreshKey((k) => k + 1);
        return created;
      },
      update: (id, payload) => adminApi.updateUser(id, payload),
    }),
    []
  );

  const orgApi = useMemo(
    () => ({
      list: () => adminApi.listOrganizations().then((rows) => rows.map((o) => ({ ...o, id: o.uuid }))),
      create: async (payload) => {
        const created = await adminApi.createOrganization(payload);
        loadOrgs();
        return created;
      },
    }),
    [loadOrgs]
  );

  const orgOptions = useMemo(() => orgs.map((o) => ({ value: o.uuid, label: o.name })), [orgs]);
  const roleOptions = useMemo(
    () => ROLE_VALUES.map((r) => ({ value: r, label: roleLabel(r) })),
    [roleLabel]
  );

  const userColumns = useMemo(
    () => [
      { key: 'id', labelKey: 'common.id' },
      { key: 'email', labelKey: 'users.columns.email' },
      { key: 'name', labelKey: 'users.columns.name' },
      {
        key: 'is_active',
        labelKey: 'users.columns.status',
        render: (row) => (
          <Badge $color={row.is_active ? '#16A34A' : '#64748B'}>
            {row.is_active ? t('common.active') : t('common.inactive')}
          </Badge>
        ),
      },
      {
        key: 'is_superuser',
        labelKey: 'users.columns.superuser',
        align: 'center',
        render: (row) => (row.is_superuser ? t('common.yes') : '—'),
      },
      {
        key: 'memberships',
        labelKey: 'users.columns.memberships',
        render: (row) =>
          (row.memberships || []).length === 0 ? (
            '—'
          ) : (
            <BadgeList>
              {row.memberships.map((m) => (
                <Badge key={m.organization_uuid} $color="#0891B2">
                  {orgs.find((o) => o.uuid === m.organization_uuid)?.name || m.organization_uuid}
                  {': '}
                  {roleLabel(m.role)}
                </Badge>
              ))}
            </BadgeList>
          ),
      },
    ],
    [orgs, t, roleLabel]
  );

  const userFields = useMemo(
    () => [
      { name: 'email', labelKey: 'users.fields.email', type: 'text', required: true, createOnly: true },
      { name: 'name', labelKey: 'users.fields.name', type: 'text', required: true },
      {
        name: 'password',
        labelKey: 'users.fields.password',
        type: 'password',
        hintKey: 'users.fields.passwordHint',
      },
      { name: 'is_active', labelKey: 'users.fields.isActive', type: 'checkbox', default: true },
      { name: 'is_superuser', labelKey: 'users.fields.isSuperuser', type: 'checkbox', default: false },
      {
        name: 'organization_uuid',
        labelKey: 'users.fields.organization',
        hintKey: 'users.fields.organizationHint',
        type: 'select',
        options: orgOptions,
        createOnly: true,
      },
      {
        name: 'role',
        labelKey: 'users.fields.role',
        type: 'select',
        options: roleOptions,
        default: ROLES.VIEWER,
        createOnly: true,
      },
    ],
    [orgOptions, roleOptions]
  );

  const orgColumns = useMemo(
    () => [
      { key: 'name', labelKey: 'users.columns.orgName' },
      { key: 'uuid', labelKey: 'users.columns.uuid' },
    ],
    []
  );

  const orgFields = useMemo(
    () => [{ name: 'name', labelKey: 'users.fields.orgName', type: 'text', required: true }],
    []
  );

  // Defense in depth: the nav item is already hidden for other roles.
  if (!canManageUsers(me?.role)) return null;

  return (
    <>
      {tab === 'users' ? (
        <CrudPage
          key="users"
          titleKey="users.title"
          api={userApi}
          columns={userColumns}
          fields={userFields}
          refreshKey={refreshKey}
          onRowClick={setEditing}
          headerExtra={tabs}
          emptyTextKey="users.empty"
        />
      ) : (
        <CrudPage
          key="orgs"
          titleKey="users.title"
          api={orgApi}
          columns={orgColumns}
          fields={orgFields}
          headerExtra={tabs}
          emptyTextKey="users.emptyOrgs"
        />
      )}
      {editing && (
        <MembershipsModal
          user={editing}
          orgs={orgs}
          onClose={() => setEditing(null)}
          onChanged={() => setRefreshKey((k) => k + 1)}
        />
      )}
    </>
  );
};
