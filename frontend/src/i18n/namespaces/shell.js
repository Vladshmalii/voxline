import { registerMessages } from '../registry';

// Sidebar tabs. Keys match the `key` of each entry in app/navItems.js.
registerMessages('nav', {
  en: {
    dashboard: 'Dashboard',
    navigation: 'Navigation',
    callStats: 'Statistics',
    callBilling: 'Billing',
    callList: 'Call list',
    messages: 'Messages',
    smsStats: 'Statistics',
    smsBilling: 'Billing',
    smsList: 'Message list',
    billing: 'Billing & Finances',
    adminStats: 'Admin Analytics',
    agents: 'Voice agents',
    campaigns: 'Campaigns',
    audiences: 'Audiences',
    calls: 'Calls',
    models: 'Models',
    providers: 'Providers',
    telephony: 'Telephony',
    messaging: 'Messaging',
    sms: 'SMS',
    smsModeration: 'SMS moderation',
    users: 'Users & Organizations',
  },
  ru: {
    dashboard: 'Дашборд',
    navigation: 'Навигация',
    callStats: 'Статистика',
    callBilling: 'Биллинг',
    callList: 'Список звонков',
    messages: 'Сообщения',
    smsStats: 'Статистика',
    smsBilling: 'Биллинг',
    smsList: 'Список сообщений',
    billing: 'Финансы и биллинг',
    adminStats: 'Админ-статистика',
    agents: 'Голосовые агенты',
    campaigns: 'Кампании',
    audiences: 'Аудитории',
    calls: 'Звонки',
    models: 'Модели',
    providers: 'Провайдеры',
    telephony: 'Телефония',
    messaging: 'Мессенджинг',
    sms: 'SMS',
    smsModeration: 'Модерация SMS',
    users: 'Пользователи и организации',
  },
});

registerMessages('userMenu', {
  en: {
    theme: 'Theme',
    language: 'Language',
    signOut: 'Sign out',
    organization: 'Organization',
    changeOrgError: 'Failed to change organization',
  },
  ru: {
    theme: 'Тема',
    language: 'Язык',
    signOut: 'Выйти',
    organization: 'Организация',
    changeOrgError: 'Не удалось сменить организацию',
  },
});

registerMessages('welcome', {
  en: {
    title: 'Voxline Panel',
    sub: 'Choose a section from the sidebar to get started.',
  },
  ru: {
    title: 'Панель Voxline',
    sub: 'Выберите раздел в боковом меню, чтобы начать.',
  },
});

// Standalone pages outside the app shell, plus the chunk-load fallback.
registerMessages('system', {
  en: {
    notFoundText: 'The page you are looking for does not exist.',
    goHome: 'Go home',
    chunkFailed: 'Failed to load the page. Please try again.',
    reload: 'Reload',
  },
  ru: {
    notFoundText: 'Такой страницы не существует.',
    goHome: 'На главную',
    chunkFailed: 'Не удалось загрузить страницу. Попробуйте ещё раз.',
    reload: 'Обновить',
  },
});
