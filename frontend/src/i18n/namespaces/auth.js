import { registerMessages } from '../registry';

// In-app login page (/login).
registerMessages('auth', {
  en: {
    title: 'Sign in to Allo AI',
    subtitle: 'Enter your credentials to open the voice AI panel.',
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
    title: 'Вход в Allo AI',
    subtitle: 'Введите данные, чтобы открыть панель управления голосовыми агентами.',
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
