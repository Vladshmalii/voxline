import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';

// Sidebar state shared by the sidebar itself and the top bar's menu button:
// `collapsed` is the desktop icon-rail mode (remembered between visits),
// `open` is the mobile drawer.
const KEY = 'voxline:nav-collapsed';

const NavContext = createContext({
  collapsed: false,
  toggleCollapsed: () => {},
  open: false,
  setOpen: () => {},
});

const readCollapsed = () => {
  try {
    return localStorage.getItem(KEY) === '1';
  } catch (_) {
    return false;
  }
};

export const NavProvider = ({ children }) => {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();

  // Following a link closes the mobile drawer.
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  const toggleCollapsed = useCallback(() => {
    setCollapsed((value) => {
      try {
        localStorage.setItem(KEY, value ? '0' : '1');
      } catch (_) {
        /* private mode: the choice just is not remembered */
      }
      return !value;
    });
  }, []);

  const value = useMemo(
    () => ({ collapsed, toggleCollapsed, open, setOpen }),
    [collapsed, toggleCollapsed, open]
  );
  return <NavContext.Provider value={value}>{children}</NavContext.Provider>;
};

export const useNav = () => useContext(NavContext);
