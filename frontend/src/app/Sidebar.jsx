import { useEffect, useState } from 'react';
import styled from 'styled-components';
import { FiChevronDown } from 'react-icons/fi';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { useUser } from 'contexts/UserContext';
import { SIDEBAR_ITEMS } from 'app/navItems';
import { canViewFor } from 'utils/permissions';

const SidebarStyled = styled.aside`
  width: 228px;
  height: 100%;
  background-color: ${({ theme }) => theme.colors.background};
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  padding: 16px 12px;
`;
const Nav = styled.nav`
  flex: 1;
  overflow-y: auto;
`;
const MenuItem = styled.button`
  width: 100%;
  border: none;
  text-align: left;
  padding: 10px 12px;
  margin: 2px 0;
  border-radius: 9px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: ${({ $child }) => ($child ? '13px' : '14px')};
  font-weight: ${({ $active, $group }) => ($active || $group ? '600' : '400')};
  background-color: ${({ $active, theme }) => ($active ? theme.colors.hover : 'transparent')};
  color: ${({ $active, theme }) => ($active ? theme.colors.primary : theme.colors.secondary)};
  transition: background-color 180ms ease, color 180ms ease;
  &:hover {
    background-color: ${({ theme }) => theme.colors.hover};
    color: ${({ theme }) => theme.colors.primary};
  }
  &:focus-visible { outline: 2px solid ${({ theme }) => theme.colors.accent}; outline-offset: -2px; }
  svg { font-size: 17px; flex-shrink: 0; }
`;
const Chevron = styled(FiChevronDown)`
  margin-left: auto;
  transform: rotate(${({ $open }) => ($open ? '180deg' : '0deg')});
  transition: transform 260ms cubic-bezier(0.2, 0.8, 0.2, 1);
  @media (prefers-reduced-motion: reduce) { transition: none; }
`;
const Submenu = styled.div`
  display: grid;
  grid-template-rows: ${({ $open }) => ($open ? '1fr' : '0fr')};
  opacity: ${({ $open }) => ($open ? 1 : 0)};
  visibility: ${({ $open }) => ($open ? 'visible' : 'hidden')};
  transition: grid-template-rows 260ms cubic-bezier(0.2, 0.8, 0.2, 1), opacity 180ms ease, visibility 260ms;
  @media (prefers-reduced-motion: reduce) { transition: none; }
`;
const SubmenuClip = styled.div`
  min-height: 0;
  overflow: hidden;
`;
const SubmenuContent = styled.div`
  border-left: 1px solid ${({ theme }) => theme.colors.border};
  margin: 3px 0 8px 20px;
  padding-left: 8px;
`;
const Group = styled.div`
  margin-bottom: 5px;
`;

const isActive = (item, pathname) => pathname === item.path ||
  (!item.exact && pathname.startsWith(`${item.path}/`));

const NavigationGroup = ({ item, pathname, theme, t, navigate }) => {
  const active = item.children.some((child) => isActive(child, pathname));
  const [open, setOpen] = useState(active);
  // Opening another page in this section also reveals its selected item.
  useEffect(() => { if (active) setOpen(true); }, [active, pathname]);
  const Icon = item.icon;
  return (
    <Group>
      <MenuItem theme={theme} $active={active} $group type="button"
        aria-expanded={open} aria-controls={`nav-${item.key}`} onClick={() => setOpen((value) => !value)}>
        <Icon /><span>{t(`nav.${item.key}`)}</span><Chevron $open={open} />
      </MenuItem>
      <Submenu id={`nav-${item.key}`} $open={open} aria-hidden={!open}>
        <SubmenuClip><SubmenuContent theme={theme}>
          {item.children.map((child) => {
            const { key, path, icon: ChildIcon } = child;
            const childActive = isActive(child, pathname);
            return (
              <MenuItem key={path} theme={theme} $child $active={childActive}
                type="button" tabIndex={open ? 0 : -1} aria-current={childActive ? 'page' : undefined}
                onClick={() => navigate(path)}>
                <ChildIcon /><span>{t(`nav.${key}`)}</span>
              </MenuItem>
            );
          })}
        </SubmenuContent></SubmenuClip>
      </Submenu>
    </Group>
  );
};

export const Sidebar = () => {
  const { theme } = useTheme();
  const { t } = useI18n();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const user = useUser();
  const items = SIDEBAR_ITEMS.map((item) => item.children
    ? { ...item, children: item.children.filter(({ key, resource = key }) => canViewFor(resource, user)) }
    : item).filter((item) => item.children ? item.children.length > 0 : canViewFor(item.resource || item.key, user));
  return (
    <SidebarStyled theme={theme}>
      <Nav aria-label={t('nav.navigation')}>
        {items.map((item) => {
          if (item.children) return <NavigationGroup key={item.key} item={item} pathname={pathname} theme={theme} t={t} navigate={navigate} />;
          const Icon = item.icon;
          return (
            <MenuItem key={item.path} theme={theme} $active={isActive(item, pathname)} type="button"
              aria-current={isActive(item, pathname) ? 'page' : undefined} onClick={() => navigate(item.path)}>
              <Icon /><span>{t(`nav.${item.key}`)}</span>
            </MenuItem>
          );
        })}
      </Nav>
    </SidebarStyled>
  );
};
