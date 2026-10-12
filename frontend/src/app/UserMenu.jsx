import { useState, useRef, useEffect } from 'react';
import styled from 'styled-components';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { LOCALE_NAMES } from 'i18n';
import { useUser } from 'contexts/UserContext';
import { ToggleTheme } from 'app/ToggleTheme';
import { logout } from 'utils/authApi';

const Container = styled.div`
  position: relative;
`;

const AvatarButton = styled.button`
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background-color: ${({ theme }) => theme.colors.accent};
  border: 2px solid ${({ theme }) => theme.colors.border};
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 15px;
  font-weight: 700;
  color: #fff;
  user-select: none;
  transition: border-color 0.2s ease;

  &:hover {
    border-color: ${({ theme }) => theme.colors.primary};
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

const UserInfo = styled.div`
  padding: 10px 12px 12px;
  border-bottom: 1px solid ${({ theme }) => theme.colors.border};
  margin-bottom: 6px;
`;

const UserEmail = styled.div`
  font-size: 13px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.primary};
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
`;

const Row = styled.div`
  padding: 8px 12px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: ${({ theme }) => theme.colors.primary};
  font-size: 14px;
`;

const LangSwitch = styled.div`
  display: flex;
  gap: 2px;
  padding: 2px;
  background-color: ${({ theme }) => theme.colors.background};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 8px;
`;

const LangButton = styled.button`
  padding: 4px 10px;
  font-size: 12px;
  font-weight: ${({ $active }) => ($active ? '700' : '500')};
  color: ${({ $active, theme }) => ($active ? '#fff' : theme.colors.secondary)};
  background-color: ${({ $active, theme }) => ($active ? theme.colors.accent : 'transparent')};
  border: none;
  border-radius: 6px;
  cursor: ${({ $active }) => ($active ? 'default' : 'pointer')};
  transition: background-color 0.15s ease, color 0.15s ease;

  &:hover {
    color: ${({ $active, theme }) => ($active ? '#fff' : theme.colors.primary)};
  }
`;

const LogoutButton = styled.button`
  width: 100%;
  padding: 10px 12px;
  border-radius: 8px;
  border: none;
  background-color: transparent;
  color: ${({ theme }) => theme.colors.secondary};
  cursor: pointer;
  font-size: 14px;
  text-align: left;
  transition: all 0.15s ease;
  margin-top: 2px;

  &:hover {
    background-color: rgba(239, 68, 68, 0.12);
    color: #ef4444;
  }
`;

export const UserMenu = () => {
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

  const avatarLetter = user?.email?.[0]?.toUpperCase() ?? '?';
  // Clear the session server-side, then do a full load of /login so no
  // per-user state survives in memory.
  const handleLogout = async () => {
    await logout();
    window.location.assign('/login');
  };

  return (
    <Container ref={ref}>
      <AvatarButton theme={theme} onClick={() => setOpen((v) => !v)}>
        {avatarLetter}
      </AvatarButton>
      {open && (
        <DropdownMenu theme={theme}>
          {user && (
            <UserInfo theme={theme}>
              <UserEmail theme={theme}>{user.email}</UserEmail>
            </UserInfo>
          )}
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
            {t('userMenu.signOut')}
          </LogoutButton>
        </DropdownMenu>
      )}
    </Container>
  );
};
