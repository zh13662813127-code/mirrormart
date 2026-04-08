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
    loadScenarios();
    loadProfiles();
    loadConfig();
    loadMaterials();
  } catch (e) {
    document.getElementById('run-list').innerHTML = '<p>无法连接 API，请确认服务已启动</p>';
  }
}

function populateSelects() {
  const opts = allRuns.map(r => `<option value="${r.run_id}">${r.run_id} (${r.status})</option>`).join('');
  document.getElementById('detail-select').innerHTML = opts;
  document.getElementById('ab-run-a').innerHTML = opts;
  document.getElementById('ab-run-b').innerHTML = opts;
  document.getElementById('journey-run').innerHTML = opts;
  document.getElementById('sentiment-run').innerHTML = opts;
  document.getElementById('kol-run').innerHTML = opts;
  document.getElementById('temporal-run').innerHTML = opts;
  document.getElementById('network-run').innerHTML = opts;
  document.getElementById('detail-select').onchange = () => {
    const v = document.getElementById('detail-select').value;
    syncRunId(v);
    loadDetail(v);
  };
  if (allRuns.length) {
    syncRunId(allRuns[0].run_id);
    loadDetail(allRuns[0].run_id);
  }
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

// 当前选中的 run_id（全局同步）
let currentRunId = '';

function switchTab(tabName) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  const tabEl = document.querySelector(`[data-tab="${tabName}"]`);
  if (tabEl) tabEl.classList.add('active');
  document.getElementById('tab-' + tabName).classList.add('active');
}

function syncRunId(runId) {
  currentRunId = runId;
  ['detail-select', 'journey-run', 'sentiment-run', 'kol-run', 'temporal-run', 'network-run'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = runId;
  });
}

function viewRun(runId) {
  syncRunId(runId);
  switchTab('detail');
  loadDetail(runId);
}

// 从详情页跳转到分析模块（自动同步 run_id 并加载）
function navigateTo(tabName, loadFn) {
  if (currentRunId) syncRunId(currentRunId);
  switchTab(tabName);
  if (loadFn) loadFn();
}

// ──────────────── 运行详情 ────────────────
let outcomeChart = null, conversionChart = null, competitionChart = null;

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
    ${Object.keys(m.product_competition || {}).length > 1 ? `
    <div class="card">
      <h3>产品竞争分析</h3>
      <div class="chart-container"><canvas id="chart-competition"></canvas></div>
    </div>` : ''}

    <div class="card">
      <h3>深入分析</h3>
      <p style="font-size:13px;color:#718096;margin-bottom:8px">选择一个维度，深入分析当前运行的数据：</p>
      <div class="flow-nav">
        <a class="flow-btn" onclick="navigateTo('journey', loadJourneys)"><span class="flow-icon">🧭</span>个体旅程<span class="flow-arrow">&rarr;</span></a>
        <a class="flow-btn" onclick="navigateTo('sentiment', loadSentiment)"><span class="flow-icon">💬</span>舆情分析<span class="flow-arrow">&rarr;</span></a>
        <a class="flow-btn" onclick="navigateTo('kol', loadKOL)"><span class="flow-icon">📣</span>KOL 分析<span class="flow-arrow">&rarr;</span></a>
        <a class="flow-btn" onclick="navigateTo('temporal', loadTemporal)"><span class="flow-icon">📈</span>时间维度<span class="flow-arrow">&rarr;</span></a>
        <a class="flow-btn" onclick="navigateTo('network', loadNetwork)"><span class="flow-icon">🔗</span>网络图谱<span class="flow-arrow">&rarr;</span></a>
        <a class="flow-btn" onclick="navigateTo('ab')"><span class="flow-icon">⚖️</span>A/B 对比<span class="flow-arrow">&rarr;</span></a>
      </div>
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

  // 产品竞争图
  const pc = m.product_competition || {};
  if (competitionChart) competitionChart.destroy();
  if (Object.keys(pc).length > 1) {
    const pcColors = ['#667eea', '#ed8936', '#48bb78', '#e53e3e', '#ecc94b'];
    const pcLabels = Object.keys(pc);
    const pcData = pcLabels.map(k => pc[k].mean || 0);
    competitionChart = new Chart(document.getElementById('chart-competition'), {
      type: 'bar',
      data: {
        labels: pcLabels,
        datasets: [{ label: '平均购买次数', data: pcData, backgroundColor: pcColors.slice(0, pcLabels.length) }]
      },
      options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true } }, plugins: { legend: { display: false } } }
    });
  }

  loadBranchTable(data);
}

