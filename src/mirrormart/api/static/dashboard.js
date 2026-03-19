// ──────────────── Tab 切换 ────────────────
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
  });
});

// ──────────────── API 调用 ────────────────
const API = '';

async function api(path) {
  const res = await fetch(API + path);
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

// ──────────────── 初始化 ────────────────
let allRuns = [];

async function init() {
  try {
    allRuns = await api('/simulations');
    renderRunList();
    populateSelects();
  } catch (e) {
    document.getElementById('run-list').innerHTML = '<p>无法连接 API，请确认服务已启动</p>';
  }
}

function populateSelects() {
  const opts = allRuns.map(r => `<option value="${r.run_id}">${r.run_id} (${r.status})</option>`).join('');
  document.getElementById('detail-select').innerHTML = opts;
  document.getElementById('ab-run-a').innerHTML = opts;
  document.getElementById('ab-run-b').innerHTML = opts;
  document.getElementById('detail-select').onchange = () => loadDetail(document.getElementById('detail-select').value);
  if (allRuns.length) loadDetail(allRuns[0].run_id);
}

// ──────────────── 运行列表 ────────────────
function renderRunList() {
  if (!allRuns.length) {
    document.getElementById('run-list').innerHTML = '<p>暂无运行记录</p>';
    return;
  }
  const statusClass = s => ({ running: 'status-running', completed: 'status-completed', failed: 'status-failed', queued: 'status-queued' }[s] || '');
  let html = '<table><thead><tr><th>运行 ID</th><th>状态</th><th>来源</th><th>操作</th></tr></thead><tbody>';
  allRuns.forEach(r => {
    html += `<tr>
      <td>${r.run_id}</td>
      <td><span class="status ${statusClass(r.status)}">${r.status}</span></td>
      <td>${r.source || '-'}</td>
      <td><button class="btn btn-secondary" onclick="viewRun('${r.run_id}')">查看</button></td>
    </tr>`;
  });
  html += '</tbody></table>';
  document.getElementById('run-list').innerHTML = html;
}

function viewRun(runId) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelector('[data-tab="detail"]').classList.add('active');
  document.getElementById('tab-detail').classList.add('active');
  document.getElementById('detail-select').value = runId;
  loadDetail(runId);
}

// ──────────────── 运行详情 ────────────────
let outcomeChart = null, conversionChart = null, platformChart = null;

async function loadDetail(runId) {
  const el = document.getElementById('detail-content');
  el.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
  try {
    const data = await api(`/simulations/${runId}`);
    renderDetail(data);
  } catch (e) {
    el.innerHTML = '<div class="card"><p>加载失败或运行尚未完成</p></div>';
  }
}

function renderDetail(data) {
  const m = data.metrics || {};
  const cr = m.conversion_rate || {};
  const mp = m.main_product_purchases || {};
  const od = data.outcome_distribution || {};

  let html = `
    <div class="card-row">
      <div class="card"><div class="metric"><div class="value">${data.num_branches || 0}</div><div class="label">分支数</div></div></div>
      <div class="card"><div class="metric"><div class="value">${((cr.mean || 0) * 100).toFixed(1)}%</div><div class="label">平均转化率</div></div></div>
      <div class="card"><div class="metric"><div class="value">${(mp.mean || 0).toFixed(1)}</div><div class="label">平均购买次数</div></div></div>
      <div class="card"><div class="metric"><div class="value">${(m.xhs_likes || {}).mean || 0}</div><div class="label">XHS 平均点赞</div></div></div>
    </div>

    <div class="card-row" style="grid-template-columns:1fr 1fr">
      <div class="card">
        <h3>结局概率分布</h3>
        <div class="chart-container"><canvas id="chart-outcome"></canvas></div>
      </div>
      <div class="card">
        <h3>各分支转化率</h3>
        <div class="chart-container"><canvas id="chart-conversion"></canvas></div>
      </div>
    </div>

    <div class="card">
      <h3>各分支概览</h3>
      <div id="branches-table"></div>
    </div>
  `;
  document.getElementById('detail-content').innerHTML = html;

  // 结局饼图
  if (outcomeChart) outcomeChart.destroy();
  const colors = { '爆款': '#48bb78', '一般': '#ecc94b', '平淡': '#a0aec0' };
  outcomeChart = new Chart(document.getElementById('chart-outcome'), {
    type: 'doughnut',
    data: {
      labels: Object.keys(od),
      datasets: [{ data: Object.values(od).map(v => (v * 100).toFixed(0)), backgroundColor: Object.keys(od).map(k => colors[k] || '#667eea') }]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } } }
  });

  // 转化率柱状图
  if (conversionChart) conversionChart.destroy();
  const vals = cr.values || [];
  conversionChart = new Chart(document.getElementById('chart-conversion'), {
    type: 'bar',
    data: {
      labels: vals.map((_, i) => `Branch ${i}`),
      datasets: [{ label: '转化率', data: vals.map(v => (v * 100).toFixed(1)), backgroundColor: '#667eea' }]
    },
    options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, title: { display: true, text: '%' } } }, plugins: { legend: { display: false } } }
  });

  // 分支表格 — 从 summary 文件获取
  loadBranchTable(data);
}

