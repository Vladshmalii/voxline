import { registerMessages } from '../registry';

// VOAD-38, extended: the global snapshot (GET /stats/overview) plus a
// separate calls-per-day trend (GET /stats/timeseries?date_from&date_to).
// Breakdown labels are translated through the same enum-label maps used
// elsewhere (STATUS_LABEL_KEYS/CAMPAIGN_STATUS_LABEL_KEYS in
// components/badges.jsx, calls.reasonCategories.*, audiences.leads.statuses.*
// for leads) — see DashboardPage.jsx's own module docstring.
registerMessages('dashboard', {
  en: {
    title: 'Dashboard',
    noData: 'No data yet.',
    autoRefresh: 'Auto-refresh',
    sections: {
      overview: 'Overview',
      trend: 'Trend',
      breakdown: 'Breakdown',
    },
    kpi: {
      totalCalls: 'Total calls',
      callsToday: 'Calls today',
      answerRate: 'Answer rate',
      avgDuration: 'Avg. call duration',
      runningCampaigns: 'Running campaigns',
      activeAgents: 'Active agents',
      totalLeads: 'Total leads',
      smsSent: 'SMS sent',
    },
    help: {
      totalCalls: 'Total number of calls ever created, across every agent and campaign. Not affected by the date range above — that range only controls the trend chart below.',
      callsToday: 'Number of calls created since midnight today (server time).',
      answerRate: 'Share of call attempts that the callee actually answered.',
      avgDuration: 'Average duration of connected calls, from answer to hang-up.',
      runningCampaigns: 'Campaigns currently in the "Running" status, out of the total number of campaigns.',
      activeAgents: 'Voice agents currently enabled and able to take calls, out of the total number configured.',
      totalLeads: 'Total number of contacts (leads) in the client database, across every audience.',
      smsSent: 'Total number of SMS messages sent so far, excluding ones that failed to send.',
    },
    range: {
      '7': '7 days',
      '14': '14 days',
      '30': '30 days',
      '90': '90 days',
      custom: 'Custom',
      from: 'From',
      to: 'To',
    },
    charts: {
      callsTrend: 'Calls over time',
      callsTrendTotal: 'Total',
      callsTrendCompleted: 'Success (SMS sent: Completed)',
      callsTrendFailed: 'Failed (Other statuses)',
      callsByStatus: 'Calls by status',
      callsByOutcome: 'Calls by outcome',
      declineReasons: 'Decline reasons',
      campaignsByStatus: 'Campaigns by status',
      topCampaigns: 'Busiest campaigns',
      leadsByStatus: 'Leads by status',
      activeGeo: 'Active call GEOs',
    },
    unknownGeo: 'Unknown',
    geo: {
      country: 'Country',
      campaigns: 'Campaigns',
      calls: 'Calls',
    },
    duration: (p) => {
      const s = p.seconds;
      if (s === 0) return '0s';
      if (s % 3600 === 0) return `${s / 3600}h`;
      if (s % 60 === 0) return `${s / 60}m`;
      const m = Math.floor(s / 60);
      const rem = s % 60;
      return m > 0 ? `${m}m ${rem}s` : `${rem}s`;
    },
  services: {
    telephonyDown: 'Warning: telephony is inactive or the gateway is unreachable. Calls cannot be placed!',
    title: 'Connected services status',
    operational: 'All services operational',
    degraded: 'Partial limitations',
    down: 'Services down',
    refresh: 'Refresh',
    latency: 'Latency: {ms} ms',
  },
  },
  ru: {
    title: 'Дашборд',
    noData: 'Пока нет данных.',
    autoRefresh: 'Автообновление',
    sections: {
      overview: 'Обзор',
      trend: 'Динамика',
      breakdown: 'Разбивка',
    },
    kpi: {
      totalCalls: 'Всего звонков',
      callsToday: 'Звонков сегодня',
      answerRate: 'Доля дозвона',
      avgDuration: 'Средняя длительность',
      runningCampaigns: 'Активных кампаний',
      activeAgents: 'Активных агентов',
      totalLeads: 'Всего лидов',
      smsSent: 'Отправлено SMS',
    },
    help: {
      totalCalls: 'Общее количество звонков за всё время, по всем агентам и кампаниям. Не зависит от периода выше — период влияет только на график динамики ниже.',
      callsToday: 'Количество звонков, созданных с начала текущих суток (по серверному времени).',
      answerRate: 'Доля попыток дозвона, на которые абонент действительно ответил.',
      avgDuration: 'Средняя длительность разговора — от ответа абонента до завершения звонка.',
      runningCampaigns: 'Кампании в статусе «Выполняется» от общего числа кампаний.',
      activeAgents: 'Голосовые агенты, включённые и готовые принимать звонки, от общего числа настроенных.',
      totalLeads: 'Общее количество контактов (лидов) в клиентской базе, по всем аудиториям.',
      smsSent: 'Общее количество отправленных SMS, без учёта тех, что не удалось отправить.',
    },
    range: {
      '7': '7 дней',
      '14': '14 дней',
      '30': '30 дней',
      '90': '90 дней',
      custom: 'Свой период',
      from: 'С',
      to: 'По',
    },
    charts: {
      callsTrend: 'Динамика звонков по дням',
      callsTrendTotal: 'Всего',
      callsTrendCompleted: 'Успех (Отправили СМС: Завершен)',
      callsTrendFailed: 'Не успех (Не отправили СМС: остальные)',
      callsByStatus: 'Звонки по статусу',
      callsByOutcome: 'Звонки по исходу',
      declineReasons: 'Причины отказа',
      campaignsByStatus: 'Кампании по статусу',
      topCampaigns: 'Кампании по объёму звонков',
      leadsByStatus: 'Лиды по статусу',
      activeGeo: 'GEO активных обзвонов',
    },
    unknownGeo: 'Неизвестно',
    geo: {
      country: 'Страна',
      campaigns: 'Кампании',
      calls: 'Звонки',
    },
    duration: (p) => {
      const s = p.seconds;
      if (s === 0) return '0 с';
      if (s % 3600 === 0) return `${s / 3600} ч`;
      if (s % 60 === 0) return `${s / 60} мин`;
      const m = Math.floor(s / 60);
      const rem = s % 60;
      return m > 0 ? `${m} мин ${rem} с` : `${rem} с`;
    },
  services: {
    telephonyDown: 'Внимание: Телефония не активна или шлюз недоступен. Звонки не смогут совершаться!',
    title: 'Статус подключенных сервисов',
    operational: 'Все сервисы работают',
    degraded: 'Частичные ограничения',
    down: 'Сбой сервисов',
    refresh: 'Обновить',
    latency: 'Задержка: {ms} мс',
  },
  },
});
