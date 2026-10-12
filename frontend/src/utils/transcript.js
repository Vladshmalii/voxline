// Friendly rendering of a call's tool-call activity, shared by CallsPage's
// attempt transcript and PlaygroundPage's live test (VOAD-58): no raw JSON,
// no system prompt, and every tool call rendered as a short line a
// non-technical reader understands ("Sent an SMS: ...") instead of a
// function name and a JSON blob.
//
// The backend only ever registers two tools today (src/application/engine/
// pipeline.py's send_sms schema, src/application/engine/call_end.py's
// end_call) — see TOOL_CALL_LABELS below. Anything else (a future tool)
// falls back to a humanized name + "key: value" argument list, still never
// a raw JSON dump.

const parseArgs = (raw) => {
  if (raw == null) return {};
  if (typeof raw === 'object') return raw;
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (_) {
    return {};
  }
};

const humanizeToolName = (name) => String(name || '?').replace(/_/g, ' ').trim();

/** One line of text for a completed tool call — `t` is the i18n translate fn. */
export const describeToolCall = (t, name, rawArgs) => {
  const args = parseArgs(rawArgs);
  if (name === 'send_sms') {
    const message = typeof args.message === 'string' ? args.message.trim() : '';
    return message ? t('calls.toolCalls.sendSmsWith', { message }) : t('calls.toolCalls.sendSms');
  }
  if (name === 'end_call') {
    const goodbye = typeof args.goodbye === 'string' ? args.goodbye.trim() : '';
    return goodbye ? t('calls.toolCalls.endCallWith', { goodbye }) : t('calls.toolCalls.endCall');
  }
  const argsText = Object.entries(args)
    .map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`)
    .join(', ');
  const humanized = humanizeToolName(name);
  return argsText
    ? t('calls.toolCalls.unknownWith', { name: humanized, args: argsText })
    : t('calls.toolCalls.unknown', { name: humanized });
};

/** One line of text for a synthetic `{role: "event"}` transcript row. */
const describeEvent = (t, msg) => {
  if (msg?.event === 'language_switched') {
    return t('calls.events.languageSwitched', { from: msg.from, to: msg.to });
  }
  if (msg?.event === 'language_switch_refused') {
    return t('calls.events.languageSwitchRefused', { from: msg.from, to: msg.to });
  }
  return t('calls.events.generic', { event: msg?.event || '?' });
};

/**
 * A stored call attempt's raw OpenAI-shaped `messages` array -> friendly
 * transcript rows: `{ key, role: 'user'|'assistant'|'tool'|'event', text }`.
 *
 * The system-prompt row (always first, `role: "system"`) is dropped
 * entirely — VOAD-58: the configured prompt is never shown to the user, in
 * the playground or in a past call's transcript. A `role: "tool"` row (the
 * function's return value) is consumed by the assistant `tool_calls` row
 * that requested it rather than shown on its own.
 */
export const normalizeMessages = (messages, t) => {
  const out = [];
  (messages || []).forEach((msg, i) => {
    const role = msg?.role;
    if (role === 'system' || role === 'tool') return;

    if (role === 'assistant' && Array.isArray(msg.tool_calls) && msg.tool_calls.length > 0) {
      msg.tool_calls.forEach((call, j) => {
        out.push({
          key: `${i}-${j}`,
          role: 'tool',
          text: describeToolCall(t, call?.function?.name, call?.function?.arguments),
        });
      });
      return;
    }

    if (role === 'event') {
      out.push({ key: i, role: 'event', text: describeEvent(t, msg) });
      return;
    }

    if (typeof msg?.content === 'string' && msg.content.trim() !== '') {
      out.push({ key: i, role: role === 'user' ? 'user' : 'assistant', text: msg.content });
    }
  });
  return out;
};
