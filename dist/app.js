import { policy, reviewProject } from './engine.js';
import { ledgerFor } from './fixtures.js';

const $ = selector => document.querySelector(selector);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));
const percent = value => value === null ? '资料缺失' : `${Math.round(value * 100)}%`;
const labels = { duplicate:'不通过 · 发现重复', review:'待复核', clear:'通过 · 未发现重复', not_found:'项目未找到', ambiguous:'编号对应多条记录' };
let latestReport = null;
let history = [];
let runId = 0;

$('#rules-content').innerHTML = policy.fields.map(f => `<div class="rule-row"><span>${f.label}</span><span>权重 ${percent(f.weight)}</span></div>`).join('') + `<ol class="rules-list"><li>排除当前记录，以其余示例项目为比对范围。</li><li>四项资料完整且规范化后全部相同：演示判定不通过。</li><li>综合相似度 ≥ ${percent(policy.threshold)}，且至少三项 ≥ 50%：待人工复核。</li><li>当前项目或比对台账有资料缺失：不直接判定通过。</li><li>其余情况：仅在当前完整示例台账中未发现重复。</li></ol>`;
$('#rule-button').addEventListener('click', () => $('#rules-dialog').showModal());
$('#close-rules').addEventListener('click', () => $('#rules-dialog').close());
$('#rules-dialog').addEventListener('click', event => { if (event.target === $('#rules-dialog')) { const rect = event.target.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) event.target.close(); } });

function candidateCard(item, target, index) {
  const p = item.project;
  return `<article class="match-card"><div class="match-head"><div><h3>${escape(p.name)}</h3><div class="code">${escape(p.code)}</div><p>${escape(p.owner)} · ${escape(p.stage)} · ${escape(p.date)}</p></div><div class="score"><strong>${Math.round(item.score * 100)}<small>%</small></strong><span>加权字符相似度</span></div></div><div class="match-reasons">${item.dimensions.map(d => `<span class="reason">${d.label}${d.score === 1 ? '一致' : d.score === null ? '缺失' : `相似 ${percent(d.score)}`}</span>`).join('')}</div><p class="match-note">${item.exact ? '四个维度的文字均一致。请核实是否属于重复申报，或补充不同期次、标段的区别。' : '存在文字相近的资料，请核对建设范围、期次与标段，确认是否为同一项目。'}</p><details class="comparison" ${index === 0 ? 'open' : ''}><summary>逐项对比项目资料</summary><div class="comparison-grid"><div class="table-heading">比对维度</div><div class="table-heading">当前项目</div><div class="table-heading">候选项目</div>${policy.fields.map(f => `<div class="field-name">${f.label}</div><div>${escape(target[f.key] || '未提供')}</div><div>${escape(p[f.key] || '未提供')}</div>`).join('')}</div></details></article>`;
}

function renderReport(report) {
  const r = report;
  if (r.status === 'not_found' || r.status === 'ambiguous') {
    const message = r.status === 'not_found' ? `示例台账中没有找到“${escape(r.code)}”。请使用上方示例编号；真实项目暂未接入。` : `该编号对应 ${r.count} 条台账记录，无法确定当前项目，请先核对台账。`;
    $('#result').innerHTML = `<section class="result-wrap"><div class="result-banner ${r.status}"><div class="result-icon">!</div><div><h2>${labels[r.status]}</h2><p>${message}</p></div></div></section>`;
    return;
  }
  let explanation = r.status === 'duplicate' ? `发现 ${r.candidates.filter(c => c.exact).length} 个四项资料一致的其他项目，演示规则判定不通过。` : r.status === 'clear' ? '在本次完整示例台账中，未发现达到演示规则的重复候选。此结论不代表真实 OA 审核结果。' : '当前信息不足以给出通过／不通过结论，请先核实以下线索。';
  const issues = [
    ...(r.missing.length ? [`当前项目缺少：${r.missing.join('、')}。请补齐资料后重新检查。`] : []),
    ...(r.candidates.length && r.status !== 'duplicate' ? [`发现 ${r.candidates.length} 个疑似重复项目，请核对下方逐项对比。`] : []),
    ...(r.incompleteRecords ? [`比对台账中有 ${r.incompleteRecords} 个其他项目资料不完整，不能据此排除重复。`] : []),
  ];
  const p = r.target;
  $('#result').innerHTML = `<div class="result-wrap"><section class="result-banner ${r.status}"><div class="result-icon">${r.status === 'clear' ? '✓' : '!'}</div><div><h2>${labels[r.status]} <small>（演示）</small></h2><p>${explanation}</p>${issues.length ? `<ul class="issue-list">${issues.map(i => `<li>${escape(i)}</li>`).join('')}</ul>` : ''}</div></section><div class="result-meta"><span>比对 ${r.checkedCount} 个其他示例项目 · 已排除当前记录 · ${escape(policy.version)}</span><button class="quiet" id="export-report">下载查重报告 ↓</button></div><section class="project-summary"><div class="project-title"><div><div class="code">${escape(p.code)}</div><h3>${escape(p.name)}</h3></div><span class="pill">${escape(p.stage)}</span></div><div class="details"><div><label>客户</label>${escape(p.customer)}</div><div><label>地点</label>${escape(p.location || '未提供 · 请补充')}</div><div class="wide"><label>项目内容</label>${escape(p.content)}</div></div></section>${r.candidates.length ? `<div class="matches-heading"><h2>重复候选 <span> / ${r.candidates.length}</span></h2><span>按匹配程度排序</span></div>${r.candidates.map((c, i) => candidateCard(c, p, i)).join('')}` : ''}</div>`;
  $('#export-report').addEventListener('click', exportReport);
}

