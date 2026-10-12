import { useState } from 'react';
import { FiMaximize2, FiMinimize2 } from 'react-icons/fi';
import styled from 'styled-components';
import { useTheme } from 'contexts/ThemeContext';
import { useI18n } from 'contexts/I18nContext';
import { resolveText } from 'i18n';
import { HelpTip } from 'components/HelpTip';
import {
  TextInput,
  Select,
  TextArea,
  FieldLabel,
  FieldGroup,
  FieldHint,
  CheckboxLabel,
} from 'components/ui';

// Field spec:
//   { name, label, type: text|password|number|checkbox|select|multiselect|
//                        textarea|json|object|list|weekdays|duration|voice,
//     required?, options? [{value,label}], asNumber? (select), nullable?,
//     default?, hint?, placeholder?, rows?,
//     voiceOptions? (voice: [{value,label,language,languages}] from a catalogue;
//                    two or more languages add a filter, its choice kept
//                    under the synthetic `${name}__lang` values key),
//     allowCustomVoice? (false hides the ID input and keeps the name selected),
//     voicesLoading? (voice: the catalogue fetch is in flight),
//     helpKey? (a "?" beside the label opens this description in a popover —
//               for what a setting *means*, where `hint` is for what an input
//               *does*; see components/HelpTip),
//     itemFields? (list: spec for each row's scalar sub-fields; the value is an
//                  array of objects, e.g. BO `configs`), addLabel? (list: the
//                  add-row button text, also addLabelKey),
//     asList? (text "a, b" → array), listOf? ('int' — items must be numbers),
//     dayOptions? (weekdays: [{value: 0-6, label}] rendered as toggle buttons;
//                  the value is an array of numbers, empty → null when
//                  nullable, same convention as any other blank field),
//     durationUnit? (duration: seconds per displayed unit, e.g. 60 for an
//                    input in minutes — the value is still stored/sent in
//                    seconds, only the on-screen number is scaled),
//     emptyValue? (what to put in the payload for an empty field instead of
//                  null / omitting it),
//     optionsLoading? (select/multiselect: options are still on their way, so a
//                      value missing from them is not reported as unknown yet),
//     readOnly? (the value is fixed once the resource exists — the input is
//                shown but disabled and the field is left out of the payload),
//     showIf? (values) => boolean — the field is hidden (but still part of the
//              payload) while this returns false; for a setting that only
//              matters once a sibling toggle is on,
//     compute? (values) => value — `type: 'computed'` only: never rendered,
//              its payload value is derived from sibling values at submit
//              time instead of typed in (e.g. tts_model_id auto-picked from
//              the chosen voice, VOAD-57) — undefined leaves it out of the
//              payload (nullable → null instead),
//     emptyLabel? (select: text of the blank option, when "— select —" does not
//                  say what leaving it blank means),
//     fields? (object: nested spec; keys in `values` stay flat — "group.sub") }
//
// select/multiselect against a remote directory (helpdesk teams, agents, tags)
// may hold an id that no longer has a name — the item was deleted upstream
// after the flow was saved. Such a value is kept, rendered as the bare id and
// marked invalid, so it is visible without being thrown away on the next save.
//
// An option may also carry `disabled: true` — it exists but must not be picked
// (a messenger chat that is switched off, say). Such an option cannot be
// chosen, and a *stored* value that landed on one is reported the same way a
// deleted one is: `disabledMessageKey` names the text, defaulting to the
// "not in the directory any more" wording.
//
// Any text slot may instead be given as a key: `labelKey`, `hintKey`,
// `placeholderKey` (plus optional `labelParams` etc.), and options may carry
// `labelKey`. Specs therefore stay plain data and this component decides the
// language — see i18n/registry.js#resolveText.
//
// Object groups mirror the backend's strict nested schemas (extra=forbid): an
// empty group (all fields blank, checkboxes at their default) becomes null when
// nullable, otherwise it is left out of the payload so the backend applies its
// own defaults.

const splitList = (text) =>
  String(text)
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean);

/** Values of a multiselect stay an array of strings all the way through. */
const toIdList = (raw) =>
  (Array.isArray(raw) ? raw : [])
    .filter((v) => v !== null && v !== undefined && v !== '')
    .map(String);

/**
 * `withDefaults: false` opens the field blank even though it has a default —
 * used for the fields of a nullable group that is not set (see
 * `buildInitialValues`).
 */