async function loadBranchTable(data) {
  const runId = data.run_id;
  let html = '<table><thead><tr><th>分支</th><th>结局</th><th>转化率</th><th>XHS点赞</th><th>抖音播放</th><th>微博转发</th><th>淘宝购买</th></tr></thead><tbody>';
  // 尝试从 branch summary 获取，降级到 aggregated values
  const crVals = (data.metrics?.conversion_rate?.values) || [];
  for (let i = 0; i < (data.num_branches || 0); i++) {
    try {
      const branch = await api(`/simulations/${runId}/branch/${i}`);
      html += `<tr>
        <td>Branch ${i}</td>
        <td><span class="status status-${branch.outcome === '爆款' ? 'completed' : branch.outcome === '一般' ? 'queued' : 'failed'}">${branch.outcome}</span></td>
        <td>${(branch.conversion_rate * 100).toFixed(1)}%</td>
        <td>${branch.xhs_likes || 0}</td>
        <td>${branch.douyin_views || 0}</td>
        <td>${branch.weibo_reposts || 0}</td>
        <td>${branch.taobao_purchases || 0}</td>
      </tr>`;
    } catch {
      html += `<tr><td>Branch ${i}</td><td colspan="6">${crVals[i] !== undefined ? (crVals[i] * 100).toFixed(1) + '%' : '-'}</td></tr>`;
    }
  }
  html += '</tbody></table>';
  document.getElementById('branches-table').innerHTML = html;
}

// ──────────────── A/B 对比 ────────────────
let abChart = null;

async function compareAB() {
  const runA = document.getElementById('ab-run-a').value;
  const runB = document.getElementById('ab-run-b').value;
  if (!runA || !runB) return;
  if (runA === runB) { alert('请选择两个不同的运行'); return; }

  document.getElementById('ab-result').innerHTML = '<div class="loading"><div class="spinner"></div></div>';

  try {
    const res = await api(`/simulations/compare?run_a=${runA}&run_b=${runB}`);
    renderABResult(res);
  } catch (e) {
    document.getElementById('ab-result').innerHTML = '<div class="card"><p>对比失败：' + e.message + '</p></div>';
  }
}

