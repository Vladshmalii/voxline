// Shared by CampaignsPage and AudiencesPage's contact-upload modals.
// "phone,name,language" per line, or a JSON array of contact rows
// (SCampaignContactRow-shaped). Whichever parses is used — the upload
// endpoint gives the real per-row verdict.
export const parseContactsInput = (text) => {
  const trimmed = text.trim();
  if (!trimmed) return [];
  if (trimmed.startsWith('[')) {
    const parsed = JSON.parse(trimmed);
    if (!Array.isArray(parsed)) throw new Error('not an array');
    return parsed;
  }
  return trimmed
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [phone, name, language] = line.split(',').map((s) => s.trim());
      const row = { phone };
      if (name) row.name = name;
      if (language) row.language = language;
      return row;
    });
};