const toFormValue = (field, raw, withDefaults = true) => {
  const fallback = withDefaults ? field.default : undefined;
  switch (field.type) {
    case 'list':
      // Rows stay as an array of plain objects all the way through; each row's
      // scalar values are kept as strings so the inputs bind directly.
      if (Array.isArray(raw)) return raw.map((item) => ({ ...item }));
      return Array.isArray(fallback) ? fallback.map((item) => ({ ...item })) : [];
    case 'multiselect':
      return toIdList(raw === undefined ? fallback : raw);
    case 'checkbox':
      return raw === undefined ? Boolean(fallback) : Boolean(raw);
    case 'json':
      if (raw === undefined) {
        return fallback !== undefined ? JSON.stringify(fallback, null, 2) : '';
      }
      return raw === null ? '' : JSON.stringify(raw, null, 2);
    case 'number':
      if (raw === undefined) return fallback !== undefined ? String(fallback) : '';
      return raw === null ? '' : String(raw);
    case 'duration': {
      // Stored in seconds; shown in `field.durationUnit` seconds per unit
      // (e.g. 60 for minutes) so an operator edits "5" instead of "300".
      const unit = field.durationUnit || 1;
      if (raw === undefined) return fallback !== undefined ? String(fallback / unit) : '';
      return raw === null ? '' : String(raw / unit);
    }
    case 'weekdays':
      if (Array.isArray(raw)) return raw.map(Number);
      return Array.isArray(fallback) ? fallback.map(Number) : [];
    case 'datetime-local':
      if (raw) {
        try {
          const d = new Date(raw);
          if (!isNaN(d.getTime())) {
            const pad = (n) => String(n).padStart(2, '0');
            return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
          }
        } catch (_) {
          // fall through to the raw-string slice below
        }
        return String(raw).slice(0, 16);
      }
      return '';
    case 'date':
      if (raw) {
        try {
          const d = new Date(raw);
          if (!isNaN(d.getTime())) {
            const pad = (n) => String(n).padStart(2, '0');
            return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
          }
        } catch (_) {
          // fall through to the raw-string slice below
        }
        return String(raw).slice(0, 10);
      }
      return '';
    case 'time':
      // Backend `time` fields round-trip as "HH:MM:SS" — the native time
      // input only wants "HH:MM" (its default step is whole minutes).
      if (raw === undefined) return fallback !== undefined ? String(fallback).slice(0, 5) : '';
      return raw ? String(raw).slice(0, 5) : '';
    case 'select':
      if (raw === undefined) return fallback !== undefined ? String(fallback) : '';
      return raw === null ? '' : String(raw);
    default:
      if (field.asList && Array.isArray(raw)) return raw.join(', ');
      if (raw === undefined) return fallback !== undefined ? String(fallback) : '';
      return raw === null ? '' : String(raw);
  }
};

export const buildInitialValues = (fields, row) => {
  const out = {};
  const visit = (specs, source, prefix, withDefaults) => {
    specs.forEach((f) => {
      if (f.type === 'object') {
        const raw = source ? source[f.name] : undefined;
        const present = Boolean(raw) && typeof raw === 'object';
        // A nullable group the server did not send is "off". Filling its fields
        // with defaults would read as a value the step does not have — and
        // `buildPayload` would then save it as one — so it opens blank instead.
        visit(
          f.fields,
          present ? raw : undefined,
          `${prefix}${f.name}.`,
          withDefaults && (present || !f.nullable)
        );
      } else {
        out[`${prefix}${f.name}`] = toFormValue(f, source ? source[f.name] : undefined, withDefaults);
      }
    });
  };
  visit(fields, row || undefined, '', true);
  return out;
};

/**
 * Values for a field set that has just changed shape — a variant switch made
 * fields appear. The keys that came with them start at their default, the ones
 * already in the form (including those of fields that just went away) are left
 * alone, so switching back brings the old input with it.
 */
export const withFieldDefaults = (fields, values) => {
  const out = { ...values };
  const visit = (specs, prefix, withDefaults) => {
    specs.forEach((f) => {
      if (f.type === 'object') {
        visit(f.fields, `${prefix}${f.name}.`, withDefaults && !f.nullable);
      } else if (!(`${prefix}${f.name}` in out)) {
        out[`${prefix}${f.name}`] = toFormValue(f, undefined, withDefaults);
      }
    });
  };
  visit(fields, '', true);
  return out;
};

/**
 * Builds a payload from form values. Returns { payload, errors }, errors keyed
 * by the flat field key. An empty optional field: emptyValue → emptyValue,
 * nullable → null, otherwise it is left out of the payload.
 *
 * Error values are i18n keys. `ResourceForm` runs them through `t`, which
 * returns unknown keys verbatim — so a caller may also hand back a literal
 * message and it renders unchanged.
 */
