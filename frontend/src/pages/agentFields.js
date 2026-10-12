// Field specs for the voice-agent forms (see components/ResourceForm), shared
// by the create modal (AgentsPage), the settings modal (AgentSettingsModal)
// and — the tuning groups — the per-language modal (AgentLanguageModal).
//
// The specs mirror SVoiceAgentCreate/Update and the nested config schemas
// (TurnParams, FragmentParams, ChunkingConfig, VadConfig, SilencePolicy,
// LanguageSwitchPolicy) with the backend's own defaults, so a blank form
// saves exactly what the backend would have defaulted to.
//
// Every field carries a `helpKey` — a "?" popover with the setting's meaning,
// worded after the backend's own docs (src/schemas/engine.py and
// src/models/agent.py of the backend). Keep them in sync.

import { modelFieldsForRole } from '../utils/modelAssignment';
import { formatVoiceLabel, voiceLanguages } from '../utils/voiceCatalog';

/** Models of one pipeline side as select options. */
export const modelOptions = (models, kind) =>
  (models || [])
    .filter((m) => m.kind === kind)
    .map((m) => ({ value: m.id, label: `${m.name} (${m.code})` }));

export const telephonyOptions = (rows) =>
  (rows || []).map((r) => ({ value: r.id, label: `${r.name} (${r.adapter})` }));

export const basicFields = () => [
  {
    name: 'name',
    labelKey: 'agents.fields.name',
    type: 'text',
    required: true,
    helpKey: 'agents.help.name',
  },
  {
    name: 'description',
    labelKey: 'agents.fields.description',
    type: 'textarea',
    rows: 2,
    emptyValue: '',
    helpKey: 'agents.help.description',
  },
  {
    name: 'is_active',
    labelKey: 'agents.fields.isActive',
    type: 'checkbox',
    default: false,
    helpKey: 'agents.help.isActive',
  },
];


// Admin logic: technical settings an administrator sets once per organization
// for ALL its agents (GET/PATCH /agent-settings), as opposed to the client's
// own per-agent fields above. Never part of an agent's create/update payload.
export const adminFields = (telephony) => [
  {
    name: 'idle_timeout_seconds',
    labelKey: 'agents.fields.idleTimeout',
    type: 'number',
    default: 300,
    helpKey: 'agents.help.idleTimeout',
  },
  {
    name: 'max_duration_seconds',
    labelKey: 'agents.fields.maxDurationSeconds',
    type: 'number',
    nullable: true,
    helpKey: 'agents.help.maxDurationSeconds',
  },
  {
    name: 'telephony_id',
    labelKey: 'agents.fields.telephony',
    type: 'select',
    asNumber: true,
    nullable: true,
    emptyLabelKey: 'agents.fields.telephonyEmpty',
    options: telephonyOptions(telephony),
    helpKey: 'agents.help.telephony',
  },
  {
    name: 'tts_sample_rate',
    labelKey: 'agents.fields.ttsSampleRate',
    type: 'number',
    default: 24000,
    helpKey: 'agents.help.ttsSampleRate',
  },
];

// Admin logic, per agent: technical prompt/LLM knobs most users never touch.
// Rendered only for administrators (AgentSettingsModal/AgentsPage), so a
// non-admin form never builds these into its payload and the stored values
// stay as they are.
export const adminTuningFields = () => [
  {
    name: 'call_script',
    labelKey: 'agents.fields.callScript',
    type: 'textarea',
    rows: 5,
    emptyValue: '',
    expandable: true,
    helpKey: 'agents.help.callScript',
  },
  {
    name: 'tts_instructions',
    labelKey: 'agents.fields.ttsInstructions',
    type: 'textarea',
    rows: 2,
    nullable: true,
    helpKey: 'agents.help.ttsInstructions',
  },
  {
    name: 'ttt_temperature',
    labelKey: 'agents.fields.tttTemperature',
    type: 'number',
    nullable: true,
    helpKey: 'agents.help.tttTemperature',
  },
  {
    name: 'ttt_extra_body',
    labelKey: 'agents.fields.tttExtraBody',
    type: 'json',
    default: {},
    rows: 3,
    helpKey: 'agents.help.tttExtraBody',
  },
];

