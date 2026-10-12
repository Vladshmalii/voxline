import { useState, useEffect } from 'react';
import styled from 'styled-components';
import { Outlet } from 'react-router-dom';
import { useTheme } from 'contexts/ThemeContext';
import { UserContext } from 'contexts/UserContext';
import { fetchMe } from 'utils/authApi';
import { normalizeMe } from 'utils/authSession';
import { meApi, modelsApi } from 'utils/callApi';
import { redirectToLogin } from 'utils/api';
import { ROLES, canView, canAssignModels } from 'utils/permissions';
import { prefetchVoiceCatalog } from 'utils/voiceCatalog';
import { Header } from 'app/Header';
import { Sidebar } from 'app/Sidebar';

const LayoutContainer = styled.div`
  display: flex;
  flex-direction: column;
  height: 100vh;
  background-color: ${({ theme }) => theme.colors.background};
  overflow: hidden;
`;

const ContentWrapper = styled.div`
  display: flex;
  flex: 1;
  overflow: hidden;
`;

const Main = styled.main`
  flex: 1;
  overflow: hidden;
  padding: 0 10px 10px 3px;
  display: flex;
`;

const ContentArea = styled.div`
  width: 100%;
  height: 100%;
  background-color: ${({ theme }) =>
    theme.colors.surface === '#F9FAFB' ? '#F0F1F3' : theme.colors.surface};
  border-radius: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  overflow: auto;
`;

export const AppLayout = () => {
  const { theme } = useTheme();
  const [user, setUser] = useState(null);
  const [authChecked, setAuthChecked] = useState(false);

  useEffect(() => {
    let active = true;
    fetchMe()
      .then((res) => {
        if (res.status === 401) {
          redirectToLogin();
          return null;
        }
        return res.ok ? res.json() : null;
      })
      .then(async (data) => {
        if (!active || !data) return;
        // Role gates the UI (utils/permissions.js) — a failed fetch is treated
        // as no access rather than blocking the app on the session gate above.
        let role = ROLES.NONE;
        let billingEnabled = true;
        try {
          const permission = await meApi.getRole();
          role = permission?.role || ROLES.NONE;
          billingEnabled = permission?.billing_enabled !== false;
        } catch (_) {
          role = ROLES.NONE;
        }
        if (!active) return;
        setUser({ ...normalizeMe(data), role, billing_enabled: billingEnabled });
        setAuthChecked(true);
      })
      .catch(() => {
        if (active) setAuthChecked(true);
      });
    return () => {
      active = false;
    };
  }, []);

  // Warm the voice catalogue as soon as the role is known, so the Voice agents
  // pickers and the voice catalogue modal open without waiting on the vendor.
  useEffect(() => {
    if (user && canView('agents', user.role)) prefetchVoiceCatalog(modelsApi, canAssignModels(user.role));
  }, [user]);

  // Hold the shell until auth resolves so we never flash app content to a
  // signed-out user before the redirect kicks in.
  if (!authChecked) return null;

  return (
    <UserContext.Provider value={user}>
      <LayoutContainer theme={theme}>
        <Header />
        <ContentWrapper>
          <Sidebar />
          <Main>
            <ContentArea theme={theme}>
              <Outlet />
            </ContentArea>
          </Main>
        </ContentWrapper>
      </LayoutContainer>
    </UserContext.Provider>
  );
};
