import { useEffect, useState } from 'react';
import styled from 'styled-components';
import { useSearchParams } from 'react-router-dom';
import { HiCheck } from 'react-icons/hi2';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { LOCALE_NAMES } from 'i18n';
import { ToggleTheme } from 'app/ToggleTheme';
import { PrimaryButton, TextInput, FieldLabel, FieldGroup, FieldHint } from 'components/ui';
import { login, probeSession, fetchOrganizations, changeOrganization } from 'utils/authApi';
import { safeNextPath } from 'utils/authSession';

const Page = styled.div`
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background-color: ${({ theme }) => theme.colors.background};
  padding: 40px 20px;
  position: relative;
`;

const TopRight = styled.div`
  position: absolute;
  top: 20px;
  right: 20px;
  display: flex;
  align-items: center;
  gap: 12px;
`;

const LangSwitch = styled.div`
  display: flex;
  gap: 2px;
  padding: 2px;
  background-color: ${({ theme }) => theme.colors.surface};
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
`;

const Brand = styled.div`
  font-size: 22px;
  font-weight: 800;
  letter-spacing: 0.02em;
  color: ${({ theme }) => theme.colors.primary};
  margin-bottom: 24px;

  span {
    color: ${({ theme }) => theme.colors.accentNeon};
  }
`;

const Card = styled.form`
  width: 100%;
  max-width: 400px;
  padding: 28px;
  background-color: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  box-sizing: border-box;
`;

const Title = styled.h1`
  font-size: 22px;
  font-weight: 700;
  color: ${({ theme }) => theme.colors.primary};
  margin: 0 0 8px;
`;

const Subtitle = styled.p`
  font-size: 14px;
  color: ${({ theme }) => theme.colors.secondary};
  margin: 0 0 22px;
`;

const OrgButton = styled.button`
  width: 100%;
  padding: 10px 12px;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 14px;
  text-align: left;
  color: ${({ theme }) => theme.colors.primary};
  background-color: ${({ theme }) => theme.colors.background};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s ease, background-color 0.15s ease;

  &:hover:not(:disabled) {
    border-color: ${({ theme }) => theme.colors.accentNeon};
    background-color: ${({ theme }) => theme.colors.hover};
  }

  &:disabled {
    opacity: 0.6;
    cursor: default;
  }

  small {
    color: ${({ theme }) => theme.colors.secondary};
    font-size: 12px;
  }
`;

const FullButton = styled(PrimaryButton)`
  width: 100%;
  justify-content: center;
  margin-top: 6px;
`;

export const LoginPage = () => {
  const { theme } = useTheme();
  const { t, locale, setLocale, locales } = useI18n();
  const [params] = useSearchParams();
  const next = safeNextPath(params.get('next'));

  const [checking, setChecking] = useState(true);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  // Set after a successful login when the account has several organizations.
  const [orgs, setOrgs] = useState(null);
  const [currentOrg, setCurrentOrg] = useState(null);

  // Full load (not SPA navigation) so the app shell starts with fresh state.
  const proceed = () => window.location.assign(next);

  // Already signed in: skip the form.
  useEffect(() => {
    let active = true;
    probeSession().then((me) => {
      if (!active) return;
      if (me) window.location.assign(next);
      else setChecking(false);
    });
    return () => {
      active = false;
    };
  }, [next]);

  const onSubmit = async (e) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const session = await login({ email: email.trim(), password });
      let list = [];
      try {
        const data = await fetchOrganizations();
        list = Array.isArray(data) ? data : [];
      } catch (_) {
        list = [];
      }
      if (list.length > 1) {
        setCurrentOrg(session?.organization?.uuid ?? null);
        setOrgs(list);
        setBusy(false);
        return;
      }
      proceed();
    } catch (err) {
      setError(
        err.message === 'invalid_credentials' ? t('auth.invalidCredentials') : err.message || t('auth.failed')
      );
      setBusy(false);
    }
  };

  const pickOrg = async (org) => {
    if (busy) return;
    if (org.uuid === currentOrg) {
      proceed();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await changeOrganization(org.uuid);
      proceed();
    } catch (err) {
      setError(err.message || t('auth.orgFailed'));
      setBusy(false);
    }
  };

  return (
    <Page theme={theme}>
      <TopRight>
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
        <ToggleTheme />
      </TopRight>
      <Brand theme={theme}>
        <span>V</span>OXLIN<span>E</span>
      </Brand>
      {checking ? (
        <Subtitle theme={theme}>{t('auth.checking')}</Subtitle>
      ) : orgs ? (
        <Card as="div" theme={theme}>
          <Title theme={theme}>{t('auth.orgTitle')}</Title>
          <Subtitle theme={theme}>{t('auth.orgSubtitle')}</Subtitle>
          {orgs.map((org) => (
            <OrgButton
              key={org.uuid}
              theme={theme}
              type="button"
              disabled={busy}
              onClick={() => pickOrg(org)}
            >
              <span>{org.name}</span>
              {org.uuid === currentOrg && (
                <small>
                  <HiCheck size={13} /> {t('auth.orgCurrent')}
                </small>
              )}
            </OrgButton>
          ))}
          {error && (
            <FieldHint theme={theme} $error>
              {error}
            </FieldHint>
          )}
        </Card>
      ) : (
        <Card theme={theme} onSubmit={onSubmit}>
          <Title theme={theme}>{t('auth.title')}</Title>
          <Subtitle theme={theme}>{t('auth.subtitle')}</Subtitle>
          <FieldGroup>
            <FieldLabel theme={theme} htmlFor="login-email">
              {t('auth.email')}
            </FieldLabel>
            <TextInput
              id="login-email"
              theme={theme}
              type="email"
              autoComplete="username"
              autoFocus
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </FieldGroup>
          <FieldGroup>
            <FieldLabel theme={theme} htmlFor="login-password">
              {t('auth.password')}
            </FieldLabel>
            <TextInput
              id="login-password"
              theme={theme}
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </FieldGroup>
          {error && (
            <FieldHint theme={theme} $error>
              {error}
            </FieldHint>
          )}
          <FullButton theme={theme} type="submit" disabled={busy}>
            {busy ? t('auth.signingIn') : t('auth.signIn')}
          </FullButton>
        </Card>
      )}
    </Page>
  );
};
