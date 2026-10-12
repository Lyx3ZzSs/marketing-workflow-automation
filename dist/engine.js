// Demonstration policy only. Calibrate against labelled business cases before use.
export const policy = Object.freeze({
  version: '演示规则 0.1 · 待业务确认',
  threshold: 0.62,
  fields: [
    { key: 'customer', label: '客户', weight: 0.25 },
    { key: 'name', label: '项目名称', weight: 0.25 },
    { key: 'location', label: '地点', weight: 0.20 },
    { key: 'content', label: '项目内容', weight: 0.30 },
  ],
});

export function normalize(value) {
  return String(value ?? '').normalize('NFKC').toLowerCase().replace(/[\s\p{P}\p{S}]/gu, '');
}

export function similarity(a, b) {
  a = normalize(a); b = normalize(b);
  if (!a || !b) return null;
  if (a === b) return 1;
  const grams = value => {
    const chars = Array.from(value);
    return new Set(chars.length < 2 ? chars : chars.slice(0, -1).map((char, i) => char + chars[i + 1]));
  };
  const left = grams(a), right = grams(b);
  return 2 * [...left].filter(value => right.has(value)).length / (left.size + right.size);
}

export function reviewProject(code, projects) {
  const matches = projects.filter(p => normalize(p.code) === normalize(code));
  if (!matches.length) return { status: 'not_found', code };
  if (matches.length !== 1) return { status: 'ambiguous', code, count: matches.length };
  const target = matches[0];
  const missing = policy.fields.filter(f => !normalize(target[f.key])).map(f => f.label);
  // Use immutable record IDs, never the displayed project number, to exclude self.
  const candidates = projects.filter(p => p.id !== target.id);
  const incompleteRecords = candidates.filter(p => policy.fields.some(f => !normalize(p[f.key]))).length;
  const ranked = candidates.map(project => {
    const dimensions = policy.fields.map(field => ({ ...field, score: similarity(target[field.key], project[field.key]) }));
    const score = dimensions.reduce((sum, d) => sum + (d.score ?? 0) * d.weight, 0);
    const exact = dimensions.every(d => d.score === 1);
    // A single identical customer or generic project name cannot establish duplication.
    const eligible = exact || (score >= policy.threshold && dimensions.filter(d => d.score >= 0.5).length >= 3);
    return { project, dimensions, score, exact, eligible };
  }).filter(item => item.eligible).sort((a, b) => Number(b.exact) - Number(a.exact) || b.score - a.score || a.project.code.localeCompare(b.project.code));
  const status = ranked.some(r => r.exact) ? 'duplicate' : missing.length || ranked.length || incompleteRecords ? 'review' : 'clear';
  return { status, target, candidates: ranked, missing, incompleteRecords, checkedCount: candidates.length, policyVersion: policy.version };
}