async function loadBranchTable(data) {
  const runId = data.run_id;
  let html = '<table><thead><tr><th>分支</th><th>结局</th><th>转化率</th><th>XHS点赞</th><th>抖音播放</th><th>微博转发</th><th>淘宝购买</th></tr></thead><tbody>';
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

// ──────────────── 新建模拟 + WebSocket 实时进度 ────────────────
let liveWs = null;
let liveState = { totalSteps: 0, totalBranches: 0, completedSteps: {} };

const PLATFORM_LABELS = { xiaohongshu: '小红书', taobao: '淘宝', douyin: '抖音', weibo: '微博' };
const PLATFORM_CLASS = { xiaohongshu: 'platform-xhs', taobao: 'platform-taobao', douyin: 'platform-douyin', weibo: 'platform-weibo' };

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

  liveState = {
    totalSteps: body.num_steps,
    totalBranches: body.num_branches,
    completedSteps: {},
    events: [],
    latestMetrics: null,
  };

  try {
    const res = await fetch(API + '/simulations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    status.innerHTML = `<p>已创建: <strong>${data.run_id}</strong></p>`;
    currentLiveRunId = data.run_id;
    connectWebSocket(data.run_id);
  } catch (e) {
    status.innerHTML = `<p style="color:#e53e3e">创建失败: ${e.message}</p>`;
    btn.disabled = false;
  }
}

function connectWebSocket(runId) {
  const panel = document.getElementById('live-panel');
  panel.style.display = 'block';
  document.getElementById('live-timeline').innerHTML = '';
  updateProgress(0);
  updateLiveStats(null);

  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${proto}//${location.host}/ws/${runId}`;
  liveWs = new WebSocket(wsUrl);

  // 显示暂停按钮
  document.getElementById('pause-btn').style.display = 'inline-block';
  document.getElementById('resume-btn').style.display = 'none';

  liveWs.onopen = () => {
    addTimelineItem('system', '', '', '已连接 WebSocket，等待事件...');
  };

  liveWs.onmessage = (evt) => {
    try {
      const event = JSON.parse(evt.data);
      handleLiveEvent(event, runId);
    } catch { /* ignore parse errors */ }
  };

  liveWs.onclose = () => {
    addTimelineItem('system', '', '', '连接已关闭');
  };

  liveWs.onerror = () => {
    // WebSocket 连接失败，降级到轮询
    addTimelineItem('system', '', '', 'WebSocket 不可用，降级为轮询...');
    pollStatus(runId, document.getElementById('create-status'));
  };
}

function handleLiveEvent(event, runId) {
  if (event.type === 'agent_action') {
    const platform = PLATFORM_LABELS[event.platform] || event.platform;
    const platformCls = PLATFORM_CLASS[event.platform] || '';
    addTimelineItem(
      `S${event.step}`,
      event.agent_id,
      `<span class="${platformCls}">${platform}</span>`,
      `${event.action_type} — ${event.effect || ''}`
    );
  } else if (event.type === 'step_complete') {
    // 每5步汇报一次，记录进度
    const key = `b${event.branch_id}`;
    liveState.completedSteps[key] = event.step;
    liveState.latestMetrics = event.metrics;

    // 计算总进度: 所有分支已完成步数之和 / 总步数之和
    const totalDone = Object.values(liveState.completedSteps).reduce((a, b) => a + b, 0);
    const totalAll = liveState.totalSteps * liveState.totalBranches;
    const pct = totalAll > 0 ? Math.round((totalDone / totalAll) * 100) : 0;
    updateProgress(pct);
    updateLiveStats(event.metrics);

    addTimelineItem(
      `S${event.step}`,
      `Branch ${event.branch_id}`,
      '',
      `步骤完成 — 淘宝购买 ${event.metrics?.taobao?.total_purchases || 0}, XHS点赞 ${event.metrics?.xhs?.total_likes || 0}`
    );
  } else if (event.type === 'run_complete') {
    updateProgress(100);
    addTimelineItem('system', '', '', '模拟完成!');
    document.getElementById('create-status').innerHTML =
      `<p style="color:#48bb78">完成! <button class="btn btn-primary" onclick="viewRun('${runId}');init()">查看结果</button></p>`;
    document.getElementById('create-btn').disabled = false;
    document.getElementById('pause-btn').style.display = 'none';
    document.getElementById('resume-btn').style.display = 'none';
    currentLiveRunId = null;
    if (liveWs) { liveWs.close(); liveWs = null; }
  }
}

function updateProgress(pct) {
  const bar = document.getElementById('progress-bar');
  const text = document.getElementById('progress-text');
  bar.style.width = Math.max(pct, 3) + '%';
  text.textContent = pct + '%';
}

function updateLiveStats(metrics) {
  const el = document.getElementById('live-stats');
  if (!metrics) {
    el.innerHTML = '<div class="live-stat"><div class="val">-</div><div class="lbl">等待数据</div></div>';
    return;
  }
  el.innerHTML = `
    <div class="live-stat"><div class="val">${metrics.xhs?.total_posts || 0}</div><div class="lbl">XHS 帖子</div></div>
    <div class="live-stat"><div class="val">${metrics.xhs?.total_likes || 0}</div><div class="lbl">XHS 点赞</div></div>
    <div class="live-stat"><div class="val">${metrics.douyin?.total_views || 0}</div><div class="lbl">抖音播放</div></div>
    <div class="live-stat"><div class="val">${metrics.weibo?.total_reposts || 0}</div><div class="lbl">微博转发</div></div>
    <div class="live-stat"><div class="val">${metrics.taobao?.total_purchases || 0}</div><div class="lbl">淘宝购买</div></div>
    <div class="live-stat"><div class="val">¥${(metrics.taobao?.total_revenue || 0).toFixed(0)}</div><div class="lbl">淘宝营收</div></div>
  `;
}

function addTimelineItem(step, agent, platform, action) {
  const el = document.getElementById('live-timeline');
  const item = document.createElement('div');
  item.className = 'timeline-item';
  item.innerHTML = `
    <div class="timeline-step">${step}</div>
    <div class="timeline-agent">${agent}</div>
    <div class="timeline-platform">${platform}</div>
    <div class="timeline-action">${action}</div>
  `;
  el.prepend(item);
  // 限制时间线条目数量
  while (el.children.length > 200) {
    el.removeChild(el.lastChild);
  }
}

// 降级轮询（WebSocket 不可用时使用）
async function pollStatus(runId, statusEl) {
  const check = async () => {
    try {
      const data = await api(`/simulations/${runId}/status`);
      if (data.status === 'completed') {
        statusEl.innerHTML = `<p style="color:#48bb78">完成! <button class="btn btn-primary" onclick="viewRun('${runId}');init()">查看结果</button></p>`;
        updateProgress(100);
        document.getElementById('create-btn').disabled = false;
        return;
      }
      if (data.status === 'failed') {
        statusEl.innerHTML = `<p style="color:#e53e3e">运行失败</p>`;
        document.getElementById('create-btn').disabled = false;
        return;
      }
      statusEl.innerHTML = `<div class="spinner"></div> 运行中 (${data.status})...`;
      setTimeout(check, 3000);
    } catch { setTimeout(check, 3000); }
  };
  setTimeout(check, 2000);
}

// ──────────────── 物料管理 ────────────────

async function uploadMaterial() {
  const platform = document.getElementById('mat-platform').value;
  const title = document.getElementById('mat-title').value.trim();
  const content = document.getElementById('mat-content').value.trim();
  const tags = document.getElementById('mat-tags').value.trim();
  const fileInput = document.getElementById('mat-file');
  const status = document.getElementById('mat-status');

  if (!content && !title) {
    status.innerHTML = '<span style="color:#e53e3e">请至少填写标题或文案</span>';
    return;
  }

  const formData = new FormData();
  if (fileInput.files.length > 0) formData.append('file', fileInput.files[0]);

  const params = new URLSearchParams({ platform, title, content, tags });

  try {
    const res = await fetch(`/simulations/materials/upload?${params}`, { method: 'POST', body: formData });
    const data = await res.json();
    if (res.ok) {
      status.innerHTML = '<span style="color:#48bb78">物料已添加</span>';
      document.getElementById('mat-title').value = '';
      document.getElementById('mat-content').value = '';
      document.getElementById('mat-tags').value = '';
      fileInput.value = '';
      loadMaterials();
    } else {
      status.innerHTML = `<span style="color:#e53e3e">上传失败: ${data.detail || '未知错误'}</span>`;
    }
  } catch (e) {
    status.innerHTML = `<span style="color:#e53e3e">上传失败: ${e.message}</span>`;
  }
}

async function loadMaterials() {
  try {
    const materials = await api('/simulations/materials');
    const el = document.getElementById('mat-list');
    if (!materials.length) { el.innerHTML = ''; return; }
    const platformName = { xiaohongshu: '小红书', douyin: '抖音', weibo: '微博' };
    el.innerHTML = `
      <table><thead><tr><th>平台</th><th>标题</th><th>文案</th><th>标签</th><th>附件</th><th>操作</th></tr></thead><tbody>
      ${materials.map(m => `<tr>
        <td><span class="tag platform-${m.platform === 'xiaohongshu' ? 'xhs' : m.platform}">${platformName[m.platform] || m.platform}</span></td>
        <td>${m.title || '-'}</td>
        <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${m.content || '-'}</td>
        <td>${(m.tags || []).map(t => `<span class="tag">${t}</span>`).join('')}</td>
        <td>${m.file_path ? '有' : '-'}</td>
        <td><button class="btn btn-sm btn-danger" onclick="deleteMaterial('${m.id}')">删除</button></td>
      </tr>`).join('')}
      </tbody></table>`;
  } catch { /* ignore */ }
}

async function deleteMaterial(id) {
  if (!confirm('确定删除此物料？')) return;
  try {
    await fetch(`/simulations/materials/${id}`, { method: 'DELETE' });
    loadMaterials();
  } catch { /* ignore */ }
}

// ──────────────── 暂停 / 恢复 ────────────────

let currentLiveRunId = null;

async function pauseSimulation() {
  if (!currentLiveRunId) return;
  try {
    await fetch(`/simulations/${currentLiveRunId}/pause`, { method: 'POST' });
    document.getElementById('pause-btn').style.display = 'none';
    document.getElementById('resume-btn').style.display = 'inline-block';
    addTimelineItem('system', '', '', '模拟已暂停');
  } catch (e) {
    addTimelineItem('system', '', '', '暂停失败: ' + e.message);
  }
}

async function resumeSimulation() {
  if (!currentLiveRunId) return;
  try {
    await fetch(`/simulations/${currentLiveRunId}/resume`, { method: 'POST' });
    document.getElementById('resume-btn').style.display = 'none';
    document.getElementById('pause-btn').style.display = 'inline-block';
    addTimelineItem('system', '', '', '模拟已恢复');
  } catch (e) {
    addTimelineItem('system', '', '', '恢复失败: ' + e.message);
  }
}

// ──────────────── CSV 导出 ────────────────

function exportCSV() {
  const runId = document.getElementById('detail-select').value;
  if (!runId) return;
  window.open(`/simulations/${runId}/export`, '_blank');
}

// ──────────────── 分析报告 ────────────────

async function showReport() {
  const runId = document.getElementById('detail-select').value;
  if (!runId) return;
  const el = document.getElementById('detail-content');

  try {
    const data = await api(`/simulations/${runId}/report`);
    // 简单 Markdown → HTML 转换（表格+标题+粗体+列表+引用+分隔线）
    const html = markdownToHtml(data.report);
    el.innerHTML = `
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
          <h3>分析报告</h3>
          <button class="btn btn-secondary" onclick="loadDetail('${runId}')">返回图表</button>
        </div>
        <div class="report-content">${html}</div>
      </div>`;
  } catch (e) {
    el.innerHTML = '<div class="card"><p>报告不存在或加载失败</p></div>';
  }
}

function markdownToHtml(md) {
  let html = md
    // 表格
    .replace(/^\|(.+)\|$/gm, (match) => {
      const cells = match.split('|').filter(c => c.trim());
      return '<tr>' + cells.map(c => {
        const content = c.trim();
        if (/^[-:]+$/.test(content)) return null; // separator row
        return `<td>${content}</td>`;
      }).filter(Boolean).join('') + '</tr>';
    })
    // 标题
    .replace(/^##### (.+)$/gm, '<h5>$1</h5>')
    .replace(/^#### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^### (.+)$/gm, '<h3 style="margin-top:16px">$1</h3>')
    .replace(/^## (.+)$/gm, '<h2 style="margin-top:20px;font-size:18px">$1</h2>')
    .replace(/^# (.+)$/gm, '<h1 style="font-size:22px">$1</h1>')
    // 分隔线
    .replace(/^---$/gm, '<hr style="margin:16px 0;border:none;border-top:1px solid #e2e8f0">')
    // 粗体
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // 代码
    .replace(/`([^`]+)`/g, '<code style="background:#f7fafc;padding:1px 4px;border-radius:3px;font-size:12px">$1</code>')
    // 引用
    .replace(/^> (.+)$/gm, '<blockquote style="border-left:3px solid #667eea;padding-left:12px;color:#718096;margin:8px 0">$1</blockquote>')
    // 列表
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    // 换行
    .replace(/\n\n/g, '<br>');

  // 包裹连续 <tr> 为 table
  html = html.replace(/((?:<tr>.*?<\/tr>\s*)+)/g, (match) => {
    // 跳过只有分隔符的行
    const rows = match.trim().split('\n').filter(r => r.includes('<td>'));
    if (rows.length === 0) return '';
    const firstRow = rows[0].replace(/<td>/g, '<th>').replace(/<\/td>/g, '</th>');
    const rest = rows.slice(1).join('\n');
    return `<table>${firstRow}${rest}</table>`;
  });

  // 包裹连续 <li> 为 ul
  html = html.replace(/((?:<li>.*?<\/li>\s*)+)/g, '<ul style="padding-left:20px;margin:8px 0">$1</ul>');

  return html;
}

// ──────────────── 个体旅程 ────────────────

let journeyCharts = [];

async function loadJourneys() {
  const runId = document.getElementById('journey-run').value;
  const branchId = document.getElementById('journey-branch').value;
  const el = document.getElementById('journey-content');
  el.innerHTML = '<div class="loading"><div class="spinner"></div></div>';

  // 清理之前的图表
  journeyCharts.forEach(c => c.destroy());
  journeyCharts = [];

  try {
    const data = await api(`/simulations/${runId}/journeys?branch_id=${branchId}`);
    renderJourneys(data);
  } catch (e) {
    el.innerHTML = '<div class="card"><p>加载失败: ' + e.message + '</p></div>';
  }
}

function renderJourneys(data) {
  const el = document.getElementById('journey-content');
  const journeys = data.journeys;
  let html = '';

  for (const [agentId, journey] of Object.entries(journeys)) {
    const finalIntent = journey.final_state?.purchase_intent || 0;
    const intentClass = finalIntent > 0.6 ? 'tag-intent-high' : 'tag-intent';
    const hasPurchase = journey.steps.some(s => s.action_type === 'purchase');

    html += `<div class="journey-card">
      <div class="journey-header">
        <h4>${journey.persona_name} (${agentId})</h4>
        <div class="journey-final">
          <span class="tag tag-interest">兴趣 ${(journey.final_state?.interest_level || 0).toFixed(2)}</span>
          <span class="tag ${intentClass}">购买意向 ${finalIntent.toFixed(2)}</span>
          ${hasPurchase ? '<span class="tag tag-intent-high">已购买</span>' : ''}
        </div>
      </div>
      <div class="journey-chart"><canvas id="chart-journey-${agentId}"></canvas></div>
      <div class="journey-steps">`;

    for (const step of journey.steps) {
      const platLabel = PLATFORM_LABELS[step.platform] || step.platform;
      const platCls = PLATFORM_CLASS[step.platform] || '';
      const actionCls = step.action_type === 'purchase' ? 'action-purchase' :
                        step.action_type === 'skip' ? 'action-skip' : '';
      html += `<div class="journey-step ${actionCls}">
        <div class="step-num">S${step.step}</div>
        <div class="step-detail">
          <span class="${platCls}">${platLabel}</span> <strong>${step.action_type}</strong> ${step.effect || ''}
          ${step.thinking ? `<div class="step-thinking">${step.thinking}</div>` : ''}
        </div>
      </div>`;
    }
    html += '</div></div>';
  }

  el.innerHTML = html;

  // 画每个 agent 的意向曲线
  for (const [agentId, journey] of Object.entries(journeys)) {
    const canvas = document.getElementById(`chart-journey-${agentId}`);
    if (!canvas) continue;
    const labels = journey.steps.map(s => `S${s.step}`);
    const intentData = journey.steps.map(s => s.purchase_intent);
    const interestData = journey.steps.map(s => s.interest_level);
    const chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [
          { label: '购买意向', data: intentData, borderColor: '#48bb78', backgroundColor: 'rgba(72,187,120,0.1)', fill: true, tension: 0.3, pointRadius: 3 },
          { label: '兴趣值', data: interestData, borderColor: '#667eea', backgroundColor: 'rgba(102,126,234,0.1)', fill: true, tension: 0.3, pointRadius: 3 },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        scales: { y: { min: 0, max: 1, ticks: { stepSize: 0.2 } } },
        plugins: { legend: { position: 'right', labels: { boxWidth: 12, font: { size: 11 } } } },
      },
    });
    journeyCharts.push(chart);
  }
}

// ──────────────── 场景与人设管理 ────────────────

async function loadScenarios() {
  try {
    const scenarios = await api('/scenarios');
    // 更新创建表单的场景下拉
    const select = document.getElementById('create-scenario');
    select.innerHTML = scenarios.map(s =>
      `<option value="${s.file}">${s.name}</option>`
    ).join('');

    // 更新配置页面的场景列表
    const el = document.getElementById('scenario-list');
    if (!scenarios.length) { el.innerHTML = '<p>暂无场景</p>'; return; }
    let html = '<table><thead><tr><th>名称</th><th>步数</th><th>分支</th><th>描述</th></tr></thead><tbody>';
    scenarios.forEach(s => {
      html += `<tr>
        <td><strong>${s.name}</strong></td>
        <td>${s.num_steps || '-'}</td>
        <td>${s.num_branches || '-'}</td>
        <td style="font-size:12px;color:#718096">${(s.description || '').slice(0, 60)}</td>
      </tr>`;
    });
    html += '</tbody></table>';
    el.innerHTML = html;
  } catch {
    document.getElementById('scenario-list').innerHTML = '<p>加载失败</p>';
  }
}

async function loadProfiles() {
  try {
    const profiles = await api('/profiles');
    const el = document.getElementById('profile-list');
    if (!profiles.length) { el.innerHTML = '<p>暂无人设</p>'; return; }
    let html = '<table><thead><tr><th>名称</th><th>决策风格</th><th>价格敏感</th><th>描述</th></tr></thead><tbody>';
    profiles.forEach(p => {
      html += `<tr>
        <td><strong>${p.name}</strong></td>
        <td>${p.decision_style || '-'}</td>
        <td>${p.price_sensitivity || '-'}</td>
        <td style="font-size:12px;color:#718096">${(p.description || '').slice(0, 50)}</td>
      </tr>`;
    });
    html += '</tbody></table>';
    el.innerHTML = html;
  } catch {
    document.getElementById('profile-list').innerHTML = '<p>加载失败</p>';
  }
}

async function uploadScenario() {
  const fileInput = document.getElementById('scenario-file');
  const statusEl = document.getElementById('upload-status');
  if (!fileInput.files.length) {
    statusEl.innerHTML = '<p style="color:#e53e3e">请先选择文件</p>';
    return;
  }
  const formData = new FormData();
  formData.append('file', fileInput.files[0]);
  statusEl.innerHTML = '<div class="spinner"></div> 上传中...';

  try {
    const res = await fetch(API + '/scenarios/upload', { method: 'POST', body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '上传失败');
    statusEl.innerHTML = `<p style="color:#48bb78">上传成功: ${data.name}</p>`;
    fileInput.value = '';
    loadScenarios();
  } catch (e) {
    statusEl.innerHTML = `<p style="color:#e53e3e">${e.message}</p>`;
  }
}

// ──────────────── 模型提供商管理（cc-switch 风格） ────────────────

async function loadConfig() {
  try {
    const [config, providers] = await Promise.all([api('/config'), api('/config/providers')]);
    const badge = document.getElementById('active-model-badge');
    if (config.active_provider) {
      badge.textContent = `${config.active_provider.name} (${config.model})`;
      badge.style.background = config.active_provider.color + '22';
      badge.style.color = config.active_provider.color;
    } else if (config.model) {
      badge.textContent = config.model;
    }
    renderProviders(providers);
  } catch (e) {
    document.getElementById('provider-list').innerHTML = '<p>加载失败</p>';
  }
}

function renderProviders(providers) {
  const el = document.getElementById('provider-list');
  if (!providers.length) {
    el.innerHTML = '<p style="color:#a0aec0;grid-column:1/-1">暂无提供商，点击下方按钮添加</p>';
    return;
  }
  el.innerHTML = providers.map(p => `
    <div class="provider-card ${p.active ? 'provider-active' : ''}" style="border-left:4px solid ${p.color}">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
        <div class="provider-icon" style="background:${p.color}">${p.icon}</div>
        <div>
          <div style="font-weight:600;font-size:14px">${p.name}</div>
          <div style="font-size:11px;color:#718096">${p.model}</div>
        </div>
      </div>
      <div style="font-size:11px;color:#a0aec0;margin-bottom:8px">
        ${p.api_key_display ? 'Key: ' + p.api_key_display : '<span style="color:#e53e3e">未设置 Key</span>'}
      </div>
      <div style="display:flex;gap:6px">
        ${p.active
          ? '<span style="font-size:11px;color:#48bb78;font-weight:600">已激活</span>'
          : `<button class="btn-sm btn-primary" onclick="activateProvider('${p.id}')">启用</button>`}
        <button class="btn-sm btn-secondary" onclick="editProvider('${p.id}')">编辑</button>
        <button class="btn-sm btn-danger" onclick="deleteProvider('${p.id}','${p.name}')">删除</button>
      </div>
    </div>
  `).join('');
}

async function showPresets() {
  const panel = document.getElementById('preset-panel');
  panel.style.display = 'block';
  try {
    const presets = await api('/config/presets');
    document.getElementById('preset-grid').innerHTML = presets.map(p => `
      <div class="provider-card" style="border-left:4px solid ${p.color};cursor:pointer"
           onclick="addFromPreset(${JSON.stringify(p).replace(/"/g,'&quot;')})">
        <div style="display:flex;align-items:center;gap:8px">
          <div class="provider-icon" style="background:${p.color}">${p.icon}</div>
          <div>
            <div style="font-weight:600">${p.name}</div>
            <div style="font-size:11px;color:#718096">${p.model}</div>
          </div>
        </div>
        <div style="font-size:11px;color:#a0aec0;margin-top:6px">${p.api_base}</div>
      </div>
    `).join('');
  } catch {}
}

function addFromPreset(preset) {
  document.getElementById('preset-panel').style.display = 'none';
  document.getElementById('provider-form').style.display = 'block';
  document.getElementById('provider-form-title').textContent = `添加 ${preset.name}`;
  document.getElementById('pf-id').value = preset.id;
  document.getElementById('pf-name').value = preset.name;
  document.getElementById('pf-model').value = preset.model;
  document.getElementById('pf-api-base').value = preset.api_base || '';
  document.getElementById('pf-api-key').value = '';
  document.getElementById('pf-max-tokens').value = preset.max_tokens || 1024;
  document.getElementById('pf-temperature').value = preset.temperature || 0.8;
  document.getElementById('pf-icon').value = preset.icon || '+';
  document.getElementById('pf-color').value = preset.color || '#94a3b8';
}

function showCustomProvider() {
  document.getElementById('provider-form').style.display = 'block';
  document.getElementById('provider-form-title').textContent = '添加自定义提供商';
  ['pf-id','pf-name','pf-model','pf-api-base','pf-api-key'].forEach(id => document.getElementById(id).value = '');
  document.getElementById('pf-max-tokens').value = 1024;
  document.getElementById('pf-temperature').value = 0.8;
  document.getElementById('pf-icon').value = '+';
  document.getElementById('pf-color').value = '#94a3b8';
}

async function editProvider(id) {
  try {
    const providers = await api('/config/providers');
    const p = providers.find(x => x.id === id);
    if (!p) return;
    document.getElementById('provider-form').style.display = 'block';
    document.getElementById('provider-form-title').textContent = `编辑 ${p.name}`;
    document.getElementById('pf-id').value = p.id;
    document.getElementById('pf-name').value = p.name;
    document.getElementById('pf-model').value = p.model;
    document.getElementById('pf-api-base').value = p.api_base || '';
    document.getElementById('pf-api-key').value = '';
    document.getElementById('pf-api-key').placeholder = p.api_key_display || 'sk-...';
    document.getElementById('pf-max-tokens').value = p.max_tokens || 1024;
    document.getElementById('pf-temperature').value = p.temperature || 0.8;
    document.getElementById('pf-icon').value = p.icon || '+';
    document.getElementById('pf-color').value = p.color || '#94a3b8';
  } catch {}
}

async function saveProvider() {
  const body = {
    id: document.getElementById('pf-id').value.trim(),
    name: document.getElementById('pf-name').value.trim(),
    model: document.getElementById('pf-model').value.trim(),
    api_base: document.getElementById('pf-api-base').value.trim(),
    api_key: document.getElementById('pf-api-key').value.trim(),
    max_tokens: parseInt(document.getElementById('pf-max-tokens').value) || 1024,
    temperature: parseFloat(document.getElementById('pf-temperature').value) || 0.8,
    icon: document.getElementById('pf-icon').value.trim() || '+',
    color: document.getElementById('pf-color').value,
  };
  if (!body.id || !body.name || !body.model) {
    document.getElementById('provider-form-status').textContent = '请填写必填项';
    return;
  }
  try {
    const res = await fetch(API + '/config/providers', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '保存失败');
    document.getElementById('provider-form-status').textContent = data.message;
    document.getElementById('provider-form').style.display = 'none';
    loadConfig();
  } catch (e) {
    document.getElementById('provider-form-status').textContent = e.message;
  }
}

async function activateProvider(id) {
  try {
    const res = await fetch(API + `/config/providers/${id}/activate`, {method: 'POST'});
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail);
    loadConfig();
  } catch (e) { alert(e.message); }
}

async function deleteProvider(id, name) {
  if (!confirm(`确定删除 ${name}?`)) return;
  try {
    await fetch(API + `/config/providers/${id}`, {method: 'DELETE'});
    loadConfig();
  } catch {}
}

// ──────────────── Agent 网络图谱（3D 力导向图） ────────────────

let graph3d = null;

async function loadNetwork() {
  const runId = document.getElementById('network-run').value;
  const branchId = document.getElementById('network-branch').value;
  if (!runId) return;

  const graphEl = document.getElementById('network-graph');
  graphEl.innerHTML = '<div class="loading"><div class="spinner"></div><p>构建网络图...</p></div>';

  try {
    const data = await api(`/simulations/${runId}/journeys?branch_id=${branchId}`);
    buildNetworkGraph(data.journeys, graphEl);
  } catch (e) {
    graphEl.innerHTML = `<p style="color:#e53e3e">加载失败: ${e.message}</p>`;
  }
}

function buildNetworkGraph(journeys, container) {
  container.innerHTML = '';
  const width = container.clientWidth || 700;
  const height = 500;

  const agentIds = Object.keys(journeys);
  const nodes = agentIds.map(id => {
    const j = journeys[id];
    const purchased = j.steps.some(s => s.action_type === 'purchase');
    const intent = j.final_state?.purchase_intent || 0;
    return {
      id, name: j.persona_name, purchased, intent,
      total_actions: j.total_actions,
      interest: j.final_state?.interest_level || 0,
      steps: j.steps,
    };
  });

  // 推断边：共同 target_id（强）+ 同步同平台（弱）
  const coMap = {};
  agentIds.forEach(id => {
    (journeys[id].steps || []).forEach(s => {
      if (s.target_id) {
        const k = `t:${s.target_id}`;
        (coMap[k] = coMap[k] || []).push(id);
      }
      if (s.platform && s.step !== undefined) {
        const k = `sp:${s.step}:${s.platform}`;
        (coMap[k] = coMap[k] || []).push(id);
      }
    });
  });
  const edgeWeights = {};
  Object.entries(coMap).forEach(([key, agents]) => {
    const unique = [...new Set(agents)];
    const w = key.startsWith('t:') ? 1 : 0.3;
    for (let i = 0; i < unique.length; i++)
      for (let j = i + 1; j < unique.length; j++) {
        const ek = [unique[i], unique[j]].sort().join('|');
        edgeWeights[ek] = (edgeWeights[ek] || 0) + w;
      }
  });
  const links = Object.entries(edgeWeights).map(([key, weight]) => {
    const [source, target] = key.split('|');
    return { source, target, weight };
  });

  if (nodes.every(n => n.total_actions === 0)) {
    container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:500px;background:#0b0f1a;border-radius:8px;color:rgba(255,255,255,0.4);font-size:14px">该运行无行为数据，请选择其他运行</div>';
    return;
  }

  // 清理旧图
  if (graph3d) { graph3d._destructor && graph3d._destructor(); graph3d = null; }

  // 3D 力导向图
  const maxActions = Math.max(...nodes.map(n => n.total_actions), 1);

  graph3d = ForceGraph3D()(container)
    .width(width)
    .height(height)
    .backgroundColor('#0b0f1a')
    .graphData({ nodes, links })
    // 节点：用 sprite 文字，大小和亮度区分状态
    .nodeThreeObject(node => {
      const sprite = new SpriteText(node.name);
      const size = 3 + (node.total_actions / maxActions) * 5;
      sprite.textHeight = size;
      sprite.fontWeight = node.purchased ? '700' : '400';
      sprite.color = node.purchased ? '#ffffff'
        : node.intent > 0.5 ? 'rgba(255,255,255,0.85)'
        : 'rgba(255,255,255,0.5)';
      sprite.backgroundColor = false;
      sprite.padding = 1;
      return sprite;
    })
    .nodeLabel(node => `${node.name} | ${node.total_actions}次行为 | ${node.purchased ? '已购买' : Math.round(node.intent * 100) + '%意向'}`)
    // 连线
    .linkWidth(link => Math.max(0.2, Math.min(link.weight * 0.4, 2)))
    .linkOpacity(0.3)
    .linkColor(() => '#667eea')
    // 点击节点
    .onNodeClick(node => showNodeDetail(node))
    // 力参数
    .d3Force('charge', d3.forceManyBody().strength(-120))
    .d3Force('link', d3.forceLink().distance(60).strength(l => Math.min(l.weight * 0.05, 0.3)));

  // 初始视角稍微拉远
  graph3d.cameraPosition({ z: 300 });
}

function showNodeDetail(d) {
  const el = document.getElementById('network-detail');
  const platformCounts = {};
  const actionCounts = {};
  (d.steps || []).forEach(s => {
    platformCounts[s.platform] = (platformCounts[s.platform] || 0) + 1;
    actionCounts[s.action_type] = (actionCounts[s.action_type] || 0) + 1;
  });

  el.innerHTML = `
    <h3 style="margin-bottom:4px">${d.name}</h3>
    <div style="font-size:12px;color:#718096;margin-bottom:12px">${d.id}</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px">
      <div class="mini-stat"><div class="stat-value" style="color:${d.purchased ? '#48bb78' : '#4299e1'}">${d.purchased ? '已购买' : '未购买'}</div></div>
      <div class="mini-stat"><div class="stat-value">${d.total_actions}</div><div class="stat-label">总行为</div></div>
      <div class="mini-stat"><div class="stat-value">${(d.intent * 100).toFixed(0)}%</div><div class="stat-label">购买意向</div></div>
      <div class="mini-stat"><div class="stat-value">${(d.interest * 100).toFixed(0)}%</div><div class="stat-label">兴趣度</div></div>
    </div>
    <h4 style="font-size:13px;margin-bottom:6px">平台分布</h4>
    <div style="margin-bottom:12px">${Object.entries(platformCounts).map(([p,c]) =>
      `<span class="tag platform-${p === 'xiaohongshu' ? 'xhs' : p}">${p} ${c}</span>`
    ).join(' ')}</div>
    <h4 style="font-size:13px;margin-bottom:6px">行为分布</h4>
    <div style="margin-bottom:12px">${Object.entries(actionCounts).sort((a,b) => b[1]-a[1]).slice(0,6).map(([a,c]) =>
      `<span class="tag">${a} ${c}</span>`
    ).join(' ')}</div>
    <h4 style="font-size:13px;margin-bottom:6px">最近行为</h4>
    <div style="max-height:180px;overflow-y:auto">${(d.steps || []).slice(-8).reverse().map(s =>
      `<div style="font-size:11px;padding:4px 0;border-bottom:1px solid #edf2f7">
        <span style="color:#718096">Step ${s.step}</span>
        <span class="tag platform-${s.platform === 'xiaohongshu' ? 'xhs' : s.platform}" style="font-size:10px">${s.platform}</span>
        <strong>${s.action_type}</strong>
        <div style="color:#a0aec0;margin-top:2px">${(s.effect || '').slice(0, 60)}</div>
      </div>`
    ).join('')}</div>
  `;
}

// ──────────────── 舆情分析 ────────────────

let sentimentChart = null;

async function loadSentiment() {
  const runId = document.getElementById('sentiment-run').value;
  const branchId = document.getElementById('sentiment-branch').value;
  const container = document.getElementById('sentiment-content');
  if (!runId) { container.innerHTML = '<p>请选择运行</p>'; return; }

  try {
    const data = await api(`/simulations/${runId}/sentiment?branch_id=${branchId}`);
    renderSentiment(data.sentiment, container);
  } catch (e) {
    container.innerHTML = `<p>加载失败: ${e.message}</p>`;
  }
}

function renderSentiment(sentiment, container) {
  if (!sentiment || !sentiment.total_analyzed) {
    container.innerHTML = '<div class="card"><p>暂无情感分析数据</p></div>';
    return;
  }

  const polLabel = sentiment.overall_polarity > 0.2 ? '正面' :
                   (sentiment.overall_polarity < -0.2 ? '负面' : '中性');
  const polColor = sentiment.overall_polarity > 0.2 ? '#48bb78' :
                   (sentiment.overall_polarity < -0.2 ? '#e53e3e' : '#a0aec0');

  let html = `
    <div class="card-row" style="grid-template-columns:1fr 1fr 1fr">
      <div class="card">
        <h3>整体情感</h3>
        <div class="stat-value" style="color:${polColor}">${sentiment.overall_polarity.toFixed(3)}</div>
        <div class="stat-label">${polLabel} (共分析 ${sentiment.total_analyzed} 条)</div>
      </div>
      <div class="card">
        <h3>各平台情感</h3>
        <table class="data-table"><tr><th>平台</th><th>正面</th><th>负面</th><th>中性</th><th>净值</th></tr>`;

  const pfSent = sentiment.platform_sentiment || {};
  for (const [pf, counts] of Object.entries(pfSent)) {
    const ratio = counts.sentiment_ratio || 0;
    const ratioColor = ratio > 0 ? '#48bb78' : (ratio < 0 ? '#e53e3e' : '#a0aec0');
    html += `<tr><td>${pf}</td><td>${counts.positive}</td><td>${counts.negative}</td>
             <td>${counts.neutral}</td><td style="color:${ratioColor}">${ratio.toFixed(3)}</td></tr>`;
  }
  html += `</table></div>
      <div class="card">
        <h3>情感趋势</h3>
        <canvas id="sentiment-trend-chart" width="400" height="200"></canvas>
      </div>
    </div>`;

  // 正面/负面内容展示
  const topPos = sentiment.top_positive || [];
  const topNeg = sentiment.top_negative || [];
  if (topPos.length || topNeg.length) {
    html += '<div class="card-row" style="grid-template-columns:1fr 1fr">';
    html += '<div class="card"><h3>最正面内容</h3>';
    for (const r of topPos) {
      html += `<div class="journey-step" style="border-left-color:#48bb78">
        <strong>${r.agent_id}</strong> (${r.platform}/${r.action_type}) 极性: ${r.polarity.toFixed(3)}<br>
        <span style="color:#718096">${r.text_preview}</span></div>`;
    }
    html += '</div><div class="card"><h3>最负面内容</h3>';
    for (const r of topNeg) {
      html += `<div class="journey-step" style="border-left-color:#e53e3e">
        <strong>${r.agent_id}</strong> (${r.platform}/${r.action_type}) 极性: ${r.polarity.toFixed(3)}<br>
        <span style="color:#718096">${r.text_preview}</span></div>`;
    }
    html += '</div></div>';
  }

  container.innerHTML = html;

  // 绘制趋势图
  const trend = sentiment.trend || [];
  if (trend.length) {
    const ctx = document.getElementById('sentiment-trend-chart');
    if (sentimentChart) sentimentChart.destroy();
    sentimentChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: trend.map(t => `步${t.step}`),
        datasets: [{
          label: '情感极性',
          data: trend.map(t => t.avg_polarity),
          borderColor: '#667eea',
          tension: 0.3,
          fill: false,
        }, {
          label: '正面数',
          data: trend.map(t => t.positive),
          borderColor: '#48bb78',
          tension: 0.3,
          fill: false,
          yAxisID: 'y1',
        }, {
          label: '负面数',
          data: trend.map(t => t.negative),
          borderColor: '#e53e3e',
          tension: 0.3,
          fill: false,
          yAxisID: 'y1',
        }],
      },
      options: {
        responsive: true,
        scales: {
          y: { title: { display: true, text: '极性' }, min: -1, max: 1 },
          y1: { position: 'right', title: { display: true, text: '数量' }, beginAtZero: true },
        },
      },
    });
  }
}

// ──────────────── KOL 分析 ────────────────

let kolChart = null;

async function loadKOL() {
  const runId = document.getElementById('kol-run').value;
  const branchId = document.getElementById('kol-branch').value;
  const container = document.getElementById('kol-content');
  if (!runId) { container.innerHTML = '<p>请选择运行</p>'; return; }

  try {
    const data = await api(`/simulations/${runId}/kol?branch_id=${branchId}`);
    renderKOL(data.kol, container);
  } catch (e) {
    container.innerHTML = `<p>加载失败: ${e.message}</p>`;
  }
}

function renderKOL(kol, container) {
  if (!kol || !kol.kol_count) {
    container.innerHTML = '<div class="card"><p>暂无 KOL 数据</p></div>';
    return;
  }

  const funnel = kol.funnel || {};
  let html = `
    <div class="card-row" style="grid-template-columns:1fr 1fr 1fr">
      <div class="card">
        <h3>曝光→转化漏斗</h3>
        <div style="text-align:center">
          <div class="stat-value">${funnel.reached_agents || 0}</div>
          <div class="stat-label">触达 Agent</div>
          <div style="font-size:24px;color:#a0aec0">↓ ${((funnel.reach_to_engage || 0) * 100).toFixed(0)}%</div>
          <div class="stat-value">${funnel.engaged_agents || 0}</div>
          <div class="stat-label">产生兴趣</div>
          <div style="font-size:24px;color:#a0aec0">↓ ${((funnel.engage_to_convert || 0) * 100).toFixed(0)}%</div>
          <div class="stat-value" style="color:#48bb78">${funnel.conversions || 0}</div>
          <div class="stat-label">完成转化</div>
        </div>
      </div>
      <div class="card">
        <h3>KOL 互动排行</h3>
        <canvas id="kol-engagement-chart" width="400" height="200"></canvas>
      </div>
      <div class="card">
        <h3>最佳 KOL</h3>
        <p><strong>互动最高</strong>: ${kol.best_engagement_kol || '无'}</p>
        <p><strong>ROI 最高</strong>: ${kol.best_roi_kol || '无'}</p>
      </div>
    </div>`;

  // KOL 详细表格
  const perf = kol.kol_performance || [];
  if (perf.length) {
    html += `<div class="card"><h3>KOL 表现详情</h3>
      <table class="data-table">
      <tr><th>KOL</th><th>内容数</th><th>浏览</th><th>点赞</th><th>评论</th><th>转发</th>
          <th>互动率</th><th>转化数</th><th>转化率</th><th>成本</th><th>收入</th><th>ROI</th></tr>`;
    for (const p of perf) {
      const roiColor = p.roi > 0 ? '#48bb78' : (p.roi < 0 ? '#e53e3e' : '#a0aec0');
      html += `<tr>
        <td>${p.kol_id}</td><td>${p.content_count}</td><td>${p.views}</td>
        <td>${p.likes}</td><td>${p.comments}</td><td>${p.reposts}</td>
        <td>${(p.engagement_rate * 100).toFixed(1)}%</td>
        <td>${p.conversions}</td><td>${(p.conversion_rate * 100).toFixed(1)}%</td>
        <td>¥${p.cost}</td><td>¥${p.revenue}</td>
        <td style="color:${roiColor}">${(p.roi * 100).toFixed(0)}%</td>
      </tr>`;
    }
    html += '</table></div>';
  }

  // 转化归因
  const conversions = kol.conversions || [];
  if (conversions.length) {
    html += '<div class="card"><h3>转化归因详情</h3>';
    for (const c of conversions) {
      html += `<div class="journey-step" style="border-left-color:#48bb78">
        <strong>${c.agent_id}</strong> 在第 ${c.step} 步购买 → 归因给 <strong>${c.attributed_kol}</strong>
        (末次归因, 内容: ${c.content_id})</div>`;
    }
    html += '</div>';
  }

  container.innerHTML = html;

  // 绘制互动柱状图
  if (perf.length) {
    const ctx = document.getElementById('kol-engagement-chart');
    if (kolChart) kolChart.destroy();
    kolChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: perf.map(p => p.kol_id),
        datasets: [{
          label: '点赞',
          data: perf.map(p => p.likes),
          backgroundColor: '#667eea',
        }, {
          label: '评论',
          data: perf.map(p => p.comments),
          backgroundColor: '#48bb78',
        }, {
          label: '转发',
          data: perf.map(p => p.reposts),
          backgroundColor: '#ed8936',
        }],
      },
      options: {
        responsive: true,
        scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true } },
      },
    });
  }
}

// ──────────────── 时间维度分析 ────────────────
let temporalCharts = [];

async function loadTemporal() {
  const runId = document.getElementById('temporal-run').value;
  if (!runId) return;
  const container = document.getElementById('temporal-content');
  container.innerHTML = '<div class="loading"><div class="spinner"></div><p>加载时间维度数据...</p></div>';

  try {
    const data = await api(`/simulations/${runId}/temporal`);
    const t = data.temporal;
    if (!t || !t.num_steps) {
      container.innerHTML = '<div class="card"><p>该运行无时间维度数据</p></div>';
      return;
    }
    renderTemporal(t, container);
  } catch (e) {
    container.innerHTML = `<div class="card"><p>加载失败: ${e.message}</p></div>`;
  }
}

function renderTemporal(t, container) {
  // 销毁旧图表
  temporalCharts.forEach(c => c.destroy());
  temporalCharts = [];

  const steps = Array.from({length: t.num_steps}, (_, i) => i);
  const phases = t.phases || {};

  let html = '';

  // 阶段概览卡片
  const phaseLabels = {early: '早期（种草）', mid: '中期（决策）', late: '晚期（转化）'};
  html += '<div class="card-row" style="grid-template-columns:1fr 1fr 1fr">';
  for (const [key, label] of Object.entries(phaseLabels)) {
    const p = phases[key] || {};
    html += `<div class="card">
      <h3>${label}</h3>
      <div class="stat-value">${(p.avg_events || 0).toFixed(1)}</div>
      <div class="stat-label">平均事件数</div>
      <p style="margin:4px 0">转化: <strong>${(p.avg_conversions || 0).toFixed(1)}</strong></p>
      <p style="margin:4px 0">意向: <strong>${(p.avg_intent || 0).toFixed(3)}</strong></p>
    </div>`;
  }
  html += '</div>';

  // 图表容器
  html += `
    <div class="card"><h3>行为密度 + 购买意向趋势</h3><canvas id="temporal-density-chart"></canvas></div>
    <div class="card"><h3>平台使用时间线</h3><canvas id="temporal-platform-chart"></canvas></div>
    <div class="card"><h3>转化时间线</h3><canvas id="temporal-conversion-chart"></canvas></div>
  `;
  container.innerHTML = html;

  // 行为密度 + 意向趋势（双 Y 轴）
  const densityCtx = document.getElementById('temporal-density-chart');
  if (densityCtx) {
    temporalCharts.push(new Chart(densityCtx, {
      type: 'line',
      data: {
        labels: steps,
        datasets: [{
          label: '行为密度',
          data: t.avg_step_density || [],
          borderColor: '#4299e1',
          backgroundColor: 'rgba(66,153,225,0.1)',
          fill: true,
          yAxisID: 'y',
        }, {
          label: '平均购买意向',
          data: t.avg_intent_timeline || [],
          borderColor: '#ed8936',
          borderDash: [5, 5],
          yAxisID: 'y1',
        }],
      },
      options: {
        responsive: true,
        scales: {
          x: { title: { display: true, text: '时间步' } },
          y: { position: 'left', title: { display: true, text: '事件数' }, beginAtZero: true },
          y1: { position: 'right', title: { display: true, text: '购买意向' }, min: 0, max: 1, grid: { drawOnChartArea: false } },
        },
      },
    }));
  }

  // 平台时间线（堆叠面积图）
  const platformCtx = document.getElementById('temporal-platform-chart');
  const pfTimeline = t.avg_platform_timeline || {};
  const pfColors = {xiaohongshu: '#ff6b6b', douyin: '#000000', weibo: '#ffa500', taobao: '#ff4500'};
  if (platformCtx && Object.keys(pfTimeline).length) {
    temporalCharts.push(new Chart(platformCtx, {
      type: 'line',
      data: {
        labels: steps,
        datasets: Object.entries(pfTimeline).map(([pf, vals]) => ({
          label: pf,
          data: vals,
          borderColor: pfColors[pf] || '#888',
          backgroundColor: (pfColors[pf] || '#888') + '22',
          fill: true,
        })),
      },
      options: {
        responsive: true,
        scales: {
          x: { title: { display: true, text: '时间步' } },
          y: { stacked: true, title: { display: true, text: '平台事件数' }, beginAtZero: true },
        },
      },
    }));
  }

  // 转化时间线（柱状图）
  const convCtx = document.getElementById('temporal-conversion-chart');
  if (convCtx) {
    temporalCharts.push(new Chart(convCtx, {
      type: 'bar',
      data: {
        labels: steps,
        datasets: [{
          label: '购买次数',
          data: t.total_conversion_timeline || [],
          backgroundColor: '#48bb78',
        }],
      },
      options: {
        responsive: true,
        scales: {
          x: { title: { display: true, text: '时间步' } },
          y: { title: { display: true, text: '购买次数' }, beginAtZero: true },
        },
      },
    }));
  }
}

// 启动
init();
