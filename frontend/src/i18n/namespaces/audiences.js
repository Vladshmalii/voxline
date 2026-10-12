import { registerMessages } from '../registry';

// This page shows the org's lead list (Client-level, VOAD-34), a status-
// segment CSV import (VOAD-32), and upload-batch history. The old per-
// audience CRUD/CSV/JSON upload UI (create/edit an audience, upload its own
// contact list) was removed from the main screen at the user's request —
// audiences still exist as a backend concept (a campaign can still target
// one via campaignsApi.addAudience, see campaigns.js), there is just no
// audience-management UI left in this app; csvUpload.*/uploadResult.* below
// are kept because the client-segment import modal reuses them.
registerMessages('audiences', {
  en: {
    title: 'Audiences',
    csvUpload: {
      chooseFile: 'Choose CSV file',
      noFile: 'No file selected',
      submit: 'Upload',
      uploading: 'Uploading…',
      invalid: 'Choose a CSV file first.',
    },
    uploadResult: {
      result: '{accepted} accepted, {rejected} rejected',
      resultPhone: 'Phone',
      resultError: 'Error',
      accepted: 'Accepted:',
      rejected: 'Rejected:',
    },
    clientImport: {
      button: 'Import clients (CSV)',
      title: 'Import clients (CSV)',
      hint:
        'Columns: phone (required), name, country, language, status (active, do_not_call, blocked). Upserts clients by phone.',
      audienceName: 'Audience',
      audienceNamePlaceholder: 'Type an existing name or a new one',
      audienceNameHint:
        'Optional — files every row from this file under this named audience (an existing ' +
        'one is matched by name, otherwise a new one is created), so you can find and filter ' +
        'them later.',
    },
    leads: {
      idleTimeout: 'Idle timeout (sec)',
      idleTimeoutPlaceholder: 'Agent default',
      title: 'Leads',
      search: 'Search',
      searchPlaceholder: 'Phone or name',
      status: 'Status',
      all: 'All',
      audience: 'Audience',
      country: 'Country',
      language: 'Language',
      exactMatch: 'Exact match',
      lastActiveFrom: 'Last active from',
      lastActiveTo: 'Last active to',
      noMatch: 'No leads match these filters.',
      incomplete: 'Incomplete',
      edit: 'Edit',
      editTitle: 'Edit lead — {phone}',
      saved: 'Lead updated successfully',
      // ClientStatusEnum, verbatim.
      statuses: {
        active: 'Active',
        do_not_call: 'Do not call',
        blocked: 'Blocked',
      },
      columns: {
        phone: 'Phone',
        name: 'Name',
        status: 'Status',
        audience: 'Audience',
        answeredCalls: 'Answered calls',
        language: 'Language',
        lastActive: 'Last active',
        country: 'Country',
        actions: 'Actions',
      },
    },
    callHistory: {
      title: 'Call history — {phone}',
      noCalls: 'No calls yet for this lead.',
      summary:
        '{totalAttempts} dial attempts to this number ({total} call record(s)) · {completed} completed · {canceled} canceled · {noAnswer} not answered',
      columns: {
        when: 'When',
        outcome: 'Outcome',
        campaign: 'Campaign',
        attempts: 'Attempts',
        duration: 'Duration (s)',
      },
    },
    manage: {
      button: 'Audiences',
      title: 'Audiences',
      noAudiences: 'No audiences yet.',
      columns: {
        name: 'Name',
        members: 'Members',
      },
      deleteTitle: 'Delete "{name}"?',
      deleteWarning:
        'This removes the audience and its {count} member(s) — leads themselves and their call history are unaffected, only the audience list disappears.',
    },
    uploadHistory: {
      button: 'Upload history',
      title: 'Upload history',
      noUploads: 'No uploads yet.',
      columns: {
        when: 'When',
        who: 'Who',
        filename: 'Filename',
        audience: 'Audience',
        total: 'Total',
        valid: 'Valid',
        invalid: 'Invalid',
        leads: 'Leads',
      },
      user: 'User #{id}',
      viewLeads: 'View leads',
      notTiedToAudience: 'Not tied to an audience — leads from this batch cannot be isolated',
      batchTitle: 'Batch #{id} — leads',
      backToHistory: '← Back to history',
      noLeadsForBatch: 'No leads found for this audience.',
    },
  },
  ru: {
    title: 'Аудитории',
    csvUpload: {
      chooseFile: 'Выбрать CSV-файл',
      noFile: 'Файл не выбран',
      submit: 'Загрузить',
      uploading: 'Загрузка…',
      invalid: 'Сначала выберите CSV-файл.',
    },
    uploadResult: {
      result: 'принято {accepted}, отклонено {rejected}',
      resultPhone: 'Телефон',
      resultError: 'Ошибка',
      accepted: 'Принято:',
      rejected: 'Отклонено:',
    },
    clientImport: {
      button: 'Импорт клиентов (CSV)',
      title: 'Импорт клиентов (CSV)',
      hint:
        'Колонки: phone (обязательно), name, country, language, status (active, do_not_call, blocked). Обновляет клиентов по телефону.',
      audienceName: 'Аудитория',
      audienceNamePlaceholder: 'Введите существующее или новое название',
      audienceNameHint:
        'Необязательно — все строки из файла будут добавлены в аудиторию с этим названием ' +
        '(существующая находится по имени, иначе создаётся новая), чтобы потом их можно было ' +
        'найти и отфильтровать.',
    },
    leads: {
      idleTimeout: 'Таймаут простоя (сек)',
      idleTimeoutPlaceholder: 'Как у агента',
      title: 'Лиды',
      search: 'Поиск',
      searchPlaceholder: 'Телефон или имя',
      status: 'Статус',
      all: 'Все',
      audience: 'Аудитория',
      country: 'Страна',
      language: 'Язык',
      exactMatch: 'Точное совпадение',
      lastActiveFrom: 'Активен с',
      lastActiveTo: 'Активен по',
      noMatch: 'Под фильтры не попал ни один лид.',
      incomplete: 'Неполные данные',
      edit: 'Редактировать',
      editTitle: 'Редактирование лида — {phone}',
      saved: 'Лид успешно обновлен',
      statuses: {
        active: 'Активен',
        do_not_call: 'Не звонить',
        blocked: 'Заблокирован',
      },
      columns: {
        phone: 'Телефон',
        name: 'Имя',
        status: 'Статус',
        audience: 'Аудитория',
        answeredCalls: 'Принято звонков',
        language: 'Язык',
        lastActive: 'Активность',
        country: 'Страна',
        actions: 'Действия',
      },
    },
    callHistory: {
      title: 'История звонков — {phone}',
      noCalls: 'У этого лида пока не было звонков.',
      summary:
        'Попыток дозвона на этот номер: {totalAttempts} (звонков в системе: {total}) · завершено: {completed} · отменено: {canceled} · не отвечено: {noAnswer}',
      columns: {
        when: 'Когда',
        outcome: 'Исход',
        campaign: 'Кампания',
        attempts: 'Попыток',
        duration: 'Длительность (с)',
      },
    },
    manage: {
      button: 'Аудитории',
      title: 'Аудитории',
      noAudiences: 'Аудиторий пока нет.',
      columns: {
        name: 'Название',
        members: 'Участников',
      },
      deleteTitle: 'Удалить «{name}»?',
      deleteWarning:
        'Аудитория и её {count} участник(ов) будут удалены — сами лиды и история их звонков не пострадают, исчезнет только список аудитории.',
    },
    uploadHistory: {
      button: 'История загрузок',
      title: 'История загрузок',
      noUploads: 'Загрузок пока не было.',
      columns: {
        when: 'Когда',
        who: 'Кто',
        filename: 'Файл',
        audience: 'Аудитория',
        total: 'Всего',
        valid: 'Валидных',
        invalid: 'Невалидных',
        leads: 'Лиды',
      },
      user: 'Пользователь #{id}',
      viewLeads: 'Посмотреть лидов',
      notTiedToAudience: 'Не привязано к аудитории — лидов из этой загрузки нельзя выделить отдельно',
      batchTitle: 'Загрузка #{id} — лиды',
      backToHistory: '← К истории загрузок',
      noLeadsForBatch: 'Для этой аудитории лидов не найдено.',
    },
  },
});