export const buildPayload = (fields, values) => {
  const errors = {};

  const build = (specs, prefix) => {
    const payload = {};
    let significant = false;

    specs.forEach((field) => {
      const key = `${prefix}${field.name}`;

      // Read-only fields cannot have been touched, so they are never sent —
      // the backend rejects (or ignores) them on update anyway.
      if (field.readOnly) return;

      if (field.type === 'object') {
        const sub = build(field.fields, `${key}.`);
        if (sub.significant) {
          payload[field.name] = sub.payload;
          significant = true;
        } else if (field.nullable) {
          payload[field.name] = null;
        }
        return;
      }

      if (field.type === 'computed') {
        const computed = field.compute(values);
        if (computed === undefined) {
          if (field.nullable) payload[field.name] = null;
        } else {
          payload[field.name] = computed;
          significant = true;
        }
        return;
      }

      if (field.type === 'checkbox') {
        const val = Boolean(values[key]);
        payload[field.name] = val;
        // A checkbox left at its default does not make the group "filled in".
        if (val !== Boolean(field.default)) significant = true;
        return;
      }

      if (field.type === 'list') {
        const rows = Array.isArray(values[key]) ? values[key] : [];
        const built = rows.map((item, i) => {
          const row = {};
          field.itemFields.forEach((sub) => {
            const raw = item ? item[sub.name] : undefined;
            const text = typeof raw === 'string' ? raw : raw == null ? '' : String(raw);
            if (text.trim() === '') {
              if (sub.required) errors[`${key}.${i}.${sub.name}`] = 'common.required';
              return;
            }
            row[sub.name] =
              sub.type === 'number' || (sub.type === 'select' && sub.asNumber) ? Number(text) : text;
          });
          return row;
        });
        if (built.length > 0) significant = true;
        // The array is always sent: clearing every row is how the user empties
        // the list (e.g. removing all BO configs sends []).
        payload[field.name] = built;
        return;
      }

      if (field.type === 'weekdays') {
        const arr = Array.isArray(values[key]) ? values[key].map(Number) : [];
        if (arr.length === 0) {
          if (field.required) {
            errors[key] = 'common.required';
          } else if ('emptyValue' in field) {
            payload[field.name] = field.emptyValue;
          } else if (field.nullable) {
            payload[field.name] = null;
          }
          return;
        }
        significant = true;
        payload[field.name] = [...arr].sort((a, b) => a - b);
        return;
      }

      if (field.type === 'multiselect') {
        const items = toIdList(values[key]);
        if (items.length === 0) {
          if (field.required) {
            errors[key] = 'common.required';
          } else if ('emptyValue' in field) {
            payload[field.name] = field.emptyValue;
          } else if (field.nullable) {
            payload[field.name] = null;
          }
          return;
        }
        significant = true;
        payload[field.name] = items;
        return;
      }

      const v = values[key];
      const text = typeof v === 'string' ? v : v == null ? '' : String(v);
      const isEmpty = text.trim() === '';

      if (isEmpty) {
        if (field.required) {
          errors[key] = 'common.required';
        } else if ('emptyValue' in field) {
          payload[field.name] = field.emptyValue;
        } else if (field.nullable) {
          payload[field.name] = null;
        }
        return;
      }

      significant = true;

      if (field.asList) {
        const items = splitList(text);
        if (field.listOf === 'int' || field.listOf === 'number') {
          const nums = items.map(Number);
          if (nums.some((n) => Number.isNaN(n))) {
            errors[key] = 'common.mustBeNumberList';
            return;
          }
          payload[field.name] = nums;
        } else {
          payload[field.name] = items;
        }
        return;
      }

      switch (field.type) {
        case 'number': {
          const n = Number(text);
          if (Number.isNaN(n)) {
            errors[key] = 'common.mustBeNumber';
          } else {
            payload[field.name] = n;
          }
          break;
        }
        case 'duration': {
          const unit = field.durationUnit || 1;
          const n = Number(text);
          if (Number.isNaN(n)) {
            errors[key] = 'common.mustBeNumber';
          } else {
            payload[field.name] = Math.round(n * unit);
          }
          break;
        }
        case 'json': {
          try {
            payload[field.name] = JSON.parse(text);
          } catch (e) {
            errors[key] = 'common.invalidJson';
          }
          break;
        }
        case 'date':
          // endOfDay: a date-only "end" field means "through the end of that
          // day", not midnight at its start — the backend column is still a
          // full datetime.
          payload[field.name] = field.endOfDay ? `${text}T23:59:59` : text;
          break;
        case 'select':
          payload[field.name] = field.asNumber ? Number(text) : text;
          break;
        default:
          payload[field.name] = text;
      }
    });

    return { payload, significant };
  };

  const { payload } = build(fields, '');
  return { payload, errors };
};

