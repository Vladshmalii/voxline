// Mock backend for the admin UI: no Postgres, no Redis, no telephony.
//
//   node mock/server.mjs            (port 8086, or MOCK_PORT)
//
// Driven by mock/openapi.json (the real backend's OpenAPI document), so every
// endpoint answers with the shape the UI expects. Collections are generated
// once, kept in memory and support list/get/create/update/delete, so the pages
// behave like a live system until the process restarts. Auth is always "signed
// in" as an admin. The agent playground WebSocket is not mocked.
import http from 'node:http';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const spec = JSON.parse(readFileSync(path.join(here, 'openapi.json'), 'utf8'));
const PORT = Number(process.env.MOCK_PORT || 8086);
const LIST_SIZE = 42;

// ── deterministic randomness, so reloads look the same ───────────────────────
let seed = 20261012;
const rnd = () => {
  seed = (seed * 1664525 + 1013904223) % 4294967296;
  return seed / 4294967296;
};
const int = (lo, hi) => Math.floor(lo + rnd() * (hi - lo + 1));
const pick = (list) => list[int(0, list.length - 1)];

const FIRST = ['Anna', 'Ivan', 'Maria', 'Oleg', 'Elena', 'Pavel', 'Sofia', 'Dmitry', 'Nina', 'Artem'];
const LAST = ['Petrov', 'Ivanova', 'Smith', 'Kowalski', 'Novak', 'Garcia', 'Bondar', 'Melnyk'];
const WORDS = ['welcome back', 'bonus offer', 'reactivation', 'vip follow-up', 'summer promo', 'verification'];
const COUNTRIES = ['US', 'GB', 'DE', 'PL', 'UA', 'BG', 'ES'];
const now = Date.now();
const iso = (daysAgo = 0) => new Date(now - daysAgo * 864e5 - int(0, 864e5 - 1)).toISOString().slice(0, 19);
const phone = () => `+1555${int(1000000, 9999999)}`;
const uuid = () =>
  'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = int(0, 15);
    return (c === 'x' ? r : (r & 3) | 8).toString(16);
  });

