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
import { NavProvider } from 'app/NavContext';
import { Sidebar } from 'app/Sidebar';
import { Topbar } from 'app/Topbar';

// Sidebar on the left, a sticky top bar and the page on the right.
const Shell = styled.div`
  display: flex;
  min-height: 100vh;
  background-color: ${({ theme }) => theme.colors.background};
  color: ${({ theme }) => theme.colors.primary};
`;

const Column = styled.div`
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
`;

const Main = styled.main`
  flex: 1;
  width: 100%;
  max-width: 1680px;
  margin: 0 auto;
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
      <NavProvider>
        <Shell theme={theme}>
          <Sidebar />
          <Column>
            <Topbar />
            <Main>
              <Outlet />
            </Main>
          </Column>
        </Shell>
      </NavProvider>
    </UserContext.Provider>
  );
};