const ObjectFields = styled.div`
  border-left: 2px solid ${({ theme }) => theme.colors.border};
  padding-left: 12px;
  margin: 2px 0 4px;
`;

const Chips = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 6px;
`;

const Chip = styled.span`
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 6px 3px 9px;
  border: 1px solid ${({ $invalid, theme }) => ($invalid ? '#ef4444' : theme.colors.border)};
  border-radius: 999px;
  font-size: 12.5px;
  color: ${({ $invalid, theme }) => ($invalid ? '#ef4444' : theme.colors.primary)};
`;

const ChipRemove = styled.button`
  display: flex;
  padding: 0;
  background: none;
  border: none;
  font-size: 14px;
  line-height: 1;
  color: inherit;
  opacity: 0.6;
  cursor: pointer;

  &:hover {
    opacity: 1;
  }
`;

const DayToggleRow = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 6px;
`;

const DayToggle = styled.button`
  padding: 5px 10px;
  font-size: 12.5px;
  font-weight: ${({ $active }) => ($active ? 700 : 500)};
  border-radius: 6px;
  border: 1px solid ${({ theme, $active }) => ($active ? theme.colors.accentNeon : theme.colors.border)};
  background: transparent;
  color: ${({ theme, $active }) => ($active ? theme.colors.accentNeon : theme.colors.secondary)};
  cursor: pointer;
  transition: color 0.15s ease, border-color 0.15s ease;
`;

const ListRows = styled.div`
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 8px;
`;

const ListRow = styled.div`
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px;
  background: ${({ theme }) => theme.colors.background};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 8px;
`;

const ListRowFields = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  flex: 1;
  min-width: 0;
`;

const ListRowField = styled.div`
  flex: ${({ $grow }) => $grow || 1};
  min-width: 130px;
`;

const ListRowFieldLabel = styled.label`
  display: block;
  margin-bottom: 4px;
  font-size: 12px;
  color: ${({ theme }) => theme.colors.secondary};
`;

const ListRemove = styled.button`
  flex-shrink: 0;
  margin-top: 22px;
  padding: 0;
  width: 24px;
  height: 24px;
  font-size: 16px;
  line-height: 1;
  color: ${({ theme }) => theme.colors.secondary};
  background: none;
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 6px;
  cursor: pointer;

  &:hover {
    color: #ef4444;
    border-color: #ef4444;
  }
`;

const ListAdd = styled.button`
  align-self: flex-start;
  padding: 6px 12px;
  font-size: 13px;
  color: ${({ theme }) => theme.colors.primary};
  background: ${({ theme }) => theme.colors.surface};
  border: 1px dashed ${({ theme }) => theme.colors.border};
  border-radius: 8px;
  cursor: pointer;

  &:hover {
    border-color: ${({ theme }) => theme.colors.secondary};
  }
`;

const ListEmpty = styled.div`
  font-size: 12.5px;
  color: ${({ theme }) => theme.colors.secondary};
`;

const TimeRangeRow = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;

  input {
    max-width: 130px;
  }
`;

const TimeRangeSep = styled.span`
  color: ${({ theme }) => theme.colors.secondary};
`;

// Clients choose a name and language; only admins can enter a vendor ID.
// The selected value remains the ID so equal names never select another voice.
const VoicePicker = styled.div`
  margin-top: 6px;
  display: flex;
  gap: 6px;
`;

const optionLabels = (t, field) => {
  const map = new Map();
  (field.options || []).forEach((opt) => map.set(String(opt.value), resolveText(t, opt, 'label')));
  return map;
};

/** Selected values that the options do not cover (deleted upstream). */
const unknownValues = (selected, labels, field) =>
  field.optionsLoading ? [] : selected.filter((v) => !labels.has(v));

/** Selected values whose option is there but marked unusable. */
const blockedValues = (selected, field) => {
  const off = new Set(
    (field.options || []).filter((o) => o.disabled).map((o) => String(o.value))
  );
  return selected.filter((v) => off.has(v));
};

const ExpandRow = styled.div`
  display: flex;
  justify-content: flex-end;
  margin-top: 6px;
`;

