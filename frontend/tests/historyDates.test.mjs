import assert from 'node:assert/strict';
import { test } from 'node:test';
import { periodRange, historyDateQuery } from '../src/utils/historyDates.js';

test('client presets cover complete UTC days across a month boundary', () => {
  const now = new Date('2026-10-01T00:15:00Z');
  assert.deepEqual(periodRange('today', true, now), { date_from: '2026-10-01T00:00', date_to: '2026-10-01T23:59' });
  assert.deepEqual(periodRange('yesterday', true, now), { date_from: '2026-09-30T00:00', date_to: '2026-09-30T23:59' });
  assert.deepEqual(periodRange('week', true, now), { date_from: '2026-09-25T00:00', date_to: '2026-10-01T23:59' });
  assert.deepEqual(periodRange('month', true, now), { date_from: '2026-09-02T00:00', date_to: '2026-10-01T23:59' });
  assert.deepEqual(periodRange('allTime', true, now), { date_from: '', date_to: '' });
});

test('time filters use explicit UTC and include the entire end minute', () => {
  assert.deepEqual(historyDateQuery({ date_from: '2026-09-22T09:30', date_to: '2026-09-22T23:59', agent_id: '7' }, true), {
    created_from: '2026-09-22T09:30:00Z', created_to: '2026-09-22T23:59:59.999999Z', agent_id: '7',
  });
  assert.deepEqual(historyDateQuery({ date_from: '', date_to: '2026-09-22T10:00' }, true), {
    created_from: '', created_to: '2026-09-22T10:00:59.999999Z',
  });
  assert.deepEqual(historyDateQuery({ date_from: '2026-09-22T10:00', date_to: '' }, true), {
    created_from: '2026-09-22T10:00:00Z', created_to: '',
  });
  assert.deepEqual(historyDateQuery(periodRange('allTime', true), true), { created_from: '', created_to: '' });
});

test('admin presets and requests retain inclusive date-only filters', () => {
  const filters = { ...periodRange('yesterday', false, new Date('2026-10-01T00:15:00Z')), source: 'call' };
  assert.deepEqual(filters, { date_from: '2026-09-30', date_to: '2026-09-30', source: 'call' });
  assert.deepEqual(historyDateQuery(filters, false), filters);
});
