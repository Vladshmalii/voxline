import { useState, useRef, useEffect } from 'react';
import styled from 'styled-components';
import { FiLogOut } from 'react-icons/fi';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { LOCALE_NAMES } from 'i18n';
import { useUser } from 'contexts/UserContext';
import { ToggleTheme } from 'app/ToggleTheme';
import { logout } from 'utils/authApi';

const Container = styled.div`
  position: relative;
`;

const Trigger = styled.button`
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: ${({ $collapsed }) => ($collapsed ? '0' : '6px 8px')};
  justify-content: ${({ $collapsed }) => ($collapsed ? 'center' : 'flex-start')};
  min-height: 46px;
  border: none;
  border-radius: ${({ theme }) => theme.radii.sm};
  background: transparent;
  color: ${({ theme }) => theme.colors.primary};
  text-align: left;
  transition: background-color 0.12s ease;

  &:hover {
    background: ${({ theme }) => theme.colors.hover};
  }
`;

const Avatar = styled.span`
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, #4f8bff, #1d4ed8);
  color: #ffffff;
  font-size: 13px;
  font-weight: 650;
  user-select: none;
`;

const Who = styled.span`
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
  line-height: 1.25;

  strong {
    font-size: 13px;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  small {
    font-size: 11.5px;
    color: ${({ theme }) => theme.colors.muted};
    text-transform: capitalize;
  }
`;

const DropdownMenu = styled.div`
  position: absolute;
  z-index: 1100;
  bottom: ${({ $collapsed }) => ($collapsed ? '0' : 'calc(100% + 8px)')};
  left: ${({ $collapsed }) => ($collapsed ? 'calc(100% + 8px)' : '0')};
  min-width: ${({ $collapsed }) => ($collapsed ? '260px' : '100%')};
  background-color: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.md};
  box-shadow: ${({ theme }) => theme.shadows.pop};
  padding: 6px;
`;

const UserEmail = styled.div`
  padding: 8px 10px 10px;
  margin-bottom: 4px;
  border-bottom: 1px solid ${({ theme }) => theme.colors.divider};
  font-size: 12.5px;
  color: ${({ theme }) => theme.colors.secondary};
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
`;

const Row = styled.div`
  padding: 6px 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: ${({ theme }) => theme.colors.primary};
  font-size: 13.5px;
`;

const LangSwitch = styled.div`
  display: inline-flex;
  padding: 3px;
  gap: 2px;
  background: ${({ theme }) => theme.colors.surfaceAlt};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.sm};
`;

const LangButton = styled.button`
  height: 26px;
  padding: 0 10px;
  font-size: 12px;
  font-weight: 600;
  color: ${({ $active, theme }) => ($active ? theme.colors.primary : theme.colors.muted)};
  background-color: ${({ $active, theme }) => ($active ? theme.colors.raised : 'transparent')};
  box-shadow: ${({ $active, theme }) => ($active ? theme.shadows.lift : 'none')};
  border: none;
  border-radius: ${({ theme }) => theme.radii.xs};
  cursor: ${({ $active }) => ($active ? 'default' : 'pointer')};

  &:hover {
    color: ${({ theme }) => theme.colors.primary};
  }
`;

const LogoutButton = styled.button`
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 4px;
  padding: 9px 10px;
  border-radius: ${({ theme }) => theme.radii.xs};
  border: none;
  background-color: transparent;
  color: ${({ theme }) => theme.colors.danger};
  font-size: 13.5px;
  font-weight: 500;
  text-align: left;

  &:hover {
    background-color: ${({ theme }) => theme.colors.danger}14;
  }
`;

export const UserMenu = ({ collapsed = false }) => {
  const { theme } = useTheme();
  const { t, locale, setLocale, locales } = useI18n();
  const user = useUser();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [open]);

  const avatarLetter = (user?.name || user?.email)?.[0]?.toUpperCase() ?? '?';
  // Clear the session server-side, then do a full load of /login so no
  // per-user state survives in memory.
  const handleLogout = async () => {
    await logout();
    window.location.assign('/login');
  };

  return (
    <Container ref={ref}>
      <Trigger
        theme={theme}
        type="button"
        $collapsed={collapsed}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title={collapsed ? user?.email : undefined}
      >
        <Avatar theme={theme}>{avatarLetter}</Avatar>
        {!collapsed && (
          <Who theme={theme}>
            <strong>{user?.name || user?.email}</strong>
            <small>{String(user?.role || '').replace(/_/g, ' ')}</small>
          </Who>
        )}
      </Trigger>
      {open && (
        <DropdownMenu theme={theme} $collapsed={collapsed}>
          {user && <UserEmail theme={theme}>{user.email}</UserEmail>}
          <Row theme={theme}>
            <span>{t('userMenu.language')}</span>
            <LangSwitch theme={theme}>
              {locales.map((code) => (
                <LangButton
                  key={code}
                  theme={theme}
                  type="button"
                  $active={code === locale}
                  onClick={() => setLocale(code)}
                  title={LOCALE_NAMES[code]}
                >
                  {code.toUpperCase()}
                </LangButton>
              ))}
            </LangSwitch>
          </Row>
          <Row theme={theme}>
            <span>{t('userMenu.theme')}</span>
            <ToggleTheme />
          </Row>
          <LogoutButton theme={theme} onClick={handleLogout}>
            <FiLogOut size={15} />
            {t('userMenu.signOut')}
          </LogoutButton>
        </DropdownMenu>
      )}
    </Container>
  );
};