// ── schema-driven generator ──────────────────────────────────────────────────
const resolve = (node) => {
  if (node && node.$ref) {
    return node.$ref
      .replace(/^#\//, '')
      .split('/')
      .reduce((acc, key) => acc[key], spec);
  }
  return node;
};

const stringFor = (key, schema) => {
  const k = key.toLowerCase();
  if (schema.format === 'date-time' || /(_at|_from|_to)$/.test(k) || k === 'date') return iso(int(0, 30));
  if (schema.format === 'date') return iso(int(0, 30)).slice(0, 10);
  if (schema.format === 'uuid' || k === 'uuid' || k.endsWith('_uuid')) return uuid();
  if (k.includes('email')) return `${pick(FIRST).toLowerCase()}@example.com`;
  if (k.includes('phone') || k.endsWith('_number') || k === 'to' || k === 'sender') return phone();
  if (k === 'name' || k.endsWith('_name')) return `${pick(FIRST)} ${pick(LAST)}`;
  if (k.includes('url')) return 'https://example.com/v1';
  if (k === 'language' || k.endsWith('_language')) return pick(['en', 'ru', 'es']);
  if (k === 'country') return pick(COUNTRIES);
  if (k === 'currency') return 'USD';
  if (k === 'timezone') return 'Europe/Berlin';
  if (k === 'summary' || k === 'description' || k === 'body' || k === 'text' || k === 'error') {
    return `The customer asked about the ${pick(WORDS)} and agreed to a follow-up.`;
  }
  if (k === 'code' || k === 'model') return pick(['nova-3', 'qwen3-asr', 'sonic-2', 'gpt-oss-20b']);
  if (k === 'voice') return pick(['vivian', 'aria', 'marcus']);
  if (k === 'api_key' || k === 'auth_token') return null;
  return `${key.replace(/_/g, ' ')} ${int(1, 99)}`;
};

const numberFor = (key, schema) => {
  const k = key.toLowerCase();
  const integer = schema.type === 'integer';
  let value;
  if (/rate|ratio|share|fraction/.test(k)) value = rnd();
  else if (/_ms$/.test(k)) value = int(150, 2400);
  else if (/seconds|duration/.test(k)) value = int(20, 400);
  else if (/balance|deposit|amount|spent|cost|price|tariff/.test(k)) value = Math.round(rnd() * 90000) / 100 + 5;
  else if (k === 'id' || k.endsWith('_id')) value = int(1, 40);
  else if (/count|total|calls|sent|members|rows|attempts|minutes/.test(k)) value = int(5, 480);
  else value = int(0, 100);
  if (schema.minimum !== undefined) value = Math.max(value, schema.minimum);
  if (schema.maximum !== undefined) value = Math.min(value, schema.maximum);
  return integer ? Math.round(value) : Math.round(value * 100) / 100;
};

function gen(schemaIn, key = '', depth = 0) {
  const schema = resolve(schemaIn) || {};
  if (depth > 7) return null;
  if (schema.anyOf || schema.oneOf) {
    const options = (schema.anyOf || schema.oneOf).filter((o) => resolve(o).type !== 'null' && o.type !== 'null');
    return options.length ? gen(options[0], key, depth + 1) : null;
  }
  if (schema.allOf) return gen(schema.allOf[0], key, depth + 1);
  if (schema.enum) return pick(schema.enum);
  if (schema.const !== undefined) return schema.const;
  switch (schema.type) {
    case 'string':
      return stringFor(key, schema);
    case 'integer':
    case 'number':
      return numberFor(key, schema);
    case 'boolean':
      return /active|enabled|operational/.test(key) ? true : rnd() > 0.5;
    case 'array': {
      const n = /tags|bonuses/.test(key) ? int(0, 2) : int(3, 5);
      return Array.from({ length: n }, () => gen(schema.items || {}, key.replace(/s$/, ''), depth + 1));
    }
    case 'object':
    default: {
      if (schema.properties) {
        const out = {};
        for (const [prop, sub] of Object.entries(schema.properties)) out[prop] = gen(sub, prop, depth + 1);
        return out;
      }
      if (schema.additionalProperties && typeof schema.additionalProperties === 'object') {
        const out = {};
        for (const name of ['alpha', 'beta', 'gamma']) out[name] = gen(schema.additionalProperties, key, depth + 1);
        return out;
      }
      return {};
    }
  }
}

// ── routing over the OpenAPI paths ───────────────────────────────────────────
const routes = [];
for (const [p, methods] of Object.entries(spec.paths)) {
  const regex = new RegExp(`^${p.replace(/\{[^}]+\}/g, '([^/]+)')}$`);
  for (const [method, op] of Object.entries(methods)) {
    routes.push({ method: method.toUpperCase(), path: p, regex, op });
  }
}
// Literal segments before parameters: /voice-agents/preview-voice-direct must not match /{item_id}/...
routes.sort((a, b) => (a.path.match(/\{/g) || []).length - (b.path.match(/\{/g) || []).length);

const responseSchema = (op) => {
  const ok = op.responses?.['200'] || op.responses?.['201'];
  return ok?.content?.['application/json']?.schema || null;
};

// The collection behind a path: /v1/calls/{id}/cancel and /v1/calls both live in "calls".
const collectionOf = (p) => p.split('/').filter(Boolean)[1];
const store = new Map(); // collection -> { items: [], nextId }
const singles = new Map(); // "METHOD path" -> generated body

const itemSchemaOf = (schema) => {
  const s = resolve(schema);
  if (s?.type === 'array') return s.items;
  if (s?.properties?.data?.type === 'array') return s.properties.data.items;
  return null;
};

function collection(name, itemSchema) {
  if (!store.has(name)) {
    const items = Array.from({ length: LIST_SIZE }, (_, i) => {
      const item = gen(itemSchema, name.replace(/s$/, ''));
      if (item && typeof item === 'object') {
        item.id = i + 1;
        if ('created_at' in item) item.created_at = iso(Math.floor((LIST_SIZE - i) / 2));
        if ('updated_at' in item) item.updated_at = item.created_at;
      }
      return item;
    });
    store.set(name, { items, nextId: LIST_SIZE + 1 });
  }
  return store.get(name);
}

const send = (res, status, body, headers = {}) => {
  const isJson = body !== null && typeof body === 'object';
  res.writeHead(status, {
    'Content-Type': isJson ? 'application/json' : headers['Content-Type'] || 'text/plain',
    ...headers,
  });
  res.end(status === 204 ? undefined : isJson ? JSON.stringify(body) : body);
};

const readBody = (req) =>
  new Promise((resolveBody) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      try {
        resolveBody(raw ? JSON.parse(raw) : {});
      } catch {
        resolveBody({});
      }
    });
  });

