import styled from 'styled-components';
import { NavLink, useLocation } from 'react-router-dom';
import { FiChevronsLeft, FiChevronsRight } from 'react-icons/fi';
import { useI18n } from 'contexts/I18nContext';
import { useUser } from 'contexts/UserContext';
import { NAV_SECTIONS } from 'app/navItems';
import { useNav } from 'app/NavContext';
import { Logo } from 'app/Logo';
import { OrgSwitcher } from 'app/OrgSwitcher';
import { UserMenu } from 'app/UserMenu';
import { canViewFor } from 'utils/permissions';

const MOBILE = '(max-width: 900px)';

const Backdrop = styled.div`
  display: none;

  @media ${MOBILE} {
    display: ${({ $open }) => ($open ? 'block' : 'none')};
    position: fixed;
    inset: 0;
    z-index: 900;
    background: rgba(2, 6, 14, 0.5);
    backdrop-filter: blur(2px);
  }
`;

const Aside = styled.aside`
  position: sticky;
  top: 0;
  align-self: flex-start;
  flex-shrink: 0;
  width: ${({ $collapsed, theme }) => ($collapsed ? theme.layout.sidebarCollapsed : theme.layout.sidebar)};
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: ${({ theme }) => theme.colors.surface};
  border-right: 1px solid ${({ theme }) => theme.colors.border};
  transition: width 0.2s ease, transform 0.22s ease;
  z-index: 1000;

  @media ${MOBILE} {
    position: fixed;
    left: 0;
    top: 0;
    width: min(300px, 86vw);
    transform: translateX(${({ $open }) => ($open ? '0' : '-102%')});
    box-shadow: ${({ $open, theme }) => ($open ? theme.shadows.pop : 'none')};
  }
`;

const Head = styled.div`
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  height: ${({ theme }) => theme.layout.topbar};
  padding: 0 ${({ $collapsed }) => ($collapsed ? '0' : '14px 0 18px')};
  justify-content: ${({ $collapsed }) => ($collapsed ? 'center' : 'space-between')};
  flex-shrink: 0;
`;

const Brand = styled.div`
  display: flex;
  align-items: center;
  gap: 11px;
  min-width: 0;
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: ${({ theme }) => theme.colors.primary};
`;

const IconButton = styled.button`
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border: none;
  border-radius: ${({ theme }) => theme.radii.xs};
  background: transparent;
  color: ${({ theme }) => theme.colors.muted};
  transition: background-color 0.12s ease, color 0.12s ease;

  &:hover {
    background: ${({ theme }) => theme.colors.hover};
    color: ${({ theme }) => theme.colors.primary};
  }

  @media ${MOBILE} {
    display: none;
  }
`;

const Block = styled.div`
  padding: 4px ${({ $collapsed }) => ($collapsed ? '14px' : '12px')} 10px;
  flex-shrink: 0;
`;

const Nav = styled.nav`
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 4px ${({ $collapsed }) => ($collapsed ? '14px' : '12px')} 12px;
  scrollbar-width: none;

  &::-webkit-scrollbar {
    display: none;
  }
`;

const SectionLabel = styled.div`
  padding: 16px 10px 6px;
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: ${({ theme }) => theme.colors.muted};
  white-space: nowrap;
  overflow: hidden;
  ${({ $collapsed }) =>
    $collapsed &&
    `
    height: 1px;
    padding: 0;
    margin: 12px 8px;
    font-size: 0;
    background: currentColor;
    opacity: 0.18;
  `}
`;