export const promptFields = () => [
  {
    name: 'system_prompt',
    labelKey: 'agents.fields.systemPrompt',
    type: 'textarea',
    rows: 8,
    required: true,
    expandable: true,
    helpKey: 'agents.help.systemPrompt',
  },
  {
    name: 'greeting_kickoff',
    labelKey: 'agents.fields.greetingKickoff',
    type: 'textarea',
    rows: 2,
    emptyValue: '',
    helpKey: 'agents.help.greetingKickoff',
  },
];

export const spokenFields = () => [
  {
    name: 'spoken_silence',
    labelKey: 'agents.fields.spokenSilence',
    type: 'text',
    required: true,
    helpKey: 'agents.help.spokenSilence',
  },
  {
    name: 'spoken_reprompt',
    labelKey: 'agents.fields.spokenReprompt',
    type: 'text',
    required: true,
    helpKey: 'agents.help.spokenReprompt',
  },
  {
    name: 'spoken_goodbye',
    labelKey: 'agents.fields.spokenGoodbye',
    type: 'text',
    required: true,
    helpKey: 'agents.help.spokenGoodbye',
  },
  {
    name: 'spoken_no_answer',
    labelKey: 'agents.fields.spokenNoAnswer',
    type: 'text',
    emptyValue: '',
    helpKey: 'agents.help.spokenNoAnswer',
  },
];

/** Active messaging routes as select options — an inactive route cannot be
 * named as `messaging_id` (the backend would still accept the id, but the
 * route itself refuses to send), so it is left out of the list entirely. */
export const messagingOptions = (routes) =>
  (routes || [])
    .filter((r) => r.is_active)
    .map((r) => ({ value: r.id, label: `${r.name} (#${r.id})` }));

// Flat top-level fields (SVoiceAgentCreate/Update), not a nested JSON config
// group like `turn`/`silence`/`language_switch` — mirrors spoken_feedback_request.
export const smsToolFields = (messaging, canAssign = false) => [
  {
    name: 'sms_tool_enabled',
    labelKey: 'agents.fields.smsToolEnabled',
    type: 'checkbox',
    default: false,
    helpKey: 'agents.help.smsToolEnabled',
  },
  // VOAD-60: the operator writes the exact SMS text; the model only decides
  // whether to send it (always after the call ends, never mid-call, and
  // never when this is still pending moderation — see agents.smsModeration).
  {
    name: 'sms_tool_message',
    labelKey: 'agents.fields.smsToolMessage',
    type: 'textarea',
    rows: 3,
    emptyValue: '',
    placeholderKey: 'agents.fields.smsToolMessagePlaceholder',
    helpKey: 'agents.help.smsToolMessage',
    showIf: (values) => Boolean(values.sms_tool_enabled),
  },
  {
    // null lets the backend pick the organization's one active route; it only
    // errors at send time if there is more than one — see messagingRouteAmbiguous.
    name: 'messaging_id',
    labelKey: 'agents.fields.messagingRoute',
    type: 'select',
    asNumber: true,
    nullable: true,
    emptyLabelKey: 'agents.fields.messagingRouteDefault',
    options: messagingOptions(messaging),
    helpKey: 'agents.help.messagingRoute',
    showIf: (values) => Boolean(values.sms_tool_enabled),
  },
].filter((field) => canAssign || field.name !== 'messaging_id');

/**
 * Options for a `voice`-type field from `modelsApi.voices(id)`'s response,
 * grouped by language (voices with no language known sort last) so a picker
 * with dozens of entries reads as a catalogue, not the vendor's raw order.
 */
export const voiceOptions = (voices) =>
  (voices || [])
    .slice()
    .sort((a, b) => {
      const langA = voiceLanguages(a).join(', ');
      const langB = voiceLanguages(b).join(', ');
      if (langA !== langB) {
        if (!langA) return 1;
        if (!langB) return -1;
        return langA.localeCompare(langB);
      }
      return (a.name || '').localeCompare(b.name || '');
    })
    .map((v) => ({
      value: v.id,
      label: v.name ? formatVoiceLabel(v) : '',
      // Kept alongside label/value so the `voice` field's language filter
      // (ResourceForm) can narrow the picker without re-parsing the label.
      language: v.language || null,
      languages: voiceLanguages(v),
    }));

