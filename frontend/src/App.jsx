import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider } from 'contexts/ThemeContext';
import { I18nProvider } from 'contexts/I18nContext';
import { useUser } from 'contexts/UserContext';
import { ChunkErrorBoundary } from 'components/ChunkErrorBoundary';
import { Toaster } from 'components/Toaster';
import { AppLayout } from 'app/AppLayout';
import { NAV_ITEMS } from 'app/navItems';
import { canViewFor, canPreviewVoice } from 'utils/permissions';

// Defense in depth for direct URL navigation — the backend is authoritative,
// this just avoids dropping a role without access onto a page full of 403s.
// `dashboard` itself never redirects (it's the fallback target — a role with
// no access anywhere, e.g. "none", would otherwise loop).
const RequireView = ({ resource, children }) => {
  const user = useUser();
  if (canViewFor(resource, user)) return children;
  if (resource === 'dashboard') return null;
  return <Navigate to="/dashboard" replace />;
};

const RequireVoicePreview = ({ children }) => {
  const user = useUser();
  if (canPreviewVoice(user?.role)) return children;
  return <Navigate to="/dashboard" replace />;
};

const WelcomePage = lazy(() => import('pages/WelcomePage').then((m) => ({ default: m.WelcomePage })));
const NotFoundPage = lazy(() => import('pages/NotFoundPage').then((m) => ({ default: m.NotFoundPage })));
const LoginPage = lazy(() => import('pages/LoginPage').then((m) => ({ default: m.LoginPage })));
const AgentDetailsPage = lazy(() =>
  import('pages/AgentDetailsPage').then((m) => ({ default: m.AgentDetailsPage }))
);
const PlaygroundPage = lazy(() =>
  import('pages/PlaygroundPage').then((m) => ({ default: m.PlaygroundPage }))
);

export const App = () => {
  return (
    <ThemeProvider>
      <I18nProvider>
        <BrowserRouter>
          <Toaster />
          <ChunkErrorBoundary>
            <Suspense fallback={null}>
              <Routes>
                {/* App zone — persistent Header + Sidebar via AppLayout/<Outlet/>,
                    gated by me(). Tabs come from NAV_ITEMS. */}
                <Route element={<AppLayout />}>
                  <Route path="/" element={<WelcomePage />} />
                  <Route path="/dashboard" element={<Navigate to="/calls/stats" replace />} />
                  <Route path="/billing" element={<Navigate to="/calls/billing" replace />} />
                  <Route path="/sms" element={<Navigate to="/messages" replace />} />
                  {NAV_ITEMS.map(({ key, resource = key, path, Page, props }) => (
                    <Route
                      key={path}
                      path={path}
                      element={
                        <RequireView resource={resource}>
                          <Page key={path} {...props} />
                        </RequireView>
                      }
                    />
                  ))}
                  {/* Agent workbench (languages + diagnostics) and the WS
                      playground — reached from the Agents tab, not the sidebar. */}
                  <Route
                    path="/agents/:agentId"
                    element={
                      <RequireView resource="agents">
                        <AgentDetailsPage />
                      </RequireView>
                    }
                  />
                  <Route
                    path="/agents/:agentId/playground"
                    element={
                      <RequireVoicePreview>
                        <PlaygroundPage />
                      </RequireVoicePreview>
                    }
                  />
                </Route>

                {/* Standalone — outside the shell and the me() gate. */}
                <Route path="/login" element={<LoginPage />} />
                <Route path="*" element={<NotFoundPage />} />
              </Routes>
            </Suspense>
          </ChunkErrorBoundary>
        </BrowserRouter>
      </I18nProvider>
    </ThemeProvider>
  );
};