const ExpandToggle = styled.button`
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 600;
  color: ${({ theme }) => theme.colors.primary};
  background: ${({ theme }) => theme.colors.surface};
  border: 1px solid ${({ theme }) => theme.colors.border};
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s ease, color 0.15s ease;

  &:hover {
    color: ${({ theme }) => theme.colors.accentNeon};
    border-color: ${({ theme }) => theme.colors.accentNeon};
  }
`;

// A textarea that can grow to most of the viewport, so a long prompt can be
// read and edited whole instead of through an 8-row window.
const ExpandableTextArea = ({
  theme, invalid, rows, value, placeholder, readOnly, expandLabel, collapseLabel, onChange,
}) => {
  const [expanded, setExpanded] = useState(false);
  return (
    <>
      <TextArea
        theme={theme}
        $invalid={invalid}
        rows={rows}
        value={value}
        placeholder={placeholder}
        disabled={readOnly}
        style={expanded ? { height: '70vh', resize: 'none' } : undefined}
        onChange={(e) => onChange(e.target.value)}
        spellCheck={false}
      />
      <ExpandRow>
        <ExpandToggle type="button" theme={theme} onClick={() => setExpanded((v) => !v)}>
          {expanded ? <FiMinimize2 size={13} /> : <FiMaximize2 size={13} />}
          {expanded ? collapseLabel : expandLabel}
        </ExpandToggle>
      </ExpandRow>
    </>
  );
};