/**
 * Options for the `stt_language` picker from `modelsApi.languages(id)` — plain
 * codes, so value and label are the same string. Reuses the `voice` field
 * type: free text plus a catalogue that fills it, which is exactly what a
 * language hint wants too (a code the vendor omits stays typable).
 */
export const languageOptions = (codes) =>
  (codes || []).map((code) => ({ value: code, label: code, language: null }));

// `voiceState` — { options, loading } — comes from a `modelsApi.voices(id)`
// fetch keyed on the currently selected `tts_model_id`, kept by the caller
// (AgentsPage/AgentSettingsModal) since it depends on live form values this
// module has no access to. Without a catalogue, admins can still type an ID;
// clients keep the stored selection. `sttLanguageState` is the same thing
// for `stt_language`, from `modelsApi.languages` keyed on
// `stt_model_id` (see src/application/engine/stt_languages.py).
export const modelFields = (models, voiceState, sttLanguageState, canAssign = false) => modelFieldsForRole([
  {
    name: 'stt_model_id',
    labelKey: 'agents.fields.sttModel',
    type: 'select',
    asNumber: true,
    required: true,
    options: modelOptions(models, 'stt'),
    helpKey: 'agents.help.sttModel',
  },
  {
    name: 'stt_language',
    labelKey: 'agents.fields.sttLanguage',
    type: 'voice',
    nullable: true,
    helpKey: 'agents.help.sttLanguage',
    voiceOptions: languageOptions(sttLanguageState?.options),
    voicesLoading: Boolean(sttLanguageState?.loading),
  },
  {
    name: 'tts_model_id',
    labelKey: 'agents.fields.ttsModel',
    type: 'select',
    asNumber: true,
    required: true,
    options: modelOptions(models, 'tts'),
    helpKey: 'agents.help.ttsModel',
  },
  {
    name: 'tts_voice',
    labelKey: 'agents.fields.ttsVoice',
    type: 'voice',
    required: true,
    helpKey: canAssign ? 'agents.help.ttsVoice' : 'agents.help.clientVoice',
    allowCustomVoice: canAssign,
    voiceOptions: voiceOptions(voiceState?.options),
    voicesLoading: Boolean(voiceState?.loading),
  },
  {
    name: 'tts_speed',
    labelKey: 'agents.fields.ttsSpeed',
    type: 'number',
    nullable: true,
    helpKey: 'agents.help.ttsSpeed',
  },
  {
    name: 'ttt_model_id',
    labelKey: 'agents.fields.tttModel',
    type: 'select',
    asNumber: true,
    required: true,
    options: modelOptions(models, 'ttt'),
    helpKey: 'agents.help.tttModel',
  },
  {
    name: 'ttt_top_p',
    labelKey: 'agents.fields.tttTopP',
    type: 'number',
    nullable: true,
    helpKey: 'agents.help.tttTopP',
  },
  {
    name: 'ttt_max_tokens',
    labelKey: 'agents.fields.tttMaxTokens',
    type: 'number',
    nullable: true,
    helpKey: 'agents.help.tttMaxTokens',
  },
  {
    name: 'ttt_enable_thinking',
    labelKey: 'agents.fields.tttEnableThinking',
    type: 'checkbox',
    default: false,
    helpKey: 'agents.help.tttEnableThinking',
  },
], canAssign);

// The nested tuning groups. All nullable: an empty group is saved as null and
// the backend (or, on a language row, the agent) supplies the defaults.

