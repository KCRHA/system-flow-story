/**
 * Add a new chart by adding an entry here — no new components needed
 * unless you're introducing a genuinely new chart TYPE.
 *
 * Each entry:
 *   id        — unique, used as a DOM anchor
 *   title      — section heading
 *   caption    — one-line description shown under the title
 *   dataset    — filename in /data (long-format JSON)
 *   type       — 'sankey' | 'bar'  (extend CHART_TYPES in ChartBlock.svelte
 *                to add more, e.g. 'line', 'map')
 *   filters    — which dataset columns get a dropdown, in display order.
 *                key must match a column in the dataset; label is shown
 *                to the reader. Omit `filters: []` for an unfiltered chart.
 *   labels     — (sankey only, optional) maps raw stage ids to display names
 */
export const chartConfigs = [
  {
    id: 'system-flow',
    title: "The path from entry to exit",
    caption:
      'Width of each band reflects the number of people moving along that path. Hover any segment for exact counts.',
    dataset: 'system_flow.json',
    type: 'sankey',
    filters: [
      { key: 'region', label: 'Region' },
      { key: 'quarter', label: 'Quarter' }
    ],
    labels: {
      outreach: 'Street Outreach',
      coord_entry: 'Coordinated Entry',
      emergency_shelter: 'Emergency Shelter',
      transitional: 'Transitional Housing',
      rapid_rehouse: 'Rapid Re-Housing',
      perm_housing: 'Permanent Supportive Housing',
      exit_housed: 'Exited to Permanent Housing',
      exit_other: 'Exited, Destination Unknown',
      returned: 'Returned to System'
    }
  },
  {
    id: 'exits-by-program',
    title: 'Exits to permanent housing by program type',
    caption: 'Total exits to permanent housing destinations, by program type.',
    dataset: 'exits_by_program.json',
    type: 'bar',
    filters: [
      { key: 'region', label: 'Region' },
      { key: 'quarter', label: 'Quarter' }
    ]
  }

  // Add chart #3 here, following the same shape. Example:
  // {
  //   id: 'avg-length-of-stay',
  //   title: 'Average length of stay by program type',
  //   caption: 'In days, among exited households.',
  //   dataset: 'length_of_stay.json',
  //   type: 'bar',
  //   filters: [{ key: 'region', label: 'Region' }]
  // }
];