export const ResourceForm = ({ fields, values, errors, onChange }) => {
  const { theme } = useTheme();
  const { t } = useI18n();

  // The form is controlled by its parent (values/onChange) so a submit button
  // in a modal footer can reach the current values.
  const set = (name, value) => {
    onChange({ ...values, [name]: value });
  };

  // One scalar cell inside a `list` row. `onItemChange(name, value)` writes back
  // into the row object the parent holds.
  const renderListItemField = (sub, item, i, listKey, onItemChange) => {
    const subKey = `${listKey}.${i}.${sub.name}`;
    const subError = errors?.[subKey];
    const subLabel = resolveText(t, sub, 'label');
    const subPlaceholder = resolveText(t, sub, 'placeholder');
    const val = item?.[sub.name] ?? '';

    return (
      <ListRowField key={sub.name} $grow={sub.grow}>
        <ListRowFieldLabel theme={theme}>
          {subLabel}
          {sub.required ? ' *' : ''}
        </ListRowFieldLabel>
        {sub.type === 'select' ? (
          <Select
            theme={theme}
            $invalid={Boolean(subError)}
            value={val}
            onChange={(e) => onItemChange(sub.name, e.target.value)}
          >
            {(!sub.required || !val) && (
              <option value="" disabled={sub.required}>
                {resolveText(t, sub, 'emptyLabel') ||
                  ((sub.options || []).length === 0 ? t('common.noOptions') : t('common.selectPrompt'))}
              </option>
            )}
            {(sub.options || []).map((opt) => (
              <option key={String(opt.value)} value={String(opt.value)}>
                {resolveText(t, opt, 'label')}
              </option>
            ))}
          </Select>
        ) : (
          <TextInput
            theme={theme}
            type={sub.type === 'password' ? 'password' : sub.type === 'number' ? 'number' : 'text'}
            value={val}
            placeholder={subPlaceholder || ''}
            onChange={(e) => onItemChange(sub.name, e.target.value)}
          />
        )}
        {subError && (
          <FieldHint theme={theme} $error>
            {t(subError)}
          </FieldHint>
        )}
      </ListRowField>
    );
  };

  // Renders `startField`/`endField` (both `type: 'time'`) as one "from – to"
  // row under a single label, instead of two separate fields — see the
  // `rangeWith` handling in the `object` branch of renderField below.
  const renderTimeRange = (startField, endField, startKey, endKey) => {
    const label = resolveText(t, startField, 'rangeLabel') || resolveText(t, startField, 'label');
    const hint = resolveText(t, startField, 'hint');
    return (
      <FieldGroup key={startKey}>
        <FieldLabel theme={theme}>{label}</FieldLabel>
        <TimeRangeRow>
          <TextInput
            theme={theme}
            type="time"
            value={values[startKey] ?? ''}
            onChange={(e) => set(startKey, e.target.value)}
          />
          <TimeRangeSep theme={theme}>{'–'}</TimeRangeSep>
          <TextInput
            theme={theme}
            type="time"
            value={values[endKey] ?? ''}
            onChange={(e) => set(endKey, e.target.value)}
          />
        </TimeRangeRow>
        {hint && <FieldHint theme={theme}>{hint}</FieldHint>}
      </FieldGroup>
    );
  };

  const renderField = (field, key) => {
    if (field.type === 'computed') return null;
    if (field.showIf && !field.showIf(values)) return null;

    const error = errors?.[key];
    const label = resolveText(t, field, 'label');
    const hint = resolveText(t, field, 'hint');
    const placeholder = resolveText(t, field, 'placeholder');
    const help = field.helpKey ? <HelpTip text={t(field.helpKey)} /> : null;

    if (field.type === 'object') {
      // A `rangeWith: '<nextFieldName>'` on a field pairs it with the field
      // right after it into one "from – to" row (e.g. calling-hours start/
      // end) instead of two separate inputs — see renderTimeRange below.
      const subFields = field.fields;
      const rendered = [];
      for (let i = 0; i < subFields.length; i++) {
        const sub = subFields[i];
        const next = subFields[i + 1];
        if (sub.rangeWith && next && next.name === sub.rangeWith) {
          rendered.push(
            renderTimeRange(sub, next, `${key}.${sub.name}`, `${key}.${next.name}`)
          );
          i += 1;
        } else {
          rendered.push(renderField(sub, `${key}.${sub.name}`));
        }
      }
      return (
        <FieldGroup key={key}>
          <FieldLabel theme={theme}>
            {label}
            {help}
          </FieldLabel>
          {hint && <FieldHint theme={theme}>{hint}</FieldHint>}
          <ObjectFields theme={theme}>{rendered}</ObjectFields>
        </FieldGroup>
      );
    }

    if (field.type === 'checkbox') {
      return (
        <FieldGroup key={key}>
          <CheckboxLabel theme={theme}>
            <input
              type="checkbox"
              checked={Boolean(values[key])}
              disabled={field.readOnly}
              onChange={(e) => set(key, e.target.checked)}
            />
            {label}
            {help}
          </CheckboxLabel>
          {hint && <FieldHint theme={theme}>{hint}</FieldHint>}
        </FieldGroup>
      );
    }

    if (field.type === 'list') {
      const items = Array.isArray(values[key]) ? values[key] : [];
      const setItems = (next) => set(key, next);
      const makeRow = () => {
        const row = {};
        field.itemFields.forEach((sub) => {
          row[sub.name] = sub.default !== undefined ? String(sub.default) : '';
        });
        return row;
      };
      const addLabel = resolveText(t, field, 'addLabel') || t('common.addRow');

      return (
        <FieldGroup key={key}>
          <FieldLabel theme={theme}>
            {label}
            {field.required ? ' *' : ''}
            {help}
          </FieldLabel>
          {hint && <FieldHint theme={theme}>{hint}</FieldHint>}
          <ListRows>
            {items.length === 0 && <ListEmpty theme={theme}>{t('common.noEntries')}</ListEmpty>}
            {items.map((item, i) => (
              <ListRow key={i} theme={theme}>
                <ListRowFields>
                  {field.itemFields.map((sub) =>
                    renderListItemField(sub, item, i, key, (name, val) =>
                      setItems(items.map((it, idx) => (idx === i ? { ...it, [name]: val } : it)))
                    )
                  )}
                </ListRowFields>
                <ListRemove
                  theme={theme}
                  type="button"
                  aria-label={t('common.remove')}
                  onClick={() => setItems(items.filter((_, idx) => idx !== i))}
                >
                  ×
                </ListRemove>
              </ListRow>
            ))}
          </ListRows>
          <ListAdd theme={theme} type="button" onClick={() => setItems([...items, makeRow()])}>
            + {addLabel}
          </ListAdd>
        </FieldGroup>
      );
    }

    if (field.type === 'weekdays') {
      const selectedDays = Array.isArray(values[key]) ? values[key].map(Number) : [];
      const toggleDay = (day) =>
        set(
          key,
          selectedDays.includes(day) ? selectedDays.filter((d) => d !== day) : [...selectedDays, day]
        );

      return (
        <FieldGroup key={key}>
          <FieldLabel theme={theme}>
            {label}
            {field.required ? ' *' : ''}
            {help}
          </FieldLabel>
          <DayToggleRow>
            {(field.dayOptions || []).map((opt) => (
              <DayToggle
                key={opt.value}
                type="button"
                theme={theme}
                $active={selectedDays.includes(opt.value)}
                onClick={() => toggleDay(opt.value)}
              >
                {resolveText(t, opt, 'label')}
              </DayToggle>
            ))}
          </DayToggleRow>
          {hint && <FieldHint theme={theme}>{hint}</FieldHint>}
        </FieldGroup>
      );
    }

    // Values that lost their name: reported under the field even before a
    // submit, since nothing the user does here can fix them.
    const labels =
      field.type === 'select' || field.type === 'multiselect' ? optionLabels(t, field) : null;
    const selected = field.type === 'multiselect' ? toIdList(values[key]) : [];
    const chosen = labels
      ? field.type === 'multiselect'
        ? selected
        : [values[key]].filter(Boolean).map(String)
      : [];
    const stale = labels ? unknownValues(chosen, labels, field) : [];
    const blocked = labels ? blockedValues(chosen, field) : [];
    const staleMessage =
      stale.length > 0
        ? t('common.unknownIds', { ids: stale.join(', ') })
        : blocked.length > 0
          ? t(field.disabledMessageKey || 'common.unknownIds', {
              ids: blocked.map((v) => labels.get(v) ?? v).join(', '),
            })
          : null;
    const invalid = stale.length > 0 || blocked.length > 0;

    if (field.type === 'multiselect') {
      const setSelected = (next) => set(key, next);
      return (
        <FieldGroup key={key}>
          <FieldLabel theme={theme}>
            {label}
            {field.required ? ' *' : ''}
            {help}
          </FieldLabel>
          {selected.length > 0 && (
            <Chips>
              {selected.map((value) => (
                <Chip
                  key={value}
                  theme={theme}
                  $invalid={stale.includes(value) || blocked.includes(value)}
                >
                  {labels.get(value) ?? value}
                  {!field.readOnly && (
                    <ChipRemove
                      type="button"
                      aria-label={`${label}: ${labels.get(value) ?? value} ×`}
                      onClick={() => setSelected(selected.filter((v) => v !== value))}
                    >
                      ×
                    </ChipRemove>
                  )}
                </Chip>
              ))}
            </Chips>
          )}
          <Select
            theme={theme}
            $invalid={Boolean(error) || invalid}
            value=""
            disabled={field.readOnly}
            onChange={(e) => {
              if (e.target.value) setSelected([...selected, e.target.value]);
            }}
          >
            <option value="">
              {field.optionsLoading
                ? t('common.loading')
                : (field.options || []).length === 0
                  ? t('common.noOptions')
                  : t('common.addPrompt')}
            </option>
            {(field.options || [])
              .filter((opt) => !selected.includes(String(opt.value)))
              .map((opt) => (
                <option key={String(opt.value)} value={String(opt.value)} disabled={opt.disabled}>
                  {resolveText(t, opt, 'label')}
                </option>
              ))}
          </Select>
          {(error || staleMessage || hint) && (
            <FieldHint theme={theme} $error={Boolean(error || staleMessage)}>
              {error ? t(error) : staleMessage || hint}
            </FieldHint>
          )}
        </FieldGroup>
      );
    }

    return (
      <FieldGroup key={key}>
        <FieldLabel theme={theme}>
          {label}
          {field.required ? ' *' : ''}
          {help}
        </FieldLabel>
        {field.type === 'select' ? (
          // A native select always shows *some* option, so an empty value must
          // get an explicit placeholder — otherwise the first option looks
          // chosen while the form still holds "" and rejects the submit, and
          // with a single option there is no change event to fix it up.
          <Select
            theme={theme}
            $invalid={Boolean(error) || invalid}
            value={values[key] ?? ''}
            disabled={field.readOnly}
            onChange={(e) => set(key, e.target.value)}
          >
            {(!field.required || !values[key]) && (
              <option value="" disabled={field.required}>
                {resolveText(t, field, 'emptyLabel')
                  || ((field.options || []).length === 0
                    ? t('common.noOptions')
                    : t('common.selectPrompt'))}
              </option>
            )}
            {/* The stored id has no option of its own — without this the select
                would silently show the first option instead. */}
            {stale.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
            {(field.options || []).map((opt) => (
              <option
                key={String(opt.value)}
                value={String(opt.value)}
                // A disabled option that is the current value still renders —
                // the stored chat has to stay visible to be corrected.
                disabled={opt.disabled && String(opt.value) !== String(values[key] ?? '')}
              >
                {resolveText(t, opt, 'label')}
              </option>
            ))}
          </Select>
        ) : field.expandable && field.type === 'textarea' ? (
          <ExpandableTextArea
            theme={theme}
            invalid={Boolean(error)}
            rows={field.rows || 4}
            value={values[key] ?? ''}
            placeholder={placeholder || ''}
            readOnly={field.readOnly}
            expandLabel={t('common.expand')}
            collapseLabel={t('common.collapse')}
            onChange={(v) => set(key, v)}
          />
        ) : field.type === 'textarea' || field.type === 'json' ? (
          <TextArea
            theme={theme}
            $invalid={Boolean(error)}
            rows={field.rows || (field.type === 'json' ? 5 : 4)}
            value={values[key] ?? ''}
            placeholder={placeholder || (field.type === 'json' ? '{ }' : '')}
            disabled={field.readOnly}
            onChange={(e) => set(key, e.target.value)}
            spellCheck={false}
          />
        ) : field.type === 'voice' ? (
          <>
            {field.allowCustomVoice !== false && (
              <TextInput
                theme={theme}
                type="text"
                value={values[key] ?? ''}
                placeholder={placeholder || ''}
                disabled={field.readOnly}
                onChange={(e) => set(key, e.target.value)}
              />
            )}
            {(field.allowCustomVoice === false || field.voicesLoading || (field.voiceOptions || []).length > 0) && (() => {
              const selectionOnly = field.allowCustomVoice === false;
              const langFilterKey = `${key}__lang`;
              const langFilter = values[langFilterKey] || '';
              // Unique languages present in the catalogue, in the same order
              // voiceOptions already sorted them — no options with no known
              // language means no filter is offered at all.
              const languages = [
                ...new Set(
                  (field.voiceOptions || []).flatMap((opt) => opt.languages || [opt.language]).filter(Boolean)
                ),
              ];
              const visibleOptions = langFilter
                ? (field.voiceOptions || []).filter((opt) => (opt.languages || [opt.language]).includes(langFilter))
                : field.voiceOptions || [];
              const current = values[key] || '';
              const selected = (field.voiceOptions || []).find((opt) => opt.value === current);
              // Keep an existing selection visible when its language is filtered
              // out, or its catalogue is loading/unavailable. Never clear it.
              const keepCurrent = selectionOnly && current && !visibleOptions.some((opt) => opt.value === current);

              return (
                <VoicePicker>
                  {languages.length > 1 && (
                    <Select
                      theme={theme}
                      aria-label={t('agents.fields.voiceAllLanguages')}
                      value={langFilter}
                      disabled={field.readOnly}
                      onChange={(e) => set(langFilterKey, e.target.value)}
                    >
                      <option value="">{t('agents.fields.voiceAllLanguages')}</option>
                      {languages.map((lang) => (
                        <option key={lang} value={lang}>
                          {lang}
                        </option>
                      ))}
                    </Select>
                  )}
                  <Select
                    theme={theme}
                    aria-label={label}
                    $invalid={Boolean(error)}
                    value={selectionOnly ? current : ''}
                    disabled={field.readOnly || (selectionOnly && field.voicesLoading)}
                    onChange={(e) => {
                      if (selectionOnly || e.target.value) set(key, e.target.value);
                    }}
                  >
                    <option value="" disabled={selectionOnly && field.required}>
                      {field.voicesLoading ? t('common.loading') : selectionOnly && field.nullable ? t('agents.languages.none') : t('common.selectPrompt')}
                    </option>
                    {keepCurrent && <option value={current}>{selected?.label || t('agents.fields.currentVoice')}</option>}
                    {visibleOptions.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label || t('agents.fields.unnamedVoice')}
                      </option>
                    ))}
                  </Select>
                </VoicePicker>
              );
            })()}
          </>
        ) : (
          <TextInput
            theme={theme}
            type={
              field.type === 'password'
                ? 'password'
                : field.type === 'number' || field.type === 'duration'
                  ? 'number'
                  : field.type === 'datetime-local'
                    ? 'datetime-local'
                    : field.type === 'date'
                      ? 'date'
                      : field.type === 'time'
                        ? 'time'
                        : 'text'
            }
            value={values[key] ?? ''}
            placeholder={placeholder || ''}
            disabled={field.readOnly}
            onChange={(e) => set(key, e.target.value)}
          />
        )}
        {(error || staleMessage || hint) && (
          <FieldHint theme={theme} $error={Boolean(error || staleMessage)}>
            {error ? t(error) : staleMessage || hint}
          </FieldHint>
        )}
      </FieldGroup>
    );
  };

  return <>{fields.map((f) => renderField(f, f.name))}</>;
};