export const turnGroup = () => ({
  name: 'turn',
  labelKey: 'agents.sections.turn',
  helpKey: 'agents.help.turn.section',
  type: 'object',
  nullable: true,
  fields: [
    {
      name: 'analyzer',
      labelKey: 'agents.fields.turn.analyzer',
      type: 'select',
      default: 'smart_turn_v3',
      options: [
        { value: 'smart_turn_v3', label: 'smart_turn_v3' },
        { value: 'none', label: 'none' },
      ],
      helpKey: 'agents.help.turn.analyzer',
    },
    {
      name: 'smart_turn',
      labelKey: 'agents.fields.turn.smartTurn',
      type: 'checkbox',
      default: true,
      helpKey: 'agents.help.turn.smartTurn',
    },
    {
      name: 'min_delay_ms',
      labelKey: 'agents.fields.turn.minDelayMs',
      type: 'number',
      default: 200,
      helpKey: 'agents.help.turn.minDelayMs',
    },
    {
      name: 'max_delay_ms',
      labelKey: 'agents.fields.turn.maxDelayMs',
      type: 'number',
      default: 3000,
      helpKey: 'agents.help.turn.maxDelayMs',
    },
    {
      name: 'repoll_ms',
      labelKey: 'agents.fields.turn.repollMs',
      type: 'number',
      default: 400,
      helpKey: 'agents.help.turn.repollMs',
    },
    {
      name: 'silence_fallback_ms',
      labelKey: 'agents.fields.turn.silenceFallbackMs',
      type: 'number',
      default: 1100,
      helpKey: 'agents.help.turn.silenceFallbackMs',
    },
  ],
});

export const fragmentGroup = () => ({
  name: 'fragment',
  labelKey: 'agents.sections.fragment',
  helpKey: 'agents.help.fragment.section',
  type: 'object',
  nullable: true,
  fields: [
    {
      name: 'min_words',
      labelKey: 'agents.fields.fragment.minWords',
      type: 'number',
      default: 2,
      helpKey: 'agents.help.fragment.minWords',
    },
    {
      name: 'dangling_tokens',
      labelKey: 'agents.fields.fragment.danglingTokens',
      type: 'text',
      asList: true,
      helpKey: 'agents.help.fragment.danglingTokens',
    },
    {
      name: 'complete_short',
      labelKey: 'agents.fields.fragment.completeShort',
      type: 'text',
      asList: true,
      helpKey: 'agents.help.fragment.completeShort',
    },
  ],
});

export const chunkingGroup = () => ({
  name: 'chunking',
  labelKey: 'agents.sections.chunking',
  helpKey: 'agents.help.chunking.section',
  type: 'object',
  nullable: true,
  fields: [
    {
      name: 'mode',
      labelKey: 'agents.fields.chunking.mode',
      type: 'select',
      default: 'clause',
      options: [
        { value: 'clause', labelKey: 'agents.fields.chunkingModes.clause' },
        { value: 'whole_turn', labelKey: 'agents.fields.chunkingModes.whole_turn' },
      ],
      helpKey: 'agents.help.chunking.mode',
    },
    {
      name: 'min_words',
      labelKey: 'agents.fields.chunking.minWords',
      type: 'number',
      default: 8,
      helpKey: 'agents.help.chunking.minWords',
    },
    {
      name: 'max_words',
      labelKey: 'agents.fields.chunking.maxWords',
      type: 'number',
      nullable: true,
      helpKey: 'agents.help.chunking.maxWords',
    },
    {
      name: 'clause_cuts',
      labelKey: 'agents.fields.chunking.clauseCuts',
      type: 'number',
      default: 1,
      helpKey: 'agents.help.chunking.clauseCuts',
    },
    {
      name: 'match_loudness',
      labelKey: 'agents.fields.chunking.matchLoudness',
      type: 'checkbox',
      default: true,
      helpKey: 'agents.help.chunking.matchLoudness',
    },
  ],
});

export const vadGroup = () => ({
  name: 'vad',
  labelKey: 'agents.sections.vad',
  helpKey: 'agents.help.vad.section',
  type: 'object',
  nullable: true,
  fields: [
    {
      name: 'adapter',
      labelKey: 'agents.fields.vad.adapter',
      type: 'select',
      default: 'silero',
      options: [{ value: 'silero', label: 'silero' }],
      helpKey: 'agents.help.vad.adapter',
    },
    {
      name: 'confidence',
      labelKey: 'agents.fields.vad.confidence',
      type: 'number',
      default: 0.7,
      helpKey: 'agents.help.vad.confidence',
    },
    {
      name: 'start_secs',
      labelKey: 'agents.fields.vad.startSecs',
      type: 'number',
      default: 0.2,
      helpKey: 'agents.help.vad.startSecs',
    },
    {
      name: 'stop_secs',
      labelKey: 'agents.fields.vad.stopSecs',
      type: 'number',
      default: 0.2,
      helpKey: 'agents.help.vad.stopSecs',
    },
    {
      name: 'min_volume',
      labelKey: 'agents.fields.vad.minVolume',
      type: 'number',
      default: 0.6,
      helpKey: 'agents.help.vad.minVolume',
    },
  ],
});