const Item = styled(NavLink)`
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  height: 38px;
  margin: 2px 0;
  padding: 0 ${({ $collapsed }) => ($collapsed ? '0' : '10px')};
  justify-content: ${({ $collapsed }) => ($collapsed ? 'center' : 'flex-start')};
  border-radius: ${({ theme }) => theme.radii.sm};
  color: ${({ theme }) => theme.colors.secondary};
  font-size: 14px;
  font-weight: 500;
  text-decoration: none;
  white-space: nowrap;
  transition: background-color 0.12s ease, color 0.12s ease;

  svg {
    flex-shrink: 0;
    font-size: 18px;
    color: ${({ theme }) => theme.colors.muted};
    transition: color 0.12s ease;
  }

  span {
    overflow: hidden;
    text-overflow: ellipsis;
  }

  &:hover {
    background: ${({ theme }) => theme.colors.hover};
    color: ${({ theme }) => theme.colors.primary};
  }

  &.active {
    background: ${({ theme }) => theme.colors.accentSoft};
    color: ${({ theme }) => (theme.mode === 'dark' ? theme.colors.accentNeon : theme.colors.accent)};
    font-weight: 600;
  }

  &.active svg {
    color: ${({ theme }) => (theme.mode === 'dark' ? theme.colors.accentNeon : theme.colors.accent)};
  }

  &.active::before {
    content: '';
    position: absolute;
    left: ${({ $collapsed }) => ($collapsed ? '-14px' : '-12px')};
    top: 9px;
    bottom: 9px;
    width: 3px;
    border-radius: 0 3px 3px 0;
    background: ${({ theme }) => theme.colors.accent};
  }
`;

const Foot = styled.div`
  padding: 10px ${({ $collapsed }) => ($collapsed ? '14px' : '12px')} 12px;
  border-top: 1px solid ${({ theme }) => theme.colors.divider};
  flex-shrink: 0;
`;

// /calls must not light up while /calls/billing is open: the most specific
// matching page wins (NavLink's own prefix matching cannot know that).
const matches = (item, pathname) =>
  pathname === item.path || (!item.exact && pathname.startsWith(`${item.path}/`));

export const Sidebar = () => {
  const { t } = useI18n();
  const user = useUser();
  const { pathname } = useLocation();
  const { collapsed: stored, toggleCollapsed, open, setOpen } = useNav();
  // The drawer is always full width; only the desktop rail collapses.
  const collapsed = stored && !open;

  const sections = NAV_SECTIONS.map((section) => ({
    ...section,
    children: section.children.filter(({ key, resource = key }) => canViewFor(resource, user)),
  })).filter((section) => section.children.length > 0);

  const activePath = sections
    .flatMap((section) => section.children)
    .filter((item) => matches(item, pathname))
    .sort((a, b) => b.path.length - a.path.length)[0]?.path;

  return (
    <>
      <Backdrop $open={open} onClick={() => setOpen(false)} />
      <Aside $collapsed={collapsed} $open={open} aria-label={t('nav.navigation')}>
        <Head $collapsed={collapsed}>
          <Brand>
            <Logo size={32} />
            {!collapsed && <span>Voxline</span>}
          </Brand>
          {!collapsed && (
            <IconButton type="button" onClick={toggleCollapsed} aria-label={t('nav.collapse')} title={t('nav.collapse')}>
              <FiChevronsLeft size={18} />
            </IconButton>
          )}
        </Head>

        <Block $collapsed={collapsed}>
          <OrgSwitcher collapsed={collapsed} />
        </Block>

        <Nav $collapsed={collapsed}>
          {sections.map((section) => (
            <div key={section.key}>
              {section.children.length > 1 && (
                <SectionLabel $collapsed={collapsed}>{t(`nav.${section.key}`)}</SectionLabel>
              )}
              {section.children.map((item) => {
                const Icon = item.icon;
                const label = t(`nav.${item.key}`);
                const active = item.path === activePath;
                return (
                  <Item
                    key={item.path}
                    to={item.path}
                    end
                    $collapsed={collapsed}
                    className={active ? 'active' : undefined}
                    aria-current={active ? 'page' : undefined}
                    title={collapsed ? label : undefined}
                  >
                    <Icon />
                    {!collapsed && <span>{label}</span>}
                  </Item>
                );
              })}
            </div>
          ))}
        </Nav>

        <Foot $collapsed={collapsed}>
          {collapsed && (
            <IconButton
              type="button"
              onClick={toggleCollapsed}
              aria-label={t('nav.expand')}
              title={t('nav.expand')}
              style={{ margin: '0 auto 8px', display: 'flex' }}
            >
              <FiChevronsRight size={18} />
            </IconButton>
          )}
          <UserMenu collapsed={collapsed} />
        </Foot>
      </Aside>
    </>
  );
};
