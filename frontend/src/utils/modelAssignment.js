// Filter the field specs themselves so restricted values never enter payloads.
const ADMIN_MODEL_FIELDS = new Set([
  'stt_model_id', 'tts_model_id', 'ttt_model_id', 'ttt_extra_body',
  'stt_params', 'tts_params', 'ttt_params',
]);

export const modelFieldsForRole = (fields, canAssign) =>
  canAssign ? fields : fields.filter((field) => !ADMIN_MODEL_FIELDS.has(field.name));