const matchesFilters = (item, query) => {
  for (const [k, v] of Object.entries(query)) {
    if (['limit', 'offset', 'sort', 'format', 'search', 'date_from', 'date_to'].includes(k)) continue;
    if (!(k in item)) continue;
    if (String(item[k]) !== v) return false;
  }
  const search = (query.search || '').toLowerCase();
  if (search) return JSON.stringify(item).toLowerCase().includes(search);
  return true;
};

const ORGS = [
  { uuid: '11111111-1111-4111-8111-111111111111', name: 'Acme Casino', role: 'admin' },
  { uuid: '22222222-2222-4222-8222-222222222222', name: 'Globex Support', role: 'owner' },
];
const session = () => ({
  user: { id: 1, email: 'admin@example.com', name: 'Demo Admin', is_superuser: true },
  organization: { uuid: ORGS[0].uuid, name: ORGS[0].name },
  role: 'super_admin',
});

// Hand-written answers where generated data would look wrong.
// "Sign out" really signs out (until the next login), so the login page can be
// reviewed; a fresh start is always signed in.
let signedIn = true;
const overrides = {
  'POST /v1/auth/login': () => ((signedIn = true), session()),
  'POST /v1/auth/refresh': () => session(),
  'GET /v1/auth/me': (_b, _p, res) => (signedIn ? session() : res.unauthorized),
  'POST /v1/auth/logout': () => ((signedIn = false), null),
  'GET /v1/me': () => ({ role: 'super_admin', billing_enabled: true }),
  'GET /v1/organizations': () => ORGS,
  'POST /v1/auth/change_organization/{org_uuid}': () => session(),
};

