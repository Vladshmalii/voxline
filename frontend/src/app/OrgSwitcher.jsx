import { useState, useRef, useEffect } from 'react';
import styled from 'styled-components';
import { HiCheck, HiChevronDown } from 'react-icons/hi2';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { useUser } from 'contexts/UserContext';
import { fetchOrganizations, changeOrganization } from 'utils/authApi';

const Container = styled.div`
  position: relative;
`;

// Single- and multi-org share this box so both variants look identical; only
// the chevron on the right marks the switchable one.
const Trigger = styled.button`
  display: flex;
  align-items: center;
  gap: 6px;
  max-width: 220px;
  height: 32px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid ${({ theme }) => theme.colors.border};
  background-color: ${({ theme }) => theme.colors.surface};
  color: ${({ theme }) => theme.colors.primary};
  font-size: 13px;
  font-weight: 600;
  cursor: ${({ $interactive }) => ($interactive ? 'pointer' : 'default')};
  transition: border-color 0.2s ease;

  &:hover {
    border-color: ${({ $interactive, theme }) =>
      $interactive ? theme.colors.primary : theme.colors.border};
  }

  span {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  svg {
    flex-shrink: 0;
    color: ${({ theme }) => theme.colors.secondary};
  }
`;

const DropdownMenu = styled.div`
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  min-width: 240px;
  background-color: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 12px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  padding: 8px;
  z-index: 1000;
`;

const SectionLabel = styled.div`
  padding: 6px 12px 4px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: ${({ theme }) => theme.colors.muted};
`;

const OrgList = styled.div`
  max-height: 260px;
  overflow-y: auto;
`;

const OrgButton = styled.button`
  width: 100%;
  padding: 8px 12px;
  border-radius: 8px;
  border: none;
  background-color: transparent;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: ${({ theme }) => theme.colors.primary};
  cursor: ${({ $current, disabled }) => ($current || disabled ? 'default' : 'pointer')};
  font-size: 13px;
  text-align: left;
  transition: background-color 0.15s ease;
  opacity: ${({ disabled, $current }) => (disabled && !$current ? 0.6 : 1)};

  &:hover {
    background-color: ${({ $current, disabled, theme }) =>
      $current || disabled ? 'transparent' : theme.colors.hover};
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
  padding: 4px 12px 8px;
  font-size: 12px;
  color: ${({ $error, theme }) => ($error ? '#ef4444' : theme.colors.secondary)};
`;

export const OrgSwitcher = () => {
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
        onClick={multi ? () => setOpen((v) => !v) : undefined}
        title={currentName}
      >
        <span>{currentName}</span>
        {multi && <HiChevronDown size={14} />}
      </Trigger>
      {multi && open && (
        <DropdownMenu theme={theme}>
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
