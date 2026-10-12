export const periodRange = (period, withTime = false, now = new Date()) => {
  if (period === 'allTime') return { date_from: '', date_to: '' };
  const daysAgo = (days) => {
    const date = new Date(now);
    date.setUTCDate(date.getUTCDate() - days);
    return date.toISOString().slice(0, 10);
  };
  return {
    date_from: daysAgo({ today: 0, yesterday: 1, week: 6, month: 29 }[period]) + (withTime ? 'T00:00' : ''),
    date_to: daysAgo(period === 'yesterday' ? 1 : 0) + (withTime ? 'T23:59' : ''),
  };
};

// The picker displays UTC, matching the existing day filters. Include the
// entire selected end minute, including sub-second timestamps at day's end.
export const historyDateQuery = ({ date_from, date_to, ...filters }, withTime) => withTime ? {
  ...filters,
  created_from: date_from ? `${date_from}:00Z` : '',
  created_to: date_to ? `${date_to}:59.999999Z` : '',
} : { ...filters, date_from, date_to };