// Rendered in AgentSettingsModal's "Silence policy" section. Carries the
// SilencePolicy fields VOAD-27 added on top of the original pair —
// reset_timeout_seconds, feedback_delay_seconds, and max_no_answer_prompts
// (backend src/schemas/engine.py) — plus the spoken_feedback_request
// phrase below is rendered alongside it (it is a VoiceAgent column, not part
// of this JSONB section — see src/models/agent.py).
// max_no_answer_prompts bounds the spoken_no_answer cascade (spokenFields
// above): if that phrase is left empty, this number is unused and a call
// that never gets answered just hangs up silently after reset_timeout_seconds,
// unchanged from before.
export const silenceFeedbackGroup = () => ({
  name: 'silence',
  labelKey: 'agents.sections.silence',
  helpKey: 'agents.help.silence.section',
  type: 'object',
  nullable: true,
  fields: [
    {
      name: 'prompt_seconds',
      labelKey: 'agents.fields.silence.promptSeconds',
      type: 'number',
      default: 9,
      helpKey: 'agents.help.silence.promptSeconds',
    },
    {
      name: 'max_prompts',
      labelKey: 'agents.fields.silence.maxPrompts',
      type: 'number',
      default: 2,
      helpKey: 'agents.help.silence.maxPrompts',
    },
    {
      name: 'reset_timeout_seconds',
      labelKey: 'agents.fields.silence.resetTimeoutSeconds',
      type: 'number',
      default: 20,
      helpKey: 'agents.help.silence.resetTimeoutSeconds',
    },
    {
      name: 'max_no_answer_prompts',
      labelKey: 'agents.fields.silence.maxNoAnswerPrompts',
      type: 'number',
      default: 2,
      helpKey: 'agents.help.silence.maxNoAnswerPrompts',
    },
    {
      name: 'feedback_delay_seconds',
      labelKey: 'agents.fields.silence.feedbackDelaySeconds',
      type: 'number',
      default: 15,
      helpKey: 'agents.help.silence.feedbackDelaySeconds',
    },
  ],
});

/** VOAD-27: the feedback-request phrase — a VoiceAgent column, not part of
 * the silence JSONB section above, but edited right next to it on the
 * Settings page. Jinja template (rendered with the caller's name), same
 * convention as call_script/greeting_kickoff. */
export const spokenFeedbackField = () => [
  {
    name: 'spoken_feedback_request',
    labelKey: 'agents.fields.spokenFeedbackRequest',
    type: 'textarea',
    rows: 2,
    emptyValue: '',
    helpKey: 'agents.help.spokenFeedbackRequest',
  },
];

export const languageSwitchGroup = () => ({
  name: 'language_switch',
  labelKey: 'agents.sections.languageSwitch',
  helpKey: 'agents.help.languageSwitch.section',
  type: 'object',
  nullable: true,
  fields: [
    {
      name: 'enabled',
      labelKey: 'agents.fields.languageSwitch.enabled',
      type: 'checkbox',
      default: false,
      helpKey: 'agents.help.languageSwitch.enabled',
    },
    {
      name: 'confirm_utterances',
      labelKey: 'agents.fields.languageSwitch.confirmUtterances',
      type: 'number',
      default: 2,
      helpKey: 'agents.help.languageSwitch.confirmUtterances',
    },
    {
      name: 'min_utterance_words',
      labelKey: 'agents.fields.languageSwitch.minUtteranceWords',
      type: 'number',
      default: 3,
      helpKey: 'agents.help.languageSwitch.minUtteranceWords',
    },
  ],
});
