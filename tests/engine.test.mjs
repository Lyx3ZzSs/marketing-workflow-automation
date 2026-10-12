import test from 'node:test';
import assert from 'node:assert/strict';
import { reviewProject, similarity } from '../dist/engine.js';
import { ledgerFor } from '../dist/fixtures.js';

const record = { id:'1', code:'P1', customer:'客户甲', name:'一号仓库建设', location:'上海市一区', content:'建设一期仓库及装卸平台' };
test('current record never counts as a duplicate', () => {
  const result = reviewProject('P1', [record]);
  assert.equal(result.status, 'clear'); assert.equal(result.checkedCount, 0);
});
test('different project numbers with identical business fields are duplicates', () => {
  const result = reviewProject('P1', [record, { ...record, id:'2', code:'P2' }]);
  assert.equal(result.status, 'duplicate'); assert.equal(result.candidates[0].project.code, 'P2');
});
test('duplicate project numbers cannot select an arbitrary target', () => {
  assert.equal(reviewProject('P1', [record, { ...record, id:'2' }]).status, 'ambiguous');
});
test('missing target fields cannot lead to a pass', () => {
  assert.equal(reviewProject('P1', [{ ...record, location:'' }]).status, 'review');
  assert.equal(similarity('', ''), null);
});
test('incomplete comparison records cannot silently give a clean result', () => {
  assert.equal(reviewProject('P1', [record, { id:'2', code:'P2', customer:'未知', name:'其他', location:'', content:'其他' }]).status, 'review');
});
test('same customer alone does not make separate projects duplicates', () => {
  const result = reviewProject('P1', [record, { id:'2', code:'P2', customer:'客户甲', name:'网站设计', location:'北京市二区', content:'制作门户首页和移动端界面' }]);
  assert.equal(result.status, 'clear');
});
test('case, Unicode width and whitespace normalize without inventing semantic matches', () => {
  assert.equal(similarity('ＡＢＣ 项目', 'abc项目'), 1);
  assert.equal(similarity('建设一期', '建设二期') === 1, false);
});
test('all four user-visible sample scenarios produce their advertised result', () => {
  for (const [suffix, expected] of [['001','duplicate'], ['002','review'], ['003','clear'], ['004','review']]) {
    const code = `DEMO-2026-${suffix}`;
    assert.equal(reviewProject(code, ledgerFor(code)).status, expected);
  }
});
test('unknown project is never reported as clear', () => {
  assert.equal(reviewProject('missing', [record]).status, 'not_found');
});
