import styled from 'styled-components';
import { useLocation } from 'react-router-dom';
import { FiMenu, FiChevronRight, FiMoon, FiSun } from 'react-icons/fi';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { NAV_SECTIONS } from 'app/navItems';
import { useNav } from 'app/NavContext';

const Bar = styled.header`
  position: sticky;
  top: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  height: ${({ theme }) => theme.layout.topbar};
  padding: 0 20px;
  background: ${({ theme }) => (theme.mode === 'dark' ? 'rgba(11, 14, 20, 0.82)' : 'rgba(245, 246, 248, 0.82)')};
  backdrop-filter: saturate(160%) blur(10px);
  border-bottom: 1px solid ${({ theme }) => theme.colors.border};

  @media (min-width: 961px) {
    padding: 0 32px;
  }
`;

const Left = styled.div`
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
`;

const Crumbs = styled.nav`
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: 13.5px;
  color: ${({ theme }) => theme.colors.muted};
  white-space: nowrap;

  svg {
    flex-shrink: 0;
    font-size: 14px;
    opacity: 0.7;
  }

  strong {
    overflow: hidden;
    text-overflow: ellipsis;
    font-weight: 600;
    color: ${({ theme }) => theme.colors.primary};
  }
`;

const IconButton = styled.button`
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: 1px solid transparent;
  border-radius: ${({ theme }) => theme.radii.sm};
  background: transparent;
  color: ${({ theme }) => theme.colors.secondary};
  transition: background-color 0.12s ease, color 0.12s ease, border-color 0.12s ease;

  &:hover {
    background: ${({ theme }) => theme.colors.hover};
    color: ${({ theme }) => theme.colors.primary};
  }

  svg {
    font-size: 18px;
  }
`;

const MenuButton = styled(IconButton)`
  margin-left: -8px;

  @media (min-width: 901px) {
    display: none;
  }
`;

// Section › page for the current URL (the most specific page wins).
const locate = (pathname) => {
  let best = null;
  for (const section of NAV_SECTIONS) {
    for (const page of section.children) {
      const hit = pathname === page.path || (!page.exact && pathname.startsWith(`${page.path}/`));
      if (hit && (!best || page.path.length > best.page.path.length)) best = { section, page };
    }
  }
  return best;
};

export const Topbar = () => {
  const { t } = useI18n();
  const { isDark, toggleTheme } = useTheme();
  const { setOpen } = useNav();
  const { pathname } = useLocation();
  const here = locate(pathname);

  return (
    <Bar>
      <Left>
        <MenuButton type="button" onClick={() => setOpen(true)} aria-label={t('nav.menu')}>
          <FiMenu />
        </MenuButton>
        {here && (
          <Crumbs aria-label="Breadcrumb">
            {here.section.children.length > 1 && (
              <>
                <span>{t(`nav.${here.section.key}`)}</span>
                <FiChevronRight />
              </>
            )}
            <strong>{t(`nav.${here.page.key}`)}</strong>
          </Crumbs>
        )}
      </Left>
      <IconButton
        type="button"
        onClick={toggleTheme}
        aria-label={t('userMenu.theme')}
        title={t('userMenu.theme')}
      >
        {isDark ? <FiSun /> : <FiMoon />}
      </IconButton>
    </Bar>
  );
};