function renderABResult(data) {
  const a = data.run_a, b = data.run_b;
  const metrics = data.comparison;

  let rows = '';
  for (const [key, val] of Object.entries(metrics)) {
    const winner = val.diff > 0 ? 'A' : val.diff < 0 ? 'B' : '-';
    const diffStr = val.diff > 0 ? `+${val.diff.toFixed(3)}` : val.diff.toFixed(3);
    rows += `<tr>
      <td>${key}</td>
      <td>${val.a.toFixed(3)}</td>
      <td>${val.b.toFixed(3)}</td>
      <td style="color:${val.diff > 0 ? '#48bb78' : val.diff < 0 ? '#e53e3e' : '#a0aec0'}">${diffStr}</td>
      <td><strong>${winner}</strong></td>
    </tr>`;
  }

  let html = `
    <div class="ab-grid">
      <div class="card ${data.winner === 'A' ? 'ab-winner' : data.winner === 'B' ? 'ab-loser' : ''}">
        <h3>方案 A: ${a}</h3>
        <div class="metric"><div class="value">${((metrics.conversion_rate?.a || 0) * 100).toFixed(1)}%</div><div class="label">转化率</div></div>
      </div>
      <div class="ab-vs">VS</div>
      <div class="card ${data.winner === 'B' ? 'ab-winner' : data.winner === 'A' ? 'ab-loser' : ''}">
        <h3>方案 B: ${b}</h3>
        <div class="metric"><div class="value">${((metrics.conversion_rate?.b || 0) * 100).toFixed(1)}%</div><div class="label">转化率</div></div>
      </div>
    </div>

    <div class="card">
      <h3>指标对比</h3>
      <table>
        <thead><tr><th>指标</th><th>方案 A</th><th>方案 B</th><th>差值(A-B)</th><th>优胜</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>

    <div class="card">
      <h3>转化率分布对比</h3>
      <div class="chart-container"><canvas id="chart-ab"></canvas></div>
    </div>

    <div class="card">
      <h3>结论</h3>
      <p>${data.conclusion}</p>
    </div>
  `;
  document.getElementById('ab-result').innerHTML = html;

  // 转化率分布对比图
  if (abChart) abChart.destroy();
  const aVals = metrics.conversion_rate?.a_values || [];
  const bVals = metrics.conversion_rate?.b_values || [];
  const labels = Array.from({ length: Math.max(aVals.length, bVals.length) }, (_, i) => `Branch ${i}`);
  abChart = new Chart(document.getElementById('chart-ab'), {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: '方案 A', data: aVals.map(v => (v * 100).toFixed(1)), backgroundColor: '#667eea' },
        { label: '方案 B', data: bVals.map(v => (v * 100).toFixed(1)), backgroundColor: '#ed8936' },
      ]
    },
    options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true, title: { display: true, text: '转化率 %' } } } }
  });
}

// ──────────────── 新建模拟 ────────────────
async function createSimulation() {
  const btn = document.getElementById('create-btn');
  btn.disabled = true;
  const status = document.getElementById('create-status');
  status.innerHTML = '<div class="spinner"></div> 正在创建...';

  const body = {
    scenario: document.getElementById('create-scenario').value,
    num_branches: parseInt(document.getElementById('create-branches').value),
    num_steps: parseInt(document.getElementById('create-steps').value),
  };
  const model = document.getElementById('create-model').value.trim();
  if (model) body.model = model;

  try {
    const res = await fetch(API + '/simulations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    status.innerHTML = `<p>已创建: <strong>${data.run_id}</strong> — ${data.message}</p>`;
    pollStatus(data.run_id, status);
  } catch (e) {
    status.innerHTML = `<p style="color:#e53e3e">创建失败: ${e.message}</p>`;
  }
  btn.disabled = false;
}

async function pollStatus(runId, statusEl) {
  const check = async () => {
    try {
      const data = await api(`/simulations/${runId}/status`);
      if (data.status === 'completed') {
        statusEl.innerHTML = `<p style="color:#48bb78">完成! <button class="btn btn-primary" onclick="viewRun('${runId}');init()">查看结果</button></p>`;
        return;
      }
      if (data.status === 'failed') {
        statusEl.innerHTML = `<p style="color:#e53e3e">运行失败</p>`;
        return;
      }
      statusEl.innerHTML = `<div class="spinner"></div> 运行中 (${data.status})...`;
      setTimeout(check, 3000);
    } catch { setTimeout(check, 3000); }
  };
  setTimeout(check, 2000);
}

// 启动
init();
