import { registerMessages } from '../registry';

// In-app login page (/login).
registerMessages('auth', {
  en: {
    title: 'Sign in to Voxline',
    subtitle: 'Enter your credentials to open the admin panel.',
    email: 'Email',
    password: 'Password',
    signIn: 'Sign in',
    signingIn: 'Signing in…',
    failed: 'Sign-in failed',
    invalidCredentials: 'Wrong email or password.',
    checking: 'Checking session…',
    orgTitle: 'Choose an organization',
    orgSubtitle: 'Your account belongs to several organizations. Pick the one to work in.',
    orgCurrent: 'current',
    orgContinue: 'Continue',
    orgFailed: 'Failed to switch organization',
  },
  ru: {
    title: 'Вход в Voxline',
    subtitle: 'Введите данные, чтобы открыть панель управления.',
    email: 'Эл. почта',
    password: 'Пароль',
    signIn: 'Войти',
    signingIn: 'Входим…',
    failed: 'Не удалось войти',
    invalidCredentials: 'Неверная почта или пароль.',
    checking: 'Проверяем сессию…',
    orgTitle: 'Выберите организацию',
    orgSubtitle: 'Ваш аккаунт состоит в нескольких организациях. Выберите, в какой работать.',
    orgCurrent: 'текущая',
    orgContinue: 'Продолжить',
    orgFailed: 'Не удалось сменить организацию',
  },
});
