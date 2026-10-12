import { lightTheme, darkTheme } from './colors';

export const getTheme = (isDark = false) => {
  return isDark ? darkTheme : lightTheme;
};

export const toggleTheme = (currentTheme) => {
  return currentTheme === 'light' ? 'dark' : 'light';
};

export { lightTheme, darkTheme };

export default {
  light: lightTheme,
  dark: darkTheme,
};
