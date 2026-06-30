/**
 * Expects rows shaped like:
 *   { source_stage, target_stage, value, ...dimension columns }
 * Sums `value` across any rows that collapse to the same source→target
 * pair after filtering (e.g. multiple quarters rolled into one view).
 */
export function toSankey(rows, labels = {}) {
  const linkMap = new Map();
  const nodeIds = new Set();

  for (const row of rows) {
    nodeIds.add(row.source_stage);
    nodeIds.add(row.target_stage);
    const key = `${row.source_stage}->${row.target_stage}`;
    linkMap.set(key, (linkMap.get(key) || 0) + Number(row.value));
  }

  const nodes = Array.from(nodeIds, (id) => ({ id, label: labels[id] || id }));
  const links = Array.from(linkMap.entries()).map(([key, value]) => {
    const [source, target] = key.split('->');
    return { source, target, value };
  });

  return { nodes, links };
}
