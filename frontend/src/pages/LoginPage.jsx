import { useEffect, useState } from 'react';
import styled from 'styled-components';
import { useSearchParams } from 'react-router-dom';
import { HiCheck } from 'react-icons/hi2';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { LOCALE_NAMES } from 'i18n';
import { ToggleTheme } from 'app/ToggleTheme';
import { Logo } from 'app/Logo';
import { PrimaryButton, TextInput, FieldLabel, FieldGroup, FieldHint } from 'components/ui';
import { login, probeSession, fetchOrganizations, changeOrganization } from 'utils/authApi';
import { safeNextPath } from 'utils/authSession';

const Page = styled.div`
  position: relative;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 72px 20px 40px;
  overflow: hidden;
  background-color: ${({ theme }) => theme.colors.background};
  background-image: radial-gradient(
      60% 50% at 50% 0%,
      ${({ theme }) => theme.colors.accentNeon}${({ theme }) => (theme.mode === 'dark' ? '26' : '22')} 0%,
      transparent 70%
    ),
    linear-gradient(${({ theme }) => theme.colors.border}66 1px, transparent 1px),
    linear-gradient(90deg, ${({ theme }) => theme.colors.border}66 1px, transparent 1px);
  background-size: 100% 100%, 44px 44px, 44px 44px;
  background-position: center top, center top, center top;
`;

const TopRight = styled.div`
  position: absolute;
  top: 20px;
  right: 20px;
  display: flex;
  align-items: center;
  gap: 10px;
`;

const LangSwitch = styled.div`
  display: inline-flex;
  padding: 3px;
  gap: 2px;
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.sm};
`;

const LangButton = styled.button`
  height: 26px;
  padding: 0 10px;
  font-size: 12px;
  font-weight: 600;
  color: ${({ $active, theme }) => ($active ? theme.colors.onAccent : theme.colors.secondary)};
  background-color: ${({ $active, theme }) => ($active ? theme.colors.accent : 'transparent')};
  border: none;
  border-radius: ${({ theme }) => theme.radii.xs};
  cursor: ${({ $active }) => ($active ? 'default' : 'pointer')};
`;

const Brand = styled.div`
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
  font-size: 24px;
  font-weight: 750;
  letter-spacing: -0.03em;
  color: ${({ theme }) => theme.colors.primary};
`;

const Card = styled.form`
  position: relative;
  width: 100%;
  max-width: 400px;
  padding: 32px;
  background-color: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.lg};
  box-shadow: ${({ theme }) => theme.shadows.pop};
`;

const Title = styled.h1`
  font-size: 22px;
  font-weight: 700;
  color: ${({ theme }) => theme.colors.primary};
  margin: 0 0 6px;
`;

const Subtitle = styled.p`
  font-size: 14px;
  color: ${({ theme }) => theme.colors.secondary};
  margin: 0 0 24px;
`;

const OrgButton = styled.button`
  width: 100%;
  height: 46px;
  padding: 0 14px;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 14px;
  font-weight: 550;
  text-align: left;
  color: ${({ theme }) => theme.colors.primary};
  background-color: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: ${({ theme }) => theme.radii.sm};
  transition: border-color 0.12s ease, background-color 0.12s ease;

  &:hover:not(:disabled) {
    border-color: ${({ theme }) => theme.colors.accentNeon};
    background-color: ${({ theme }) => theme.colors.accentSoft};
  }

  &:disabled {
    opacity: 0.6;
    cursor: default;
  }

  small {
    color: ${({ theme }) => theme.colors.accent};
    font-size: 12px;
    font-weight: 600;
  }
`;

const FullButton = styled(PrimaryButton)`
  width: 100%;
  height: 40px;
  margin-top: 8px;
  font-size: 14px;
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
        <Logo size={40} />
        Voxline
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
