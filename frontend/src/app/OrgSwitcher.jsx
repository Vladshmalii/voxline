import { useState, useRef, useEffect } from 'react';
import styled from 'styled-components';
import { HiCheck, HiChevronUpDown } from 'react-icons/hi2';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { useUser } from 'contexts/UserContext';
import { fetchOrganizations, changeOrganization } from 'utils/authApi';

const Container = styled.div`
  position: relative;
`;

// Workspace button at the top of the sidebar. Single- and multi-org share the
// same box; only the chevron marks the switchable one.
const Trigger = styled.button`
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 46px;
  padding: ${({ $collapsed }) => ($collapsed ? '0' : '6px 10px 6px 8px')};
  justify-content: ${({ $collapsed }) => ($collapsed ? 'center' : 'flex-start')};
  border-radius: ${({ theme }) => theme.radii.sm};
  border: 1px solid ${({ $collapsed, theme }) => ($collapsed ? 'transparent' : theme.colors.border)};
  background-color: ${({ $collapsed, theme }) => ($collapsed ? 'transparent' : theme.colors.surface)};
  box-shadow: ${({ $collapsed, theme }) => ($collapsed ? 'none' : theme.shadows.card)};
  color: ${({ theme }) => theme.colors.primary};
  text-align: left;
  cursor: ${({ $interactive }) => ($interactive ? 'pointer' : 'default')};
  transition: background-color 0.12s ease, border-color 0.12s ease;

  &:hover {
    background-color: ${({ $interactive, $collapsed, theme }) =>
      $interactive ? theme.colors.hover : $collapsed ? 'transparent' : theme.colors.surface};
  }
`;

const Avatar = styled.span`
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: ${({ theme }) => theme.radii.xs};
  background: ${({ theme }) => theme.colors.accentSoft};
  color: ${({ theme }) => (theme.mode === 'dark' ? theme.colors.accentNeon : theme.colors.accent)};
  font-size: 13px;
  font-weight: 700;
`;

const Names = styled.span`
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
  line-height: 1.25;

  strong {
    font-size: 13.5px;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  small {
    font-size: 11.5px;
    color: ${({ theme }) => theme.colors.muted};
  }
`;

const Chevrons = styled(HiChevronUpDown)`
  flex-shrink: 0;
  color: ${({ theme }) => theme.colors.muted};
`;

const DropdownMenu = styled.div`
  position: absolute;
  z-index: 1100;
  top: ${({ $collapsed }) => ($collapsed ? '0' : 'calc(100% + 6px)')};
  left: ${({ $collapsed }) => ($collapsed ? 'calc(100% + 8px)' : '0')};
  min-width: ${({ $collapsed }) => ($collapsed ? '240px' : '100%')};
  background-color: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.md};
  box-shadow: ${({ theme }) => theme.shadows.pop};
  padding: 6px;
`;

const SectionLabel = styled.div`
  padding: 8px 10px 6px;
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: ${({ theme }) => theme.colors.muted};
`;

const OrgList = styled.div`
  max-height: 260px;
  overflow-y: auto;
`;

const OrgButton = styled.button`
  width: 100%;
  padding: 8px 10px;
  border-radius: ${({ theme }) => theme.radii.xs};
  border: none;
  background-color: ${({ $current, theme }) => ($current ? theme.colors.accentSoft : 'transparent')};
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: ${({ theme }) => theme.colors.primary};
  cursor: ${({ $current, disabled }) => ($current || disabled ? 'default' : 'pointer')};
  font-size: 13.5px;
  font-weight: ${({ $current }) => ($current ? 600 : 450)};
  text-align: left;
  opacity: ${({ disabled, $current }) => (disabled && !$current ? 0.6 : 1)};

  &:hover {
    background-color: ${({ $current, disabled, theme }) =>
      $current ? theme.colors.accentSoft : disabled ? 'transparent' : theme.colors.hover};
  }

  span {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  svg {
    flex-shrink: 0;
    color: ${({ theme }) => theme.colors.accent};
  }
`;

const OrgStatus = styled.div`
  padding: 6px 10px 8px;
  font-size: 12px;
  color: ${({ $error, theme }) => ($error ? theme.colors.danger : theme.colors.secondary)};
`;

export const OrgSwitcher = ({ collapsed = false }) => {
  const { theme } = useTheme();
  const { t } = useI18n();
  const user = useUser();
  const [open, setOpen] = useState(false);
  const [orgs, setOrgs] = useState(null);
  const [switchingUuid, setSwitchingUuid] = useState(null);
  const [orgError, setOrgError] = useState(null);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [open]);

  // Loaded up front: the count decides whether this renders as a drop list or
  // as a plain name.
  useEffect(() => {
    let active = true;
    fetchOrganizations()
      .then((data) => {
        if (active) setOrgs(Array.isArray(data) ? data : []);
      })
      .catch(() => {
        if (active) setOrgs([]);
      });
    return () => {
      active = false;
    };
  }, []);

  const currentOrgUuid = user?.organization?.uuid;
  const currentName =
    user?.organization?.name ??
    orgs?.find((org) => org.uuid === currentOrgUuid)?.name;

  const handleChangeOrg = async (org) => {
    if (switchingUuid || org.uuid === currentOrgUuid) return;
    setOrgError(null);
    setSwitchingUuid(org.uuid);
    try {
      await changeOrganization(org.uuid);
      // The new organization's tokens are already in cookies, so the app
      // just reloads and starts up in its context.
      window.location.reload();
    } catch (e) {
      setOrgError(t('userMenu.changeOrgError'));
      setSwitchingUuid(null);
    }
  };

  if (!currentName) return null;

  const multi = Array.isArray(orgs) && orgs.length > 1;

  return (
    <Container ref={ref}>
      <Trigger
        theme={theme}
        type="button"
        $interactive={multi}
        $collapsed={collapsed}
        onClick={multi ? () => setOpen((v) => !v) : undefined}
        title={currentName}
      >
        <Avatar theme={theme}>{currentName.trim()[0]?.toUpperCase()}</Avatar>
        {!collapsed && (
          <Names theme={theme}>
            <strong>{currentName}</strong>
            <small>{t('userMenu.organization')}</small>
          </Names>
        )}
        {!collapsed && multi && <Chevrons theme={theme} size={16} />}
      </Trigger>
      {multi && open && (
        <DropdownMenu theme={theme} $collapsed={collapsed}>
          <SectionLabel theme={theme}>{t('userMenu.organization')}</SectionLabel>
          <OrgList>
            {orgs.map((org) => {
              const isCurrent = org.uuid === currentOrgUuid;
              return (
                <OrgButton
                  key={org.uuid}
                  theme={theme}
                  $current={isCurrent}
                  disabled={Boolean(switchingUuid)}
                  onClick={() => handleChangeOrg(org)}
                >
                  <span>{org.name}</span>
                  {isCurrent && <HiCheck size={15} />}
                  {switchingUuid === org.uuid && <span>…</span>}
                </OrgButton>
              );
            })}
          </OrgList>
          {orgError && (
            <OrgStatus theme={theme} $error>
              {orgError}
            </OrgStatus>
          )}
        </DropdownMenu>
      )}
    </Container>
  );
};
