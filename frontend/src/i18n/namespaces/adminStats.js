import { registerMessages } from '../registry';

// Admin analytics page (GET /admin/stats): company-wide calls, billing and
// resource counters. The "success" wording follows the product definition —
// a call is successful when at least one SMS was sent after it.
registerMessages('adminStats', {
  en: {
    title: 'Company admin analytics',
    loadFailed: 'Failed to load admin analytics',
    organization: 'Company / Account: {id}',
    refresh: 'Refresh',
    min: 'min',
    sec: 'sec',
    sections: {
      calls: 'Call and conversion metrics',
      finance: 'Timing and account finances',
      resources: 'Company resources',
    },
    cards: {
      callsTotal: {
        label: 'Total calls',
        help: 'Total number of outbound calls created to date, across all campaigns and agents.',
        sub: 'Total number of calls created',
      },
      callsSuccess: {
        label: 'Successful calls (SMS sent)',
        help:
          'Calls after which the customer was sent at least one SMS. This is our definition of success and does not depend on the phone status of the call itself (busy / no answer / dropped, etc.). The progress bar and percentage below show their share of all calls.',
        sub: '{pct}% of all calls',
      },
      callsFailed: {
        label: 'No SMS (unsuccessful)',
        help:
          'Calls after which no SMS was sent to the customer. By our definition these are unsuccessful calls, regardless of how the call itself ended.',
        sub: '{pct}% of all calls',
      },
      answerRate: {
        label: 'Answer rate',
        help:
          'Share of dial attempts that the callee answered. "Conversion to outcome" is the share of calls with the target outcome (Converted).',
        sub: 'Conversion to outcome: {pct}%',
      },
      talkTime: {
        label: 'Total talk time',
        help:
          'Total duration of all answered calls, in minutes. Used to calculate costs under the per-minute tariff.',
        sub: 'Average duration: {sec} sec',
      },
      balance: {
        label: 'Current balance',
        help:
          'Current funds remaining on the organization balance. "Minutes left" is how many talk minutes can be made at the current balance and tariff.',
        sub: 'Minutes left: {min} min',
      },
      spent: {
        label: 'Total spent',
        help:
          'Estimated cost of all completed calls and SMS at current tariffs. This is not an actual balance deduction — the balance only decreases through explicit charges. "Total deposited" is the sum of all balance top-ups.',
        sub: 'Total deposited: {amount}',
      },
      tariff: {
        label: 'Tariff rates',
        help:
          'Current organization tariffs: cost per talk minute and cost per SMS. Configured in the billing section.',
        call: 'Call, per minute',
        sms: 'SMS, each',
      },
      smsSent: {
        label: 'SMS sent',
        help: 'Total number of SMS messages sent to date, excluding undelivered ones (failed).',
        sub: 'Total cost: {amount}',
      },
      agents: {
        label: 'Voice agents',
        help: 'Total number of configured voice agents. "Active" means agents ready to take calls.',
        sub: 'Active: {count}',
      },
      campaigns: {
        label: 'Calling campaigns',
        help:
          'Total number of calling campaigns. "Running" means campaigns in the "In progress" status.',
        sub: 'Running: {count}',
      },
      leads: {
        label: 'Customer base (Leads)',
        help: 'Total number of contacts (leads) across all audiences of the organization.',
        sub: 'Total contacts in the base',
      },
    },
  },
  ru: {
    title: 'Админ-статистика компании',
    loadFailed: 'Ошибка загрузки админ-статистики',
    organization: 'Компания / Аккаунт: {id}',
    refresh: 'Обновить',
    min: 'мин',
    sec: 'сек',
    sections: {
      calls: 'Показатели звонков и конверсии',
      finance: 'Хронометраж и финансы аккаунта',
      resources: 'Ресурсы компании',
    },
    cards: {
      callsTotal: {
        label: 'Всего звонков',
        help: 'Общее количество созданных исходящих вызовов за всё время, по всем кампаниям и агентам.',
        sub: 'Общее число созданных вызовов',
      },
      callsSuccess: {
        label: 'Успешные звонки (Отправлено SMS)',
        help:
          'Звонки, после которых клиенту было отправлено хотя бы одно SMS — это наше определение успеха, оно не зависит от телефонного статуса самого звонка (занято/не ответили/сброс и т.д.). Прогресс-бар и процент ниже показывают их долю от общего числа звонков.',
        sub: '{pct}% от общего числа звонков',
      },
      callsFailed: {
        label: 'Без SMS (неуспешные)',
        help:
          'Звонки, после которых SMS клиенту отправлено не было — по нашему определению это неуспешные звонки, независимо от того, как завершился сам звонок.',
        sub: '{pct}% от общего числа звонков',
      },
      answerRate: {
        label: 'Доля дозвона (Answer Rate)',
        help:
          'Доля попыток дозвона, на которые абонент ответил. «Конверсия в результат» — доля звонков с целевым исходом (Converted).',
        sub: 'Конверсия в результат: {pct}%',
      },
      talkTime: {
        label: 'Общее время разговоров',
        help:
          'Суммарная длительность всех отвеченных звонков, в минутах. Используется для расчёта расходов по тарифу «за минуту».',
        sub: 'Средняя длительность: {sec} сек',
      },
      balance: {
        label: 'Текущий баланс',
        help:
          'Текущий остаток средств на балансе организации. «Осталось минут» — сколько минут разговора можно совершить при текущем балансе и тарифе.',
        sub: 'Осталось минут: {min} мин',
      },
      spent: {
        label: 'Всего израсходовано',
        help:
          'Расчётная стоимость всех состоявшихся звонков и SMS по текущим тарифам — это не фактическое списание с баланса, баланс уменьшается только явным списанием. «Всего пополнено» — сумма всех пополнений баланса.',
        sub: 'Всего пополнено: {amount}',
      },
      tariff: {
        label: 'Тарифная стоимость',
        help:
          'Текущие тарифы организации: стоимость минуты разговора и стоимость одного SMS. Настраиваются в разделе биллинга.',
        call: 'Звонок, за минуту',
        sms: 'SMS, за штуку',
      },
      smsSent: {
        label: 'Отправлено SMS',
        help: 'Общее количество отправленных SMS-сообщений за всё время, без учёта недоставленных (failed).',
        sub: 'На сумму: {amount}',
      },
      agents: {
        label: 'Голосовые агенты',
        help: 'Общее количество настроенных голосовых агентов. «Активно» — агенты, готовые принимать звонки.',
        sub: 'Активно: {count}',
      },
      campaigns: {
        label: 'Кампании обзвона',
        help:
          'Общее количество кампаний обзвона. «Запущено» — кампании в статусе «Выполняется».',
        sub: 'Запущено: {count}',
      },
      leads: {
        label: 'Клиентская база (Лиды)',
        help: 'Общее количество контактов (лидов) во всех аудиториях организации.',
        sub: 'Всего контактов в базе',
      },
    },
  },
});