function exportReport() {
  if (!latestReport?.target) return;
  const r = latestReport;
  const content = ['立项查重报告（虚构示例数据）', `生成时间：${new Date().toISOString()}`, `项目编号：${r.target.code}`, `项目名称：${r.target.name}`, `演示结论：${labels[r.status]}`, `规则：${policy.version}`, `比对范围：${r.checkedCount} 个其他示例项目，排除当前记录`, `当前项目缺失字段：${r.missing.join('、') || '无'}`, `比对范围资料不完整记录数：${r.incompleteRecords}`, '', ...r.candidates.flatMap(c => [`候选：${c.project.code} ${c.project.name}`, `加权字符相似度：${percent(c.score)}（不是重复概率）`, ...c.dimensions.map(d => `${d.label}：当前 ${r.target[d.key] || '未提供'} / 候选 ${c.project[d.key] || '未提供'} / 相似度 ${percent(d.score)}`), '']), '本报告仅用于体验页面和演示规则，不是实际立项审批结果。未连接致远。'].join('\n');
  const url = URL.createObjectURL(new Blob(['\ufeff', content], { type:'text/plain;charset=utf-8' }));
  const link = document.createElement('a'); link.href = url; link.download = `示例查重报告-${r.target.code}.txt`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function renderHistory() {
  $('#history-section').hidden = !history.length;
  $('#history').innerHTML = history.map((entry, index) => `<div class="history-row"><button data-history="${index}">${escape(entry.code)}</button><span class="history-status">${labels[entry.status]} · 演示</span><span>${escape(entry.time)}</span></div>`).join('');
  document.querySelectorAll('[data-history]').forEach(button => button.addEventListener('click', () => { $('#project-code').value = history[Number(button.dataset.history)].code; runReview(); }));
}

async function runReview() {
  const code = $('#project-code').value.trim();
  if (!code) { $('#project-code').setCustomValidity('请输入项目编号'); $('#project-code').reportValidity(); return; }
  $('#project-code').setCustomValidity('');
  const current = ++runId;
  $('#submit-button').disabled = true;
  $('#result').setAttribute('aria-busy', 'true');
  $('#result').innerHTML = '<div class="loading"><span class="spinner"></span>正在比对示例项目资料…</div>';
  try {
    // Yield a paint; no external API or simulated network progress.
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const report = reviewProject(code, ledgerFor(code));
    if (current !== runId) return;
    latestReport = report;
    renderReport(report);
    history = [{ code:report.target?.code ?? code, status:report.status, time:new Date().toLocaleTimeString('zh-CN', { hour12:false }) }, ...history].slice(0, 8);
    renderHistory();
  } catch {
    if (current === runId) { latestReport = null; $('#result').innerHTML = '<section class="result-wrap"><div class="result-banner review"><div><h2>本次检查未完成</h2><p>请刷新页面后重试。本次未产生审核结论。</p></div></div></section>'; }
  } finally {
    if (current === runId) { $('#submit-button').disabled = false; $('#result').setAttribute('aria-busy', 'false'); }
  }
}
$('#review-form').addEventListener('submit', event => { event.preventDefault(); runReview(); });
$('#project-code').addEventListener('input', () => $('#project-code').setCustomValidity(''));
document.querySelectorAll('[data-example]').forEach(button => button.addEventListener('click', () => { $('#project-code').value = button.dataset.example; runReview(); }));
$('#clear-history').addEventListener('click', () => { history = []; renderHistory(); });
