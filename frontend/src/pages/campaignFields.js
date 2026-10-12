// Field specs for a campaign's dialing schedule (see components/ResourceForm)
// — calling hours (window/weekdays/priority intervals) and retry policy.
// Spread into CampaignsPage's own create/edit form, alongside what to call
// and who with (name/agent/script/dates) — a new campaign gets the backend's
// own defaults for both sections until an operator changes them (the "sparse
// section" convention, the backend/src/application/services/
// campaign.py:157-164).

/** SCampaignCreate/Update's `calling_hours` section. */
export const callingHoursField = () => ({
  name: 'calling_hours',
  labelKey: 'campaigns.fields.callingHours',
  type: 'object',
  nullable: true,
  fields: [
    // Manual timezone deliberately absent (VOAD-33): the backend derives it
    // per call from the client's country, falling back to UTC when a client
    // has no resolvable country — there is nothing left here for an operator
    // to set by hand.
    {
      name: 'start',
      labelKey: 'campaigns.fields.windowStart',
      rangeWith: 'end',
      rangeLabelKey: 'campaigns.fields.callingHoursWindow',
      type: 'time',
      nullable: true,
      hintKey: 'campaigns.fields.windowHint',
    },
    { name: 'end', labelKey: 'campaigns.fields.windowEnd', type: 'time', nullable: true },
    {
      name: 'weekdays',
      labelKey: 'campaigns.fields.weekdays',
      type: 'weekdays',
      nullable: true,
      hintKey: 'campaigns.fields.weekdaysHint',
      dayOptions: [
        { value: 0, labelKey: 'campaigns.fields.weekdayMon' },
        { value: 1, labelKey: 'campaigns.fields.weekdayTue' },
        { value: 2, labelKey: 'campaigns.fields.weekdayWed' },
        { value: 3, labelKey: 'campaigns.fields.weekdayThu' },
        { value: 4, labelKey: 'campaigns.fields.weekdayFri' },
        { value: 5, labelKey: 'campaigns.fields.weekdaySat' },
        { value: 6, labelKey: 'campaigns.fields.weekdaySun' },
      ],
    },
    {
      name: 'priority_intervals',
      labelKey: 'campaigns.fields.priorityIntervals',
      hintKey: 'campaigns.fields.priorityIntervalsHint',
      type: 'list',
      itemFields: [
        {
          name: 'start',
          labelKey: 'campaigns.fields.priorityStart',
          type: 'text',
          required: true,
          placeholderKey: 'campaigns.fields.timeFormatPlaceholder',
        },
        {
          name: 'end',
          labelKey: 'campaigns.fields.priorityEnd',
          type: 'text',
          required: true,
          placeholderKey: 'campaigns.fields.timeFormatPlaceholder',
        },
      ],
      addLabelKey: 'campaigns.fields.addPriorityInterval',
    },
  ],
});

/** SCampaignCreate/Update's `retry` section. */
export const retryField = () => ({
  name: 'retry',
  labelKey: 'campaigns.fields.retry',
  type: 'object',
  nullable: true,
  fields: [
    { name: 'max_attempts', labelKey: 'campaigns.fields.maxAttempts', type: 'number', default: 3 },
    {
      name: 'busy_delay_seconds',
      labelKey: 'campaigns.fields.busyDelay',
      type: 'duration',
      durationUnit: 60,
      default: 300,
      hintKey: 'campaigns.fields.delayHint',
    },
    {
      name: 'no_answer_delay_seconds',
      labelKey: 'campaigns.fields.noAnswerDelay',
      type: 'duration',
      durationUnit: 60,
      default: 3600,
    },
    {
      name: 'failed_delay_seconds',
      labelKey: 'campaigns.fields.failedDelay',
      type: 'duration',
      durationUnit: 60,
      default: 1800,
    },
  ],
});

export const campaignScheduleFields = () => [callingHoursField(), retryField()];