async function handle(req, res) {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const pathname = url.pathname.replace(/^\/api/, '');
  const query = Object.fromEntries(url.searchParams);

  if (pathname === '/health' || pathname === '/ready') return send(res, 200, '');

  const route = routes.find((r) => r.method === req.method && r.regex.test(pathname));
  if (!route) return send(res, 404, { detail: `mock: no route for ${req.method} ${pathname}` });
  const params = route.regex.exec(pathname).slice(1);
  const key = `${route.method} ${route.path}`;
  const body = ['POST', 'PATCH', 'PUT'].includes(req.method) ? await readBody(req) : {};

  if (overrides[key]) {
    const out = overrides[key](body, params, { unauthorized: undefined });
    if (out === undefined && key === 'GET /v1/auth/me') return send(res, 401, { detail: 'unauthorized' });
    return out === null ? send(res, 204, null) : send(res, 200, out);
  }

  // Header counters of the calls page: derived from the generated calls so the
  // numbers agree with the table below.
  if (key === 'GET /v1/calls/stats/summary') {
    const calls = collection('calls', itemSchemaOf(responseSchema(spec.paths['/v1/calls'].get))).items;
    const tally = (field) =>
      calls.reduce((acc, c) => (c[field] ? { ...acc, [c[field]]: (acc[c[field]] || 0) + 1 } : acc), {});
    return send(res, 200, { total: calls.length, statuses: tally('status'), outcomes: tally('outcome') });
  }

  // Files and audio the UI downloads or plays.
  if (/export|example$/.test(pathname)) {
    const csv = 'id,name,phone\n1,Anna Petrov,+15551234567\n2,Ivan Smith,+15557654321\n';
    return send(res, 200, csv, {
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': `attachment; filename="${collectionOf(pathname)}_demo.csv"`,
    });
  }
  if (/preview-voice/.test(pathname)) {
    const wav = Buffer.alloc(44 + 16000);
    wav.write('RIFF', 0); wav.writeUInt32LE(36 + 16000, 4); wav.write('WAVEfmt ', 8);
    wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
    wav.writeUInt32LE(16000, 24); wav.writeUInt32LE(32000, 28); wav.writeUInt16LE(2, 32);
    wav.writeUInt16LE(16, 34); wav.write('data', 36); wav.writeUInt32LE(16000, 40);
    res.writeHead(200, { 'Content-Type': 'audio/wav' });
    return res.end(wav);
  }

  const schema = responseSchema(route.op);
  const name = collectionOf(route.path);
  const itemSchema = schema ? itemSchemaOf(schema) : null;
  const isItemPath = /\{[^}]+\}$/.test(route.path);
  const idParam = params[0];

  // Collections: list / create / get / update / delete.
  if (route.method === 'GET' && itemSchema && /^\/v1\/[^/]+$/.test(route.path)) {
    const { items } = collection(name, itemSchema);
    const filtered = items.filter((it) => matchesFilters(it, query));
    const offset = Number(query.offset || 0);
    const limit = Number(query.limit || filtered.length);
    const page = filtered.slice(offset, offset + limit);
    const wrapped = resolve(schema)?.type === 'array' ? page : { data: page, count: filtered.length };
    return send(res, 200, wrapped);
  }
  if (route.method === 'POST' && !isItemPath && /^\/v1\/[^/]+$/.test(route.path)) {
    const listOp = spec.paths[route.path]?.get;
    const listItem = listOp ? itemSchemaOf(responseSchema(listOp)) : null;
    if (listItem) {
      const coll = collection(name, listItem);
      const created = { ...gen(schema, name.replace(/s$/, '')), ...body, id: coll.nextId++, created_at: iso(0), updated_at: iso(0) };
      delete created.api_key;
      delete created.auth_token;
      coll.items.unshift(created);
      return send(res, 201, created);
    }
  }
  if (isItemPath && /^\/v1\/[^/]+\/\{[^}]+\}$/.test(route.path) && store.has(name)) {
    const coll = store.get(name);
    const index = coll.items.findIndex((it) => String(it.id) === idParam);
    if (index === -1) return send(res, 404, { detail: `${name} not found` });
    if (route.method === 'GET') return send(res, 200, coll.items[index]);
    if (route.method === 'PATCH') {
      coll.items[index] = { ...coll.items[index], ...body, updated_at: iso(0) };
      return send(res, 200, coll.items[index]);
    }
    if (route.method === 'DELETE') {
      coll.items.splice(index, 1);
      return send(res, 204, null);
    }
  }

  // Everything else (stats, summaries, actions): a stable generated document.
  if (route.op.responses?.['204'] && !schema) return send(res, 204, null);
  if (!schema) return send(res, 200, {});
  const cacheKey = `${key}:${idParam || ''}`;
  if (!singles.has(cacheKey)) singles.set(cacheKey, gen(schema, name));
  let out = singles.get(cacheKey);
  // Item reads for resources whose list was never opened: generate a row.
  if (out && typeof out === 'object' && !Array.isArray(out) && 'id' in out && idParam) out = { ...out, id: Number(idParam) || out.id };
  return send(res, route.method === 'POST' ? 201 : 200, out);
}

http
  .createServer((req, res) => {
    handle(req, res).catch((err) => {
      console.error(err);
      send(res, 500, { detail: String(err) });
    });
  })
  .listen(PORT, () => console.log(`mock API on http://localhost:${PORT} (${routes.length} operations)`));
