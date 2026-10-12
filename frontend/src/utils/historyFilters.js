import { MAX_PAGE } from './callApi';
export { periodRange, historyDateQuery } from './historyDates';

export const PERIODS = ['allTime', 'today', 'yesterday', 'week', 'month'];
export const loadFilterOptions = async (api, query, isCanceled) => {
  const options = [];
  while (!isCanceled()) {
    const result = await api.list({ ...query, limit: MAX_PAGE, offset: options.length });
    const page = Array.isArray(result) ? result : result?.data;
    if (!Array.isArray(page)) throw new Error('Invalid filter options response');
    options.push(...page);
    if (page.length < MAX_PAGE || (result?.count !== undefined && options.length >= result.count)) break;
  }
  return options;
};
