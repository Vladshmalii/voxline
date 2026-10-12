import { registerMessages } from '../registry';

// Voice agents: the list tab, the agent workbench (details page), the big
// settings form and the per-language override rows.
//
// The `help` subtree feeds the "?" popovers (components/HelpTip) next to every
// setting. The texts are worded after the backend's own documentation —
// the backend's src/schemas/engine.py, src/models/agent.py and the engine
// modules — keep them in sync rather than improvising.
registerMessages('agents', {
  en: {
    title: 'Voice agents',
    empty: 'No agents yet. Create one and give it prompts, models and a voice.',
    backToAgents: 'Agents',
    settings: 'Settings',
    settingsTitle: 'Agent #{id} — settings',
    settingsSaved: 'Agent saved',
    playground: 'Playground',
    columns: {
      name: 'Name',
      defaultLanguage: 'Language',
      description: 'Description',
      telephony: 'Telephony',
    },
    logic: {
      client: 'Client logic',
      admin: 'Admin logic',
      adminHint: 'Visible and editable by administrators only. Applies to this agent.',
    },
    sections: {
      basic: 'Agent',
      prompts: 'Prompts',
      spoken: 'Spoken lines',
      models: 'Models & voice',
      smsTool: 'SMS tool',
      turn: 'Turn taking',
      fragment: 'Fragments',
      chunking: 'TTS chunking',
      vad: 'Voice activity detection',
      silence: 'Silence policy',
      languageSwitch: 'Language switching',
    },
    fields: {
      name: 'Name',
      description: 'Description',
      isActive: 'Active',
      defaultLanguage: 'Default language',
      greetFirst: 'Greet first',
      idleTimeout: 'Idle timeout (seconds)',
      maxDurationSeconds: 'Max call duration (seconds)',
      telephony: 'Telephony',
      telephonyEmpty: '— none —',
      systemPrompt: 'System prompt',
      callScript: 'Call script',
      greetingKickoff: 'Greeting kickoff',
      spokenSilence: 'On silence',
      spokenReprompt: 'Reprompt',
      spokenGoodbye: 'Goodbye',
      spokenNoAnswer: 'On no answer',
      spokenFeedbackRequest: 'Feedback request phrase',
      sttModel: 'STT model',
      sttLanguage: 'STT language',
      ttsModel: 'TTS model',
      ttsVoice: 'TTS voice',
      currentVoice: 'Current voice (name unavailable)',
      unnamedVoice: 'Unnamed voice',
      voiceAllLanguages: 'All languages',
      ttsSampleRate: 'TTS sample rate',
      ttsSpeed: 'TTS speed',
      ttsInstructions: 'Voice description',
      tttModel: 'LLM model',
      tttTemperature: 'Temperature',
      tttTopP: 'Top-p',
      tttMaxTokens: 'Max tokens',
      tttEnableThinking: 'Enable thinking',
      tttExtraBody: 'Extra body',
      smsToolEnabled: 'Send SMS',
      smsToolMessage: 'Message text',
      smsToolMessagePlaceholder: 'The exact SMS text the agent may send',
      smsToolModerationPending: 'Pending moderation',
      messagingRoute: 'SMS route',
      messagingRouteDefault: 'Default (the organization’s single active route)',
      turn: {
        analyzer: 'Analyzer',
        smartTurn: 'Smart turn',
        minDelayMs: 'Min delay (ms)',
        maxDelayMs: 'Max delay (ms)',
        repollMs: 'Repoll (ms)',
        silenceFallbackMs: 'Silence fallback (ms)',
      },
      fragment: {
        minWords: 'Min words',
        danglingTokens: 'Dangling tokens',
        completeShort: 'Complete short utterances',
      },
      chunking: {
        mode: 'Mode',
        minWords: 'Min words',
        maxWords: 'Max words',
        clauseCuts: 'Clause cuts',
        matchLoudness: 'Match loudness',
      },
      chunkingModes: {
        clause: 'clause — speak while generating',
        whole_turn: 'whole turn — one draw, no drift',
      },
      vad: {
        adapter: 'Adapter',
        confidence: 'Confidence',
        startSecs: 'Start (s)',
        stopSecs: 'Stop (s)',
        minVolume: 'Min volume',
      },
      silence: {
        promptSeconds: 'Prompt after (s)',
        maxPrompts: 'Max prompts',
        resetTimeoutSeconds: 'Reset on full silence after (s)',
        maxNoAnswerPrompts: 'Max no-answer prompts',
        feedbackDelaySeconds: 'Ask for feedback after (s)',
      },
      languageSwitch: {
        enabled: 'Enabled',
        confirmUtterances: 'Confirm utterances',
        minUtteranceWords: 'Min words per utterance',
      },
    },
    help: {
      name: 'Display name of the agent inside the organization — shown in this panel and in call logs.',
      description:
        'Free-form note for operators. Not part of any prompt — it never reaches the model.',
      isActive:
        'Only an active agent may originate calls — the backend refuses to queue a call for an inactive one. The playground does not check this flag, so an inactive agent can still be rehearsed.',
      defaultLanguage:
        'The language a call runs in when it does not name one of its own (e.g. en, de, ru).',
      greetFirst:
        'Speak first instead of waiting for the caller. The engine additionally gates this on the call actually being outbound.',
      idleTimeout:
        'Hang up a call that has produced no audio frames for this long. Guards against a leg that stays open after the far end vanishes. Minimum 10 seconds.',
      maxDurationSeconds:
        'Hard cap on total call length, regardless of activity — distinct from the idle timeout above, which only fires on inactivity. The agent says its goodbye line and ends the call once this is reached, waiting for a quiet moment rather than interrupting an ongoing exchange. Leave empty for no cap.',
      telephony:
        'Which trunk this agent dials out through. May stay empty while the organization’s carrier is not set up yet — readiness reports it, and originating a call is refused until an active binding is set.',
      systemPrompt:
        'The agent’s standing instructions to the LLM — who it is and how it behaves. Write it natively in the agent’s language: a model follows instructions in the language it answers in far more reliably, and a fixed string is prefix-cacheable where a generated one is not.',
      callScript:
        'The scenario of the call — steps, arguments, facts — sent to the LLM as part of the fixed prompt prefix, after the system prompt. Optional; same native-language rule as the system prompt.',
      greetingKickoff:
        'Stands in for the caller’s first turn on an outbound call — it tells the model to open the conversation. Phrase it as a stage direction: anything that reads like dialogue risks the model answering it instead of opening the call.',
      spokenSilence:
        'Spoken when the caller has said nothing for the silence-policy window. A fixed line, not model output: instant, identical every time, and safe to say when the model is unreachable.',
      spokenReprompt:
        'Spoken when the caller’s committed utterance looks unfinished (see Fragments) — the agent asks them to go on instead of answering half a sentence.',
      spokenGoodbye:
        'Spoken right before the agent ends the call — for example after the allowed number of unanswered silence prompts.',
      spokenNoAnswer:
        'Repeated while the caller has picked up but never said a word, in place of the reset-timeout window’s silent hangup. Left empty, the original behaviour applies: the call just ends after the reset timeout, with no line spoken.',
      spokenFeedbackRequest:
        'Spoken instead of the generic reprompt after the configured silence delay following the agent’s last reply — a Jinja template, may use the caller’s name. Empty means the organization has not opted in and this feature stays a no-op.',
      sttModel: 'The speech-to-text model that transcribes the caller. Registered on the Models tab (kind = stt).',
      sttLanguage:
        'Language hint for the recogniser. Sent to backends that accept one, and used to tag frames on those that do not. Blank falls back to the call’s language. When the STT model’s vendor publishes a catalogue (Deepgram), its languages are offered below; “multi” is Deepgram’s multilingual mode — it detects and switches language itself, but is billed higher than a single language. A value set here applies to every language of the agent that has no STT model of its own.',
      ttsModel: 'The text-to-speech model that voices the agent (kind = tts).',
      ttsVoice: 'The voice name, exactly as the TTS service knows it.',
      clientVoice: 'Choose a voice by name and language.',
      clientLanguageVoice: 'Choose a voice by name and language. Blank inherits the agent’s voice.',
      ttsSampleRate:
        'Audio rate (Hz) the TTS service emits. The transport resamples to the leg’s rate; nothing else should.',
      ttsSpeed:
        'Speaking-rate multiplier passed to the TTS service. Blank sends nothing and the server’s default stands.',
      ttsInstructions:
        'Style and delivery instructions passed to the TTS service, for backends that accept them. Blank sends nothing.',
      tttModel: 'The LLM that writes the agent’s replies (kind = ttt).',
      tttTemperature: 'Sampling temperature for the LLM. Blank sends nothing — the server’s default stands.',
      tttTopP: 'Nucleus-sampling cutoff for the LLM. Blank sends nothing — the server’s default stands.',
      tttMaxTokens: 'Cap on tokens per reply. Blank sends nothing — the server’s default stands.',
      tttEnableThinking:
        'Whether a reasoning model may “think” before answering. Off by default: reasoning models think by default, and a phone call cannot wait for it.',
      tttExtraBody: 'Escape hatch: free-form JSON merged into every LLM request’s extra_body.',
      smsToolEnabled:
        'Lets the agent send the message below to the caller’s own number only — there is no field for another number, the backend will not accept one. The model decides *whether* it fits the conversation; the text itself is fixed and always goes out after the call ends, never mid-call. Off by default.',
      smsToolMessage:
        'The exact text that will be sent — the model never composes or edits it, only decides whether to send it. Text written or changed by staff needs an owner/admin to approve it before it can ever be sent (shown as “Pending moderation” until then).',
      messagingRoute:
        'Which SMS route the SMS tool sends through. Left blank, the backend picks the organization’s one active route automatically.',
      messagingRouteAmbiguous:
        'The organization has more than one active SMS route — leaving this blank will make sending fail (“several active messaging routes; name one with messaging_id”). Pick a route explicitly.',
      turn: {
        section:
          'When a pause becomes the caller’s turn ending. The cascade: below the min delay the caller is almost certainly mid-breath; between min and max the analyzer is asked every repoll interval; at the max delay the turn commits regardless.',
        analyzer:
          'The end-of-turn classifier that judges whether the caller has finished rather than merely paused. smart_turn_v3 runs in-process on CPU; “none” relies on the silence fallback alone.',
        smartTurn:
          'Whether to consult the analyzer at all. Off drops to the silence fallback, which is the honest setting for a language the analyzer was never trained on.',
        minDelayMs:
          'Below this pause length the caller is almost certainly mid-breath, and an analyzer inference would be wasted.',
        maxDelayMs:
          'Hard ceiling: the turn commits this long after speech ends, no matter what the analyzer says. It is what stops a caller who trails off from being ignored. Must not be below the min delay.',
        repollMs: 'How often the analyzer is re-asked while waiting between min and max delay. Must be positive.',
        silenceFallbackMs: 'Used only when smart turn is off: commit the turn this long after speech ends.',
      },
      fragment: {
        section:
          'What a turn committed at the max delay may send to the LLM. Such an utterance may be half a sentence, and answering half a sentence is worse than asking the caller to go on — so a commit that looks unfinished gets the reprompt line instead.',
        minWords:
          'An utterance with fewer words than this looks unfinished — unless one of its words is in the complete-short list.',
        danglingTokens:
          'Ending on one of these words means the caller was still assembling the sentence — conjunctions, articles, prepositions, fillers (“and”, “my”, “um”). Comma-separated.',
        completeShort:
          'Short utterances that are nonetheless whole turns: “yes”, “no”, “hello”. Comma-separated.',
      },
      chunking: {
        section:
          'How the reply is cut on its way to TTS. Each chunk is a separate synthesis request, and each request is an independent draw of the speaker — so chunk count trades time-to-first-audio against how much the voice can drift inside one answer.',
        mode:
          '“clause” speaks the first clause while the model is still generating — this is what keeps time-to-first-audio under a second. “whole turn” waits for the complete reply and synthesises it in one request: one draw of the speaker, no drift mid-answer, paid for in latency.',
        minWords:
          'Words that must accumulate before a clause boundary (comma, semicolon, colon, dash) is allowed to cut a chunk. Sentence endings always cut.',
        maxWords:
          'Hard ceiling: a run-on with no punctuation at all would otherwise never flush. Blank defaults to 2.5 × min words.',
        clauseCuts:
          'How many chunks per turn may be cut at a clause instead of running to a sentence end — only the chunks on the latency path need it.',
        matchLoudness:
          'Scale every chunk after the first to the loudness of the first, so the level cannot jump between synthesis requests. Costs nothing on the path to first audio.',
      },
      vad: {
        section:
          'Voice activity detection: is there speech in this frame? Runs in-process on every frame. It opens the recogniser’s gate and starts the turn controller’s clock — whether a pause ends the turn is decided by Turn taking, not here.',
        adapter: 'The detector. Silero runs in-process on CPU and opens no connection.',
        confidence: 'Minimum speech probability for a frame to count as speech.',
        startSecs: 'How long speech must persist before a start is reported.',
        stopSecs:
          'Speech-to-silence gap before the VAD reports a stop. The turn controller decides what that stop means.',
        minVolume: 'Minimum audio level for a frame to count as speech.',
      },
      silence: {
        section:
          'How long to tolerate a caller saying nothing, and what to do about it. A crude backstop for voicemail or a handset put down — not answering-machine detection. Without it such a call would hold the leg open until the provider’s timeout, minutes later.',
        promptSeconds: 'Silence with neither party speaking before the agent says its “on silence” line.',
        maxPrompts:
          'Unanswered prompts before the agent says goodbye and ends the call. Any speech from the caller resets the counter.',
        resetTimeoutSeconds:
          'How long the caller may stay silent — counted from connect, or from the end of the agent\'s own last turn, whichever is later — before repeating the "on no answer" line below (or, if that phrase is empty, ending the call outright with no goodbye: voicemail, dead air, a handset put down). The agent\'s own speech never resets this: with the agent greeting first, only the caller actually answering counts. A different, usually shorter, threshold than the mid-conversation prompt above.',
        maxNoAnswerPrompts:
          'Unanswered "on no answer" prompts before giving up and hanging up (no goodbye — nobody has ever answered to say it to). Unused while the "on no answer" phrase is left empty.',
        feedbackDelaySeconds:
          'Silence for this long after the agent’s last reply speaks the feedback-request phrase below instead of the generic reprompt, once, before falling back to the normal reprompt/goodbye cascade.',
      },
      languageSwitch: {
        section:
          'Whether a caller’s detected language may retarget a live call. Off by default: a switch rewrites the prompt layers, which burns the prefix cache once. Only languages configured on the agent (or its default) are candidates, and the recogniser must report a detected language for the mechanism to work at all.',
        enabled: 'Allow a live call to switch language when the caller demonstrably speaks another configured one.',
        confirmUtterances:
          'Consecutive qualifying utterances that must agree before the switch commits — one borrowed sentence must not flip the call. Minimum 1.',
        minUtteranceWords:
          'Utterances shorter than this many words count neither for nor against a pending switch: one-word answers (“ja”, “no”, “okay”) are exactly where language detection is noisiest. Minimum 1.',
      },
      languages: {
        language: 'Language code, the way callers send it — e.g. “de”, “pt-br”. One row per language per agent.',
        voice: 'TTS voice for this language. Blank inherits the agent’s voice.',
        prompts:
          'Replaces the agent’s prompt set whole for this language — system prompt, call script and greeting kickoff together. Written natively in the language, not translated at runtime.',
        spoken: 'Localised spoken lines. Replaces the agent’s trio whole — set all three or none.',
        model:
          'A different backend for this language — e.g. the recogniser that actually covers it. Blank inherits the agent’s model; if the override’s model is ever deleted, the row falls back to the agent’s default.',
        sttParams:
          'JSON parameters accompanying an overridden recogniser. Accepted key: "language" (hint; defaults to this row’s language). Applied only when this row overrides the STT model.',
        ttsParams:
          'JSON parameters accompanying an overridden TTS: "voice", "sample_rate", "speed", "instructions". Applied only when this row overrides the TTS model.',
        tttParams:
          'JSON parameters accompanying an overridden LLM: "temperature", "top_p", "max_tokens", "enable_thinking", "extra_body". Applied only when this row overrides the LLM.',
      },
    },
    info: {
      updated: 'Updated',
    },
    voiceTest: {
      section: 'Voice test',
      language: 'Language',
      defaultOption: 'Default ({language})',
      text: 'Custom phrase',
      textPlaceholder: 'Type a phrase to synthesize (optional)…',
      play: 'Play',
      stop: 'Stop',
      synthesizing: 'Synthesizing…',
    },
    testVoicesBtn: 'Test voices',
    catalog: {
      title: 'Voice Catalog & Testing',
      subtitle: 'Voices available from your configured speech models. Listen to any voice and copy its Voice ID for the agent settings.',
      clientSubtitle: 'Listen to the available voices, then choose a voice by name and language in the agent settings.',
      clientSearchPlaceholder: 'Search by voice name or language…',
      clientNoVoices: 'No voices available yet. Contact the project administrator.',
      allModels: 'All models',
      allLanguages: 'All languages',
      refresh: 'Refresh voices',
      loading: 'Loading voices…',
      loadError: 'Could not load all voices. Try refreshing the catalogue.',
      noModels: 'No TTS model assigned. Contact the project administrator.',
      playbackError: 'Could not play this voice.',
      searchPlaceholder: 'Search by voice name, model or Voice ID…',
      allProviders: 'All providers',
      allGenders: 'Any gender',
      genderMale: 'Male',
      genderFemale: 'Female',
      testPhraseLabel: 'Test phrase (supports {name} placeholder)',
      resetPhrase: 'Reset phrase',
      filterCount: 'Showing {count} voices',
      columns: {
        provider: 'Provider / Model',
        name: 'Voice Name',
        gender: 'Gender',
        voiceId: 'Voice ID',
        character: 'Character / Timbre',
        languages: 'Languages',
        actions: 'Test',
      },
      copySuccess: 'Voice ID copied to clipboard!',
      copyTooltip: 'Click to copy Voice ID',
      recommended: 'Recommended',
      play: 'Play',
      stop: 'Stop',
      synthesizing: 'Synthesizing…',
      noResults: 'No voices match the filter criteria.',
    },
    languages: {
      section: 'Languages',
      hint: 'Per-language overrides. Every field left blank falls back to the agent’s defaults above.',
      add: 'Add language',
      addTitle: 'Add language',
      editTitle: 'Language “{language}”',
      deleteTitle: 'Remove language “{language}”?',
      empty: 'No language rows yet — every call runs on the agent’s defaults.',
      columns: {
        language: 'Language',
        voice: 'Voice',
        overrides: 'Overrides',
      },
      none: '— inherited —',
      saved: 'Language saved',
      deleted: 'Language removed',
      fields: {
        language: 'Language',
        voice: 'Voice',
        systemPrompt: 'System prompt',
        callScript: 'Call script',
        greetingKickoff: 'Greeting kickoff',
        sttModel: 'STT model',
        ttsModel: 'TTS model',
        tttModel: 'LLM model',
        sttParams: 'STT params',
        ttsParams: 'TTS params',
        tttParams: 'LLM params',
      },
    },
    // VOAD-62: the moderation queue — owner/admin/super_admin review staff-
    // authored SMS-tool text before it can ever be sent.
    smsModeration: {
      title: 'SMS moderation',
      empty: 'Nothing pending moderation.',
      columns: {
        agent: 'Agent',
        message: 'Message',
      },
      approve: 'Approve',
      reject: 'Reject',
      approved: 'Approved',
      rejected: 'Rejected — text cleared',
      confirmReject: 'Reject this text? It will be cleared, and the agent’s SMS tool will have nothing to send until staff writes a new message.',
    },
  },
  ru: {
    title: 'Голосовые агенты',
    empty: 'Агентов пока нет. Создайте агента и задайте ему промпты, модели и голос.',
    backToAgents: 'Агенты',
    settings: 'Настройки',
    settingsTitle: 'Агент #{id} — настройки',
    settingsSaved: 'Агент сохранён',
    playground: 'Плейграунд',
    columns: {
      name: 'Название',
      defaultLanguage: 'Язык',
      description: 'Описание',
      telephony: 'Телефония',
    },
    logic: {
      client: 'Клиентская логика',
      admin: 'Админская логика',
      adminHint: 'Видно и доступно для изменения только администратору. Относится к этому агенту.',
    },
    sections: {
      basic: 'Агент',
      prompts: 'Промпты',
      spoken: 'Готовые реплики',
      models: 'Модели и голос',
      turn: 'Смена реплик',
      fragment: 'Фрагменты',
      chunking: 'Нарезка TTS',
      vad: 'Детекция речи (VAD)',
      silence: 'Политика тишины',
      languageSwitch: 'Переключение языка',
      smsTool: 'SMS-тул',
    },
    fields: {
      name: 'Название',
      description: 'Описание',
      isActive: 'Активен',
      defaultLanguage: 'Язык по умолчанию',
      greetFirst: 'Здоровается первым',
      idleTimeout: 'Таймаут простоя (сек)',
      maxDurationSeconds: 'Макс. длительность звонка (сек)',
      telephony: 'Телефония',
      telephonyEmpty: '— нет —',
      systemPrompt: 'Системный промпт',
      callScript: 'Скрипт звонка',
      greetingKickoff: 'Запуск приветствия',
      spokenSilence: 'При тишине',
      spokenReprompt: 'Переспрос',
      spokenGoodbye: 'Прощание',
      spokenNoAnswer: 'При недозвоне',
      spokenFeedbackRequest: 'Фраза запроса обратной связи',
      sttModel: 'Модель STT',
      sttLanguage: 'Язык STT',
      ttsModel: 'Модель TTS',
      ttsVoice: 'Голос TTS',
      currentVoice: 'Текущий голос (название недоступно)',
      unnamedVoice: 'Голос без названия',
      voiceAllLanguages: 'Все языки',
      ttsSampleRate: 'Частота TTS',
      ttsSpeed: 'Скорость TTS',
      ttsInstructions: 'Описание голоса',
      tttModel: 'Модель LLM',
      tttTemperature: 'Температура',
      tttTopP: 'Top-p',
      tttMaxTokens: 'Макс. токенов',
      tttEnableThinking: 'Включить размышление',
      tttExtraBody: 'Extra body',
      smsToolEnabled: 'Отправлять SMS',
      smsToolMessage: 'Текст сообщения',
      smsToolMessagePlaceholder: 'Точный текст SMS, который может отправить агент',
      smsToolModerationPending: 'На модерации',
      messagingRoute: 'SMS-маршрут',
      messagingRouteDefault: 'По умолчанию (единственный активный маршрут)',
      turn: {
        analyzer: 'Анализатор',
        smartTurn: 'Smart turn',
        minDelayMs: 'Мин. задержка (мс)',
        maxDelayMs: 'Макс. задержка (мс)',
        repollMs: 'Повторный опрос (мс)',
        silenceFallbackMs: 'Фолбэк тишины (мс)',
      },
      fragment: {
        minWords: 'Мин. слов',
        danglingTokens: 'Висячие токены',
        completeShort: 'Полные короткие фразы',
      },
      chunking: {
        mode: 'Режим',
        minWords: 'Мин. слов',
        maxWords: 'Макс. слов',
        clauseCuts: 'Разрезы по клаузам',
        matchLoudness: 'Выравнивать громкость',
      },
      chunkingModes: {
        clause: 'clause — говорить во время генерации',
        whole_turn: 'whole turn — одна выборка, без дрейфа',
      },
      vad: {
        adapter: 'Адаптер',
        confidence: 'Уверенность',
        startSecs: 'Старт (с)',
        stopSecs: 'Стоп (с)',
        minVolume: 'Мин. громкость',
      },
      silence: {
        promptSeconds: 'Напомнить через (с)',
        maxPrompts: 'Макс. напоминаний',
        resetTimeoutSeconds: 'Сброс при полной тишине через (с)',
        maxNoAnswerPrompts: 'Макс. попыток при недозвоне',
        feedbackDelaySeconds: 'Запрос обратной связи через (с)',
      },
      languageSwitch: {
        enabled: 'Включено',
        confirmUtterances: 'Реплик для подтверждения',
        minUtteranceWords: 'Мин. слов в реплике',
      },
    },
    help: {
      name: 'Отображаемое имя агента внутри организации — видно в панели и в логах звонков.',
      description:
        'Произвольная заметка для операторов. Не входит ни в один промпт — модель её не видит.',
      isActive:
        'Создавать звонки может только активный агент — бэкенд откажется ставить звонок неактивного в очередь. Плейграунд этот флаг не проверяет, так что неактивного агента можно репетировать.',
      defaultLanguage:
        'Язык, на котором идёт звонок, если у него не задан собственный (например en, de, ru).',
      greetFirst:
        'Говорить первым, не дожидаясь абонента. Движок дополнительно требует, чтобы звонок действительно был исходящим.',
      idleTimeout:
        'Повесить трубку, если звонок столько времени не производит ни одного аудиокадра. Защита от «зависшего» плеча, когда собеседник исчез. Минимум 10 секунд.',
      maxDurationSeconds:
        'Жёсткое ограничение общей длительности звонка, независимо от активности — в отличие от таймаута простоя выше, который срабатывает только при бездействии. По достижении лимита агент произносит фразу прощания и завершает звонок, дождавшись паузы, а не перебивая разговор. Оставьте пустым, чтобы не ограничивать.',
      telephony:
        'Через какой транк агент звонит. Можно оставить пустым, пока оператор связи организации не настроен — это покажет проверка готовности, а создание звонка будет отклоняться, пока не задана активная привязка.',
      systemPrompt:
        'Постоянные инструкции агента для LLM — кто он и как себя ведёт. Пишите сразу на языке агента: модель заметно надёжнее следует инструкции на языке ответа, а фиксированная строка кэшируется префиксом, в отличие от генерируемой.',
      callScript:
        'Сценарий звонка — шаги, аргументы, факты. Отправляется LLM как часть фиксированного префикса промпта после системного промпта. Необязателен; то же правило родного языка, что и у системного промпта.',
      greetingKickoff:
        'Заменяет первую реплику абонента в исходящем звонке — говорит модели открыть разговор. Формулируйте как сценическую ремарку: всё, что читается как реплика диалога, модель рискует принять за вопрос и ответить на него вместо приветствия.',
      spokenSilence:
        'Произносится, когда абонент молчит дольше окна политики тишины. Фиксированная строка, не вывод модели: мгновенная, всегда одинаковая и безопасная, даже когда модель недоступна.',
      spokenReprompt:
        'Произносится, когда зафиксированная реплика абонента выглядит незаконченной (см. «Фрагменты») — агент просит продолжить вместо того, чтобы отвечать на полфразы.',
      spokenGoodbye:
        'Произносится перед тем, как агент завершает звонок — например, после исчерпания напоминаний о тишине.',
      spokenNoAnswer:
        'Повторяется, пока абонент взял трубку, но так и не сказал ни слова — вместо молчаливого завершения звонка по истечении таймаута сброса. Если оставить пустым, сохраняется прежнее поведение: звонок просто завершается по истечении таймаута сброса, без произнесения фразы.',
      spokenFeedbackRequest:
        'Произносится вместо обычного переспроса после настроенной задержки тишины после последней реплики агента — шаблон Jinja, может использовать имя абонента. Пусто — организация не подключила эту функцию, и она остаётся no-op.',
      sttModel: 'Модель распознавания речи, транскрибирующая абонента. Регистрируется на вкладке «Модели» (тип stt).',
      sttLanguage:
        'Языковая подсказка распознавателю. Отправляется бэкендам, которые её принимают, и используется для маркировки кадров у остальных. Пустое — язык звонка. Если провайдер STT-модели публикует каталог (Deepgram), его языки предлагаются ниже; «multi» — мультиязычный режим Deepgram: сам определяет и переключает язык, но тарифицируется дороже одного языка. Заданное здесь значение действует для всех языков агента, у которых нет своей STT-модели.',
      ttsModel: 'Модель синтеза речи, озвучивающая агента (тип tts).',
      ttsVoice: 'Имя голоса ровно в том виде, в каком его знает TTS-сервис.',
      clientVoice: 'Выберите голос по названию и языку.',
      clientLanguageVoice: 'Выберите голос по названию и языку. Пустое — наследуется голос агента.',
      ttsSampleRate:
        'Частота (Гц), с которой TTS-сервис отдаёт аудио. Транспорт ресемплирует под канал; больше никто не должен.',
      ttsSpeed:
        'Множитель скорости речи, передаётся TTS-сервису. Пустое — ничего не отправляется, действует значение сервера.',
      ttsInstructions:
        'Инструкции по стилю и подаче для TTS-сервисов, которые их принимают. Пустое — ничего не отправляется.',
      tttModel: 'LLM, которая пишет реплики агента (тип ttt).',
      tttTemperature: 'Температура сэмплирования LLM. Пустое — ничего не отправляется, действует значение сервера.',
      tttTopP: 'Порог nucleus-сэмплирования LLM. Пустое — ничего не отправляется, действует значение сервера.',
      tttMaxTokens: 'Потолок токенов на ответ. Пустое — ничего не отправляется, действует значение сервера.',
      tttEnableThinking:
        'Может ли рассуждающая модель «думать» перед ответом. По умолчанию выключено: такие модели думают по умолчанию, а телефонный звонок этого ждать не может.',
      tttExtraBody: 'Запасной выход: произвольный JSON, подмешиваемый в extra_body каждого запроса к LLM.',
      smsToolEnabled:
        'Разрешает агенту отправить текст ниже — только на номер текущего абонента, поля для другого номера нет, бэкенд его и не примет. Модель решает, подходит ли момент по разговору; сам текст фиксирован и всегда уходит уже после завершения звонка, а не во время него. По умолчанию выключено.',
      smsToolMessage:
        'Точный текст, который будет отправлен — модель его не сочиняет и не меняет, только решает, отправлять ли. Текст, созданный или изменённый staff, требует подтверждения owner/admin, прежде чем его вообще можно будет отправить (до тех пор показывается статус «На модерации»).',
      messagingRoute:
        'Через какой SMS-маршрут SMS-тул отправляет сообщения. Пусто — бэкенд сам возьмёт единственный активный маршрут организации.',
      messagingRouteAmbiguous:
        'У организации больше одного активного SMS-маршрута — если оставить поле пустым, отправка будет падать с ошибкой «several active messaging routes; name one with messaging_id». Выберите маршрут явно.',
      turn: {
        section:
          'Когда пауза означает конец реплики абонента. Каскад: до минимальной задержки абонент почти наверняка переводит дыхание; между минимумом и максимумом анализатор опрашивается с заданным интервалом; на максимуме ход фиксируется в любом случае.',
        analyzer:
          'Классификатор конца реплики — закончил абонент или лишь запнулся. smart_turn_v3 работает локально на CPU; «none» полагается только на фолбэк тишины.',
        smartTurn:
          'Опрашивать ли анализатор вообще. Выключено — срабатывает фолбэк тишины; это честная настройка для языка, на котором анализатор не обучался.',
        minDelayMs:
          'Пауза короче этой почти наверняка означает вдох посреди фразы — вызов анализатора был бы потрачен зря.',
        maxDelayMs:
          'Жёсткий потолок: ход фиксируется через столько после конца речи, что бы ни говорил анализатор. Именно он не даёт игнорировать абонента, который «затих на полуслове». Не должен быть меньше минимальной задержки.',
        repollMs: 'Как часто переспрашивать анализатор в ожидании между минимумом и максимумом. Должен быть положительным.',
        silenceFallbackMs: 'Используется только при выключенном smart turn: фиксировать ход через столько после конца речи.',
      },
      fragment: {
        section:
          'Что зафиксированный по потолку ход может отправить LLM. Обрезанная на максимальной задержке реплика может быть полфразы, а отвечать на полфразы хуже, чем попросить продолжить, — поэтому «незаконченный» коммит получает реплику-переспрос.',
        minWords:
          'Реплика короче этого числа слов выглядит незаконченной — если ни одно из её слов не входит в список полных коротких фраз.',
        danglingTokens:
          'Окончание на одном из этих слов означает, что абонент ещё собирал фразу, — союзы, артикли, предлоги, заполнители («и», «моей», «эм»). Через запятую.',
        completeShort: 'Короткие реплики, которые тем не менее — целый ход: «да», «нет», «алло». Через запятую.',
      },
      chunking: {
        section:
          'Как ответ режется на пути в TTS. Каждый кусок — отдельный запрос синтеза и независимая выборка диктора, так что число кусков — компромисс между временем до первого звука и тем, насколько голос может «поплыть» внутри одного ответа.',
        mode:
          '«clause» проговаривает первую клаузу, пока модель ещё генерирует, — именно это удерживает время до первого звука меньше секунды. «whole turn» ждёт весь ответ и синтезирует его одним запросом: одна выборка диктора, никакого дрейфа в середине ответа, ценой задержки.',
        minWords:
          'Сколько слов должно накопиться, прежде чем граница клаузы (запятая, точка с запятой, двоеточие, тире) может отрезать кусок. Конец предложения режет всегда.',
        maxWords:
          'Жёсткий потолок: длинная фраза вовсе без пунктуации иначе никогда не отправилась бы. Пустое — 2,5 × мин. слов.',
        clauseCuts:
          'Сколько кусков за ход можно отрезать по клаузе, не дожидаясь конца предложения, — это нужно только кускам на пути задержки.',
        matchLoudness:
          'Подгонять громкость каждого следующего куска под первый, чтобы уровень не скакал между запросами синтеза. Ничего не стоит на пути к первому звуку.',
      },
      vad: {
        section:
          'Детекция голосовой активности: есть ли речь в этом кадре? Работает локально на каждом кадре. Открывает «ворота» распознавателя и запускает часы контроллера ходов — а решает, закончила ли пауза реплику, «Смена реплик», не VAD.',
        adapter: 'Детектор. Silero работает локально на CPU и не открывает соединений.',
        confidence: 'Минимальная вероятность речи, чтобы кадр считался речью.',
        startSecs: 'Сколько речь должна длиться, прежде чем будет зафиксировано её начало.',
        stopSecs:
          'Пауза после речи, после которой VAD сообщает об остановке. Что эта остановка означает — решает контроллер ходов.',
        minVolume: 'Минимальная громкость, чтобы кадр считался речью.',
      },
      silence: {
        section:
          'Сколько терпеть молчание абонента и что с ним делать. Грубая подстраховка на случай автоответчика или отложенной трубки — это не детекция автоответчика. Без неё такой звонок держал бы канал открытым до таймаута провайдера, то есть минуты.',
        promptSeconds: 'Сколько секунд обоюдной тишины до того, как агент произнесёт реплику «при тишине».',
        maxPrompts:
          'Сколько напоминаний без ответа до того, как агент попрощается и завершит звонок. Любая речь абонента сбрасывает счётчик.',
        resetTimeoutSeconds:
          'Сколько абонент может молчать — отсчёт от соединения или от конца последней реплики агента (что наступит позже) — прежде чем повторится фраза «при недозвоне» ниже (а если она пустая — звонок завершится сразу, без прощания: автоответчик, мёртвая линия, брошенная трубка). Собственная речь агента этот таймер не сбрасывает: раз агент говорит первым, засчитывается только реальный ответ абонента. Отдельный, обычно более короткий порог, чем переспрос посреди разговора выше.',
        maxNoAnswerPrompts:
          'Сколько раз повторить фразу «при недозвоне» без ответа, прежде чем сдаться и положить трубку (без прощания — отвечать некому). Не используется, пока фраза «при недозвоне» не задана.',
        feedbackDelaySeconds:
          'Тишина столько времени после последней реплики агента — вместо обычного переспроса агент один раз произносит фразу запроса обратной связи (см. ниже), и только потом возвращается к обычному сценарию переспроса/прощания.',
      },
      languageSwitch: {
        section:
          'Может ли определённый у абонента язык перенацелить живой звонок. По умолчанию выключено: переключение переписывает слои промпта и один раз сжигает префиксный кэш. Кандидаты — только настроенные у агента языки (или его язык по умолчанию), и распознаватель должен вообще сообщать определённый язык.',
        enabled: 'Разрешить живому звонку сменить язык, когда абонент явно говорит на другом настроенном.',
        confirmUtterances:
          'Сколько подряд подходящих реплик должны совпасть, прежде чем переключение сработает, — одна заимствованная фраза не должна перевернуть звонок. Минимум 1.',
        minUtteranceWords:
          'Реплики короче этого числа слов не считаются ни за, ни против переключения: односложные ответы («ja», «no», «okay») — ровно то место, где детекция языка шумит сильнее всего. Минимум 1.',
      },
      languages: {
        language: 'Код языка в том виде, в каком его присылают звонки, — например «de», «pt-br». Одна строка на язык на агента.',
        voice: 'Голос TTS для этого языка. Пустое — наследуется голос агента.',
        prompts:
          'Целиком заменяет промпты агента для этого языка — системный промпт, скрипт и запуск приветствия вместе. Пишутся сразу на языке, а не переводятся на лету.',
        spoken: 'Локализованные готовые реплики. Заменяют тройку агента целиком — задайте все три или ни одной.',
        model:
          'Другой бэкенд для этого языка — например распознаватель, который его действительно покрывает. Пустое — наследуется модель агента; если модель переопределения удалят, строка вернётся к настройке агента.',
        sttParams:
          'JSON-параметры к переопределённому распознавателю. Ключ: "language" (подсказка; по умолчанию язык этой строки). Применяются, только если строка переопределяет модель STT.',
        ttsParams:
          'JSON-параметры к переопределённому TTS: "voice", "sample_rate", "speed", "instructions". Применяются, только если строка переопределяет модель TTS.',
        tttParams:
          'JSON-параметры к переопределённой LLM: "temperature", "top_p", "max_tokens", "enable_thinking", "extra_body". Применяются, только если строка переопределяет LLM.',
      },
    },
    info: {
      updated: 'Обновлён',
    },
    voiceTest: {
      section: 'Тест голоса',
      language: 'Язык',
      defaultOption: 'По умолчанию ({language})',
      text: 'Своя фраза',
      textPlaceholder: 'Введите фразу для синтеза (необязательно)…',
      play: 'Воспроизвести',
      stop: 'Остановить',
      synthesizing: 'Генерация…',
    },
    testVoicesBtn: 'Тест голосов',
    catalog: {
      title: 'Каталог и тест голосов',
      subtitle: 'Доступные голоса настроенных моделей синтеза речи. Прослушайте любой голос и скопируйте его Voice ID в настройки агента.',
      clientSubtitle: 'Прослушайте доступные голоса, затем выберите голос по названию и языку в настройках агента.',
      clientSearchPlaceholder: 'Поиск по названию голоса или языку…',
      clientNoVoices: 'Доступных голосов пока нет. Обратитесь к администратору проекта.',
      allModels: 'Все модели',
      allLanguages: 'Все языки',
      refresh: 'Обновить голоса',
      loading: 'Загрузка голосов…',
      loadError: 'Не удалось загрузить все голоса. Попробуйте обновить каталог.',
      noModels: 'Модель TTS не назначена. Обратитесь к администратору проекта.',
      playbackError: 'Не удалось воспроизвести голос.',
      searchPlaceholder: 'Поиск по имени голоса, модели или Voice ID…',
      allProviders: 'Все провайдеры',
      allGenders: 'Любой пол',
      genderMale: 'Мужской',
      genderFemale: 'Женский',
      testPhraseLabel: 'Фраза для теста (поддерживает подстановку {name})',
      resetPhrase: 'Сбросить фразу',
      filterCount: 'Найдено голосов: {count}',
      columns: {
        provider: 'Провайдер / Модель',
        name: 'Имя голоса',
        gender: 'Пол',
        voiceId: 'Voice ID',
        character: 'Характер / Тембр',
        languages: 'Языки',
        actions: 'Тест',
      },
      copySuccess: 'Voice ID скопирован в буфер обмена!',
      copyTooltip: 'Нажмите, чтобы скопировать Voice ID',
      recommended: 'Рекомендуемый',
      play: 'Слушать',
      stop: 'Стоп',
      synthesizing: 'Генерация…',
      noResults: 'По выбранным фильтрам голоса не найдены.',
    },
    languages: {
      section: 'Языки',
      hint: 'Переопределения на язык. Каждое пустое поле наследует настройки агента выше.',
      add: 'Добавить язык',
      addTitle: 'Добавить язык',
      editTitle: 'Язык «{language}»',
      deleteTitle: 'Удалить язык «{language}»?',
      empty: 'Языковых строк нет — все звонки идут на настройках агента.',
      columns: {
        language: 'Язык',
        voice: 'Голос',
        overrides: 'Переопределения',
      },
      none: '— наследуется —',
      saved: 'Язык сохранён',
      deleted: 'Язык удалён',
      fields: {
        language: 'Язык',
        voice: 'Голос',
        systemPrompt: 'Системный промпт',
        callScript: 'Скрипт звонка',
        greetingKickoff: 'Запуск приветствия',
        sttModel: 'Модель STT',
        ttsModel: 'Модель TTS',
        tttModel: 'Модель LLM',
        sttParams: 'Параметры STT',
        ttsParams: 'Параметры TTS',
        tttParams: 'Параметры LLM',
      },
    },
    smsModeration: {
      title: 'Модерация SMS',
      empty: 'Нет текстов на модерации.',
      columns: {
        agent: 'Агент',
        message: 'Текст',
      },
      approve: 'Одобрить',
      reject: 'Отклонить',
      approved: 'Одобрено',
      rejected: 'Отклонено — текст очищен',
      confirmReject: 'Отклонить этот текст? Он будет очищен, и SMS-тулу агента будет нечего отправлять, пока staff не напишет новый текст.',
    },
  },
});
