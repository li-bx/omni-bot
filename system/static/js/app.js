/**
 * AI 数字化智能服务平台 — 前端应用逻辑
 */

const API = '';
let thinkingEl = null;

// ================================================================
// 认证
// ================================================================

(async function checkAuth() {
  const token = localStorage.getItem('token');
  if (!token) { window.location.href = '/login'; return; }
  window._token = token;
  try {
    const r = await fetch('/user/info', { headers: { 'Authorization': 'Bearer ' + token } });
    if (!r.ok) { localStorage.removeItem('token'); window.location.href = '/login'; return; }
    const info = await r.json();
    window._currentUser = info.username;  // 保存用户名，用于修改密码
    document.getElementById('headerUser').innerHTML =
      (info.role ? ` <span class="tag tag-purple" style="font-size:10px">${info.name || info.username}</span>` : '');
  } catch(e) {}
  // 兜底：清除浏览器自动填充残留在聊天输入框的内容
  var chatInp = document.getElementById('chatInput');
  if (chatInp && chatInp.value) chatInp.value = '';
})();

async function doLogout() {
  try { await fetch('/logout', { method: 'POST', headers: { 'Authorization': 'Bearer ' + (window._token||'') } }); } catch(e) {}
  localStorage.removeItem('token');
  window.location.href = '/login';
}

// ================================================================
// 修改密码
// ================================================================

function showChangePwd() {
  document.getElementById('pwdOld').value = '';
  document.getElementById('pwdNew').value = '';
  document.getElementById('pwdConfirm').value = '';
  document.getElementById('pwdModal').style.display = 'flex';
}

function hideChangePwd() {
  document.getElementById('pwdModal').style.display = 'none';
}

async function changePwd() {
  var oldPwd = document.getElementById('pwdOld').value;
  var newPwd = document.getElementById('pwdNew').value;
  var confirm = document.getElementById('pwdConfirm').value;
  if (!oldPwd) return toast('请输入当前密码', 'error');
  if (!newPwd) return toast('请输入新密码', 'error');
  if (newPwd.length < 4) return toast('新密码至少 4 位', 'error');
  if (newPwd !== confirm) return toast('两次新密码不一致', 'error');

  try {
    // 先验证旧密码
    var loginCheck = await fetch('/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: window._currentUser, password: oldPwd })
    });
    if (!loginCheck.ok) return toast('当前密码错误', 'error');

    // 更新密码
    await api('PUT', '/users/' + encodeURIComponent(window._currentUser), { password: newPwd });
    toast('密码修改成功');
    hideChangePwd();
  } catch(e) {
    toast('修改失败: ' + e.message, 'error');
  }
}

function toast(msg, type) {
  type = type || 'success';
  var c = document.getElementById('toastContainer');
  var d = document.createElement('div');
  d.className = 'toast ' + type;
  d.textContent = msg;
  c.appendChild(d);
  setTimeout(function() { d.remove(); }, 2500);
}

async function api(method, path, body) {
  var opts = { method: method, headers: { 'Accept': 'application/json' } };
  if (window._token) opts.headers['Authorization'] = 'Bearer ' + window._token;
  if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  var r = await fetch(API + path, opts);
  if (r.status === 401) { localStorage.removeItem('token'); window.location.href = '/login'; throw new Error('未登录'); }
  if (!r.ok) { var err = await r.text(); throw new Error(err || (r.status + ' ' + r.statusText)); }
  return r.json();
}

// ================================================================
// 导航
// ================================================================

document.querySelectorAll('.nav-tab').forEach(function(tab) {
  tab.addEventListener('click', function() { switchPanel(this.dataset.panel); });
});

function switchPanel(name) {
  document.querySelectorAll('.panel').forEach(function(p) { p.classList.remove('active'); });
  document.querySelectorAll('.nav-tab').forEach(function(t) { t.classList.remove('active'); });
  document.getElementById('panel-' + name).classList.add('active');
  var tab = document.querySelector('.nav-tab[data-panel="' + name + '"]');
  if (tab) tab.classList.add('active');
  if (name === 'data') loadIntents(true);
  if (name === 'docs') { loadDocs(); loadDomains(); }
  if (name === 'system') loadHealth();
  if (name === 'train') loadJobs();
  if (name === 'tools') { loadTools(); loadIntentsForTools(); }
  if (name === 'users') { loadUsers(); loadRoles(); }
}

// ================================================================
// 对话
// ================================================================

var sessionId = 'sess_' + Date.now();

async function clearChat() {
  try { await api('DELETE', '/session/' + sessionId); } catch(e) {}
  sessionId = 'sess_' + Date.now();
  var box = document.getElementById('chatBox');
  box.innerHTML = '<div class="chat-empty" id="chatEmpty">' +
    '<div class="icon">💬</div>' +
    '<p>18 个意图 · 8 大业务领域 · AI 数智驱动，一键触达全业务</p>' +
    '<div class="suggestions">' +
      '<span onclick="quickAsk(\'我的待办任务有哪些\')">📋 OA办公</span>' +
      '<span onclick="quickAsk(\'公司的组织架构是怎样的\')">🏢 企业知识</span>' +
      '<span onclick="quickAsk(\'X2000-Pro 和 K-500S 有什么区别\')">🔍 产品对比</span>' +
      '<span onclick="quickAsk(\'批量采购 10 台 X2000 什么价格\')">💰 销售报价</span>' +
      '<span onclick="quickAsk(\'今年Q2华东区X2000销售额和趋势\')">📈 销售图表</span>' +
      '<span onclick="quickAsk(\'我们项目现在到什么阶段了\')">📊 项目进度</span>' +
      '<span onclick="quickAsk(\'设备报 E05 通信超时怎么排查\')">🔧 故障报修</span>' +
      '<span onclick="quickAsk(\'我们的发票什么时候能开出来\')">🧾 发票查询</span>' +
      '<span onclick="quickAsk(\'帮我查下供应商有哪些 A 级的\')">🏭 供应商管理</span>' +
      '<span onclick="quickAsk(\'PO20260601 采购订单货到哪了\')">📦 采购订单</span>' +
      '<span onclick="quickAsk(\'产品保修期是多久怎么延保\')">🛡️ 售后政策</span>' +
      '<span onclick="quickAsk(\'合同里的违约责任条款怎么约定\')">📋 合同条款</span>' +
      '<span onclick="quickAsk(\'我要退货已经收到货了怎么操作\')">🔄 退换货</span>' +
    '</div></div>';
  toast('对话已刷新');
}

function quickAsk(text) {
  document.getElementById('chatInput').value = text;
  sendChat();
}

async function sendChat() {
  var input = document.getElementById('chatInput');
  var btn = document.getElementById('btnSend');
  var text = input.value.trim();
  if (!text || btn.disabled) return;
  input.value = '';
  var empty = document.getElementById('chatEmpty');
  if (empty) empty.style.display = 'none';
  appendMsg('user', text);
  var thinkEl = appendThinking();
  btn.disabled = true;
  var t0 = performance.now();
  try {
    var r = await api('POST', '/chat', { text: text, session_id: sessionId });
    thinkEl.remove();
    var latency = (performance.now() - t0).toFixed(0);
    var sourceLabels = {
      'knowledge_base': '<span class="tag tag-purple">📚 RAG检索</span>',
      'direct': '<span class="tag tag-gray">💬 直接回复</span>',
      'tool_calling': '<span class="tag tag-purple">🔧 Function Call</span>'
    };
    var sourceTag = sourceLabels[r.source] || '<span class="tag tag-gray">' + r.source + '</span>';
    var intentTag = '<span class="tag tag-amber">🎯 ' + r.intent + '</span>';
    var latencyTag = '<span class="tag tag-gray">⚡ ' + latency + 'ms</span>';
    var toolTags = '';
    if (r.tool_calls && r.tool_calls.length) {
      toolTags = r.tool_calls.map(function(tc) {
        return '<span class="tag tag-purple" title="参数: ' + (tc.arguments || '') + '">🔧 ' + tc.tool + '</span>';
      }).join(' ');
    }
    var meta = intentTag + ' ' + sourceTag + ' ' + toolTags + ' ' + latencyTag;
    appendMsg('assistant', r.reply, meta);
    document.getElementById('chatLatency').textContent = '上次响应: ' + latency + 'ms';
  } catch(e) {
    thinkEl.remove();
    appendMsg('assistant', '❌ 请求失败: ' + e.message, '<span class="tag tag-red">错误</span>');
  }
  btn.disabled = false;
  input.focus();
}

function isMarkdown(text) {
  var patterns = [
    /^#{1,6}\s+/m, /\*\*.*?\*\*/, /__.*?__/,
    /(?<!\w)\*[^*\s].*?\*/, /(?<!\w)_[^_\s].*?_/,
    /```[\s\S]*?```/, /`[^`]+`/,
    /^\s*[-*+]\s+/m, /^\s*\d+\.\s+/m,
    /\|.*\|.*\|/, /\[.*?\]\(.*?\)/, /!\[.*?\]\(.*?\)/,
    /^>\s+/m, /^[=-]{3,}$/m
  ];
  return patterns.some(function(p) { return p.test(text); });
}

function escapeHtml(text) {
  var div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function copyMsg(btn) {
  var raw = btn.getAttribute('data-raw');
  navigator.clipboard.writeText(raw).then(function() {
    btn.classList.add('copied'); btn.textContent = '✅ 已复制';
    setTimeout(function() { btn.classList.remove('copied'); btn.textContent = '📋 复制'; }, 1500);
  }).catch(function() {
    var ta = document.createElement('textarea');
    ta.value = raw; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); document.body.removeChild(ta);
    btn.classList.add('copied'); btn.textContent = '✅ 已复制';
    setTimeout(function() { btn.classList.remove('copied'); btn.textContent = '📋 复制'; }, 1500);
  });
}

function appendMsg(role, text, meta) {
  var box = document.getElementById('chatBox');
  var div = document.createElement('div');
  div.className = 'chat-msg ' + role;
  var avatarIcon = role === 'user' ? '👤' : '🤖';
  var rendered = (role === 'assistant' && isMarkdown(text))
    ? '<div class="md-content">' + marked.parse(text) + '</div>'
    : text.replace(/\n/g, '<br>');
  var copyBtn = role === 'assistant'
    ? '<button class="btn-copy" data-raw="' + escapeHtml(text) + '" onclick="copyMsg(this)" title="复制内容">📋 复制</button>'
    : '';
  var metaRow = (copyBtn || meta) ? '<div class="meta-row">' + copyBtn + (meta || '') + '</div>' : '';
  div.innerHTML = '<div class="avatar-sm">' + avatarIcon + '</div>' +
    '<div class="body"><div class="bubble">' + rendered + '</div>' + metaRow + '</div>';
  box.appendChild(div);
  // 延迟滚动确保 DOM 渲染完成后滚动到底部
  requestAnimationFrame(function() {
    box.scrollTop = box.scrollHeight;
  });
}

function appendThinking() {
  var box = document.getElementById('chatBox');
  var div = document.createElement('div');
  div.className = 'chat-msg assistant thinking';
  div.innerHTML = '<div class="avatar-sm">🤖</div>' +
    '<div class="body"><div class="bubble"><div class="thinking-dots"><span></span><span></span><span></span></div></div></div>';
  box.appendChild(div);
  requestAnimationFrame(function() {
    box.scrollTop = box.scrollHeight;
  });
  return div;
}

// ================================================================
// 训练数据
// ================================================================

var selectedIntent = null;

async function loadIntents(autoSelect) {
  var intents = await api('GET', '/data/intents');
  // OA办公、企业知识排最前，其余按名称排序
  var priority = ['OA办公', '企业知识'];
  intents.sort(function(a, b) {
    var ai = priority.indexOf(a.name), bi = priority.indexOf(b.name);
    if (ai >= 0 && bi >= 0) return ai - bi;
    if (ai >= 0) return -1;
    if (bi >= 0) return 1;
    return a.name.localeCompare(b.name, 'zh');
  });
  var list = document.getElementById('intentList');
  list.innerHTML = intents.map(function(i) {
    return '<span class="intent-chip" style="display:inline-flex;align-items:center;gap:6px">' +
      '<span onclick="selectIntent(\'' + i.name + '\')">' + i.name + ' <span style="color:var(--text-muted)">' + i.count + '</span></span>' +
      '<span onclick="deleteIntent(\'' + i.name + '\')" title="删除意图" style="cursor:pointer;color:var(--text-muted);font-size:15px;line-height:1">&times;</span></span>';
  }).join('');
  if (!intents.length) {
    list.innerHTML = '<span style="color:var(--text-muted)">还没有意图类别，在上方添加</span>';
    return;
  }
  // 切换到意图训练数据面板时，默认选中第一个意图
  if (autoSelect && intents.length > 0) {
    selectIntent(intents[0].name);
  }
}

async function deleteIntent(name) {
  if (!confirm('确定删除意图"' + name + '"及其所有样本？此操作不可恢复。')) return;
  try {
    await api('DELETE', '/data/intents/' + encodeURIComponent(name));
    toast('已删除意图: ' + name);
    if (selectedIntent === name) { selectedIntent = null; document.getElementById('sampleCard').style.display = 'none'; }
    loadIntents();
  } catch(e) { toast('删除失败: ' + e.message, 'error'); }
}

async function addIntent() {
  var name = document.getElementById('newIntentName').value.trim();
  if (!name) return;
  await api('POST', '/data/intents/' + encodeURIComponent(name));
  document.getElementById('newIntentName').value = '';
  toast('意图已添加: ' + name);
  loadIntents();
}

async function selectIntent(name) {
  selectedIntent = name;
  document.getElementById('sampleCard').style.display = 'block';
  document.getElementById('sampleTitle').textContent = '样本管理 · ' + name;
  document.querySelectorAll('.intent-chip').forEach(function(c) { c.classList.remove('selected'); });
  var chip = document.querySelector('.intent-chip span[onclick*="' + name + '"]');
  if (chip) chip.closest('.intent-chip').classList.add('selected');
  await loadSamples(name);
  await loadPrompt(name);
}

async function loadPrompt(intent) {
  try {
    var r = await api('GET', '/data/prompts');
    document.getElementById('intentPrompt').value = r.prompts[intent] || '';
    document.getElementById('promptSaved').style.display = 'none';
  } catch(e) {}
}

async function savePrompt() {
  if (!selectedIntent) return;
  var prompt = document.getElementById('intentPrompt').value.trim();
  try {
    await api('PUT', '/data/prompts/' + encodeURIComponent(selectedIntent), { prompt: prompt });
    document.getElementById('promptSaved').style.display = 'inline';
    setTimeout(function() { document.getElementById('promptSaved').style.display = 'none'; }, 2000);
  } catch(e) { toast('保存失败: ' + e.message, 'error'); }
}

async function loadSamples(intent) {
  var r = await api('GET', '/data/samples/' + encodeURIComponent(intent) + '?limit=200');
  var div = document.getElementById('sampleList');
  if (!r.samples || !r.samples.length) {
    div.innerHTML = '<span style="color:var(--text-muted)">暂无样本</span>'; return;
  }
  var html = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">' +
    '<span style="font-size:12px;color:var(--text-muted)">共 ' + r.total + ' 条</span>' +
    '<span><button class="btn btn-sm btn-outline" onclick="toggleSelectAll()">全选</button>' +
    '<button class="btn btn-sm btn-danger" onclick="batchDeleteSamples()" style="margin-left:4px">批量删除</button></span></div>';
  html += r.samples.map(function(s) {
    return '<div style="display:flex;justify-content:space-between;padding:5px 0;font-size:13px;border-bottom:1px solid var(--border-light);align-items:center">' +
      '<span><input type="checkbox" class="sample-cb" value="' + s.index + '" style="margin-right:8px">' + s.text + '</span>' +
      '<span style="color:var(--danger);cursor:pointer;flex-shrink:0;font-size:12px" onclick="delSample(' + s.index + ')">删除</span></div>';
  }).join('');
  div.innerHTML = html;
}

function getSelectedIndices() { return Array.from(document.querySelectorAll('.sample-cb:checked')).map(function(cb) { return parseInt(cb.value); }); }
function toggleSelectAll() {
  var cbs = document.querySelectorAll('.sample-cb');
  var allChecked = cbs.length > 0 && Array.from(cbs).every(function(cb) { return cb.checked; });
  cbs.forEach(function(cb) { cb.checked = !allChecked; });
}
async function batchDeleteSamples() {
  var indices = getSelectedIndices();
  if (!indices.length) return toast('请先勾选要删除的样本', 'error');
  if (!confirm('确定删除选中的 ' + indices.length + ' 条样本？')) return;
  try {
    await api('DELETE', '/data/samples/' + encodeURIComponent(selectedIntent) + '?indices=' + indices.join(','));
    toast('已删除 ' + indices.length + ' 条'); loadSamples(selectedIntent); loadIntents();
  } catch(e) { toast('删除失败: ' + e.message, 'error'); }
}
async function addSamples() {
  if (!selectedIntent) return toast('请先选择意图', 'error');
  var raw = document.getElementById('sampleTexts').value.trim();
  if (!raw) return;
  var texts = raw.split('\n').map(function(t) { return t.trim(); }).filter(Boolean);
  var r = await api('POST', '/data/samples/' + encodeURIComponent(selectedIntent), { texts: texts });
  toast('添加 ' + r.added + ' 条');
  document.getElementById('sampleTexts').value = '';
  loadSamples(selectedIntent); loadIntents();
}
async function autoGenerate() {
  if (!selectedIntent) return toast('请先选择意图', 'error');
  var btn = event.target;
  btn.disabled = true; btn.textContent = '生成中...';
  try {
    var r = await api('POST', '/data/generate/' + encodeURIComponent(selectedIntent) + '?count=30');
    if (r.ok) { toast('LLM生成 ' + r.generated + ' 条，新增 ' + r.added + ' 条'); loadSamples(selectedIntent); loadIntents(); }
    else toast(r.error, 'error');
  } catch(e) { toast('生成失败: ' + e.message, 'error'); }
  btn.disabled = false; btn.textContent = 'LLM自动生成';
}
async function delSample(idx) {
  await api('DELETE', '/data/samples/' + encodeURIComponent(selectedIntent) + '?indices=' + idx);
  loadSamples(selectedIntent); loadIntents();
}
async function exportData() {
  var r = await api('POST', '/data/export');
  toast('导出完成: 训练' + r.train + ' 验证' + r.val + ' 测试' + r.test);
}

// ================================================================
// 知识库文档
// ================================================================

async function uploadDoc() {
  var file = document.getElementById('docFile').files[0];
  if (!file) return toast('请选择文件', 'error');
  var domain = document.getElementById('docDomain').value;
  var newDomain = document.getElementById('newDomain').value.trim();
  if (newDomain) domain = newDomain;
  if (!domain) domain = '通用';
  var form = new FormData(); form.append('file', file);
  var r = await fetch(API + '/documents/upload?domain=' + encodeURIComponent(domain), {
    method: 'POST', body: form,
    headers: window._token ? { 'Authorization': 'Bearer ' + window._token } : {}
  });
  var data = await r.json();
  toast('文档已上传 [' + domain + '] ' + data.filename);
  document.getElementById('docFile').value = ''; document.getElementById('newDomain').value = '';
  loadDocs(); loadDomains();
}
async function loadDocs() {
  var docs = await api('GET', '/documents');
  var indexedResp = await api('GET', '/models/indexed-docs');
  var indexed = new Set(indexedResp.indexed || []);
  var div = document.getElementById('docList');
  if (!docs.length) { div.innerHTML = '<span style="color:var(--text-muted)">暂无文档，请上传产品手册等内容</span>'; return; }
  div.innerHTML = docs.map(function(d) {
    // name 可能已含 domain 前缀，去重
    var filename = d.name;
    if (d.domain && d.domain !== '通用' && !d.name.startsWith(d.domain + '/')) {
      filename = d.domain + '/' + d.name;
    }
    var isIndexed = indexed.has(filename);
    return '<div style="display:flex;justify-content:space-between;padding:9px 0;border-bottom:1px solid var(--border-light);font-size:13px;align-items:center">' +
      '<span><input type="checkbox" class="doc-cb" value="' + filename + '" ' + (isIndexed ? 'checked disabled' : '') + ' style="margin-right:8px">' +
      '<span class="tag tag-' + (d.domain === '通用' ? 'gray' : 'blue') + '">' + (d.domain || '通用') + '</span> ' + d.name +
      ' <span style="color:var(--text-muted);font-size:11px">' + (d.size / 1024).toFixed(1) + 'KB</span>' +
      (isIndexed ? ' <span class="tag tag-green" style="font-size:10px">已索引</span>' : '') +
      '</span>' +
      '<span style="color:var(--danger);cursor:pointer;font-size:12px" onclick="deleteDoc(\'' + d.id + '\')">删除</span></div>';
  }).join('');
}

async function deleteDoc(id) { await api('DELETE', '/documents/' + id); toast('文档已删除'); loadDocs(); loadDomains(); }

async function addSelectedToKB() {
  var checked = [];
  document.querySelectorAll('.doc-cb:checked:not([disabled])').forEach(function(cb) {
    checked.push(cb.value);
  });
  if (!checked.length) return toast('请先勾选要加入知识库的文档', 'error');
  var btn = document.getElementById('btnAddToKB');
  btn.disabled = true; btn.textContent = '索引中...';
  try {
    var r = await api('POST', '/models/add-to-kb', { filenames: checked });
    toast('已添加 ' + r.added + ' 篇，跳过 ' + r.skipped + ' 篇');
    loadDocs();
  } catch(e) {
    toast('添加失败: ' + e.message, 'error');
  }
  btn.disabled = false; btn.textContent = '📥 增量加入知识库';
}
async function loadDomains() {
  try {
    var r = await api('GET', '/documents/domains');
    var sel = document.getElementById('docDomain');
    sel.innerHTML = '<option value="">选择领域</option>' + r.domains.map(function(d) { return '<option value="' + d + '">' + d + '</option>'; }).join('');
  } catch(e) {}
}

// ================================================================
// 模型训练
// ================================================================

async function trainIntent() {
  var btn = document.getElementById('btnTrainIntent');
  btn.disabled = true; btn.textContent = '训练中...';
  try { var r = await api('POST', '/train/intent'); toast('训练任务已启动: ' + r.job_id); pollJob(r.job_id, 'intentJobStatus', btn); }
  catch(e) { toast('启动失败: ' + e.message, 'error'); btn.disabled = false; btn.textContent = '开始训练'; }
}
async function trainEmbedding() {
  var btn = document.getElementById('btnTrainEmbed');
  btn.disabled = true; btn.textContent = '训练中...';
  try { var r = await api('POST', '/train/embedding'); toast('训练任务已启动: ' + r.job_id); pollJob(r.job_id, 'embedJobStatus', btn); }
  catch(e) { toast('启动失败: ' + e.message, 'error'); btn.disabled = false; btn.textContent = '开始训练'; }
}
function pollJob(jobId, statusElId, btn) {
  var el = document.getElementById(statusElId);
  el.innerHTML = '<span class="tag tag-blue">queued</span> 排队中...';
  var iv = setInterval(async function() {
    try {
      var j = await api('GET', '/train/jobs/' + jobId);
      if (j.status === 'completed') {
        el.innerHTML = '<span class="tag tag-green">完成</span> ' + j.message;
        btn.disabled = false; btn.textContent = '重新训练'; clearInterval(iv);
        toast('训练完成！请点击"重新加载模型"'); loadJobs();
      } else if (j.status === 'failed') {
        el.innerHTML = '<span class="tag tag-red">失败</span> ' + j.message;
        btn.disabled = false; btn.textContent = '重试'; clearInterval(iv); loadJobs();
      } else {
        el.innerHTML = '<span class="tag tag-blue">' + j.status + '</span> ' + j.message +
          ' <div class="progress-bar" style="width:200px;display:inline-block;vertical-align:middle"><div class="fill" style="width:' + (j.progress * 100).toFixed(0) + '%"></div></div>';
      }
    } catch(e) { clearInterval(iv); }
  }, 2000);
}
async function reloadModels() { var r = await api('POST', '/models/reload'); toast('模型重载完成'); loadHealth(); }
async function rebuildKB() {
  var btn = document.getElementById('btnRebuildKB'); var span = document.getElementById('rebuildStatus');
  btn.disabled = true; btn.textContent = '重建中...'; span.innerHTML = '<span class="tag tag-blue">running</span> 正在重建索引...';
  try {
    var r = await api('POST', '/models/rebuild-kb');
    if (r.ok) { span.innerHTML = '<span class="tag tag-green">完成</span> ' + r.chunks + ' 个段落'; toast('知识库重建完成: ' + r.chunks + ' 个段落'); loadHealth(); }
    else { span.innerHTML = '<span class="tag tag-red">失败</span> ' + r.error; toast('重建失败: ' + r.error, 'error'); }
  } catch(e) { toast('请求失败: ' + e.message, 'error'); span.innerHTML = ''; }
  btn.disabled = false; btn.textContent = '🔨 重建知识库索引';
}
async function loadJobs() {
  var jobs = await api('GET', '/train/jobs');
  var div = document.getElementById('jobList');
  if (!jobs.length) { div.innerHTML = '无训练任务'; return; }
  div.innerHTML = jobs.map(function(j) {
    return '<div style="padding:9px 0;border-bottom:1px solid var(--border-light);font-size:13px">' +
      '<span class="tag tag-' + (j.status === 'completed' ? 'green' : j.status === 'failed' ? 'red' : 'blue') + '">' + j.status + '</span> ' +
      j.type + ' · ' + (j.message || '') + ' · ' + (j.progress ? (j.progress * 100).toFixed(0) + '%' : '') + '</div>';
  }).join('');
}

// ================================================================
// 系统状态
// ================================================================

async function loadHealth() {
  var h = await api('GET', '/health');
  var el;
  el = document.getElementById('statusIntent'); if (el) el.innerHTML = '<span class="status-pulse ' + (h.intent_model ? 'on' : 'off') + '"></span>意图';
  el = document.getElementById('statusEmbed'); if (el) el.innerHTML = '<span class="status-pulse ' + (h.embedding_model ? 'on' : 'off') + '"></span>检索';
  el = document.getElementById('statusKb'); if (el) el.innerHTML = '<span class="status-pulse ' + (h.kb_chunks > 0 ? 'on' : 'off') + '"></span>知识库';
  el = document.getElementById('statusTools'); if (el) el.innerHTML = '<span class="status-pulse ' + (h.tool_count > 0 ? 'on' : 'off') + '"></span>工具';
  var grid = document.getElementById('metricsGrid');
  if (grid) grid.innerHTML =
    '<div class="metric"><div class="value">' + h.intent_categories + '</div><div class="label">意图类别</div></div>' +
    '<div class="metric"><div class="value">' + h.uploaded_docs + '</div><div class="label">知识库文档</div></div>' +
    '<div class="metric"><div class="value">' + h.kb_chunks + '</div><div class="label">知识库段落</div></div>' +
    '<div class="metric"><div class="value">' + (h.tool_count || 0) + '</div><div class="label">API 工具</div></div>' +
    '<div class="metric"><div class="value">' + (h.intent_model ? '已加载' : '未加载') + '</div><div class="label">意图模型</div></div>' +
    '<div class="metric"><div class="value">' + (h.embedding_model ? '已加载' : '未加载') + '</div><div class="label">检索模型</div></div>';
  loadJobs();
  var chatStatus = document.getElementById('chatModelStatus');
  if (chatStatus) {
    if (h.embedding_model) {
      var parts = ['意图识别(' + (h.intent_categories || 16) + '类)'];
      if (h.kb_chunks > 0) parts.push('知识库' + h.kb_chunks + '段');
      if (h.tool_count > 0) parts.push(h.tool_count + '个API工具');
      parts.push('Reranker重排'); parts.push('多轮对话');
      // chatStatus.textContent = '✅ 模型就绪 · ' + parts.join(' · ');
    } else {
      // chatStatus.textContent = '⚠️ 模型未加载，请先训练或重载模型';
    }
    chatStatus.textContent =''
  }
}

// ================================================================
// 工具管理
// ================================================================

var editingToolName = null; var allIntents = [];

async function loadTools() {
  try {
    var r = await api('GET', '/tools');
    var list = document.getElementById('toolList');
    if (!r.tools || !r.tools.length) {
      list.innerHTML = '<span style="color:var(--text-muted)">还没有配置工具。点击"+ 添加工具"创建第一个 API 调用工具。</span>'; return;
    }
    list.innerHTML = r.tools.map(function(t) {
      var intents = (t.intents || []).join(', ') || '<i>未关联</i>';
      var method = (t.api_config || {}).method || 'GET';
      var urlPreview = ((t.api_config || {}).url_template || '').substring(0, 60);
      return '<div style="display:flex;justify-content:space-between;align-items:center;padding:11px 0;border-bottom:1px solid var(--border-light)">' +
        '<div style="flex:1"><div style="font-weight:600;margin-bottom:2px"><span class="tag tag-' + (method === 'GET' ? 'green' : 'blue') + '">' + method + '</span> ' + t.name + '</div>' +
        '<div style="font-size:12px;color:var(--text-secondary)">' + (t.description || '') + '</div>' +
        '<div style="font-size:11px;color:var(--text-muted);margin-top:2px">意图: ' + intents + ' | URL: ' + urlPreview + '...</div></div>' +
        '<div style="display:flex;gap:4px;flex-shrink:0;margin-left:12px">' +
        '<button class="btn btn-sm btn-outline" onclick="editTool(\'' + t.name + '\')">编辑</button>' +
        '<button class="btn btn-sm btn-danger" onclick="deleteTool(\'' + t.name + '\')">删除</button></div></div>';
    }).join('');
  } catch(e) { document.getElementById('toolList').innerHTML = '<span style="color:var(--danger)">加载失败: ' + e.message + '</span>'; }
}

async function loadIntentsForTools() {
  try { var r = await api('GET', '/data/intents'); allIntents = r.map(function(i) { return i.name; }); renderIntentCheckboxes(); }
  catch(e) { allIntents = []; }
}

function renderIntentCheckboxes(selected) {
  var div = document.getElementById('tfIntents');
  var sel = selected || [];
  div.innerHTML = allIntents.map(function(i) {
    return '<label style="font-size:12px;cursor:pointer;padding:5px 12px;border:1px solid var(--border);border-radius:16px;display:inline-flex;align-items:center;gap:5px;' +
      (sel.includes(i) ? 'background:var(--primary-light);border-color:var(--primary);color:var(--primary)' : '') + '">' +
      '<input type="checkbox" value="' + i + '" ' + (sel.includes(i) ? 'checked' : '') + ' style="margin:0"> ' + i + '</label>';
  }).join('') || '<span style="color:var(--text-muted);font-size:12px">暂无意图类别，请先在"训练数据"中添加</span>';
}

function showToolForm(tool) {
  document.getElementById('toolFormCard').style.display = 'block';
  document.getElementById('toolListCard').style.display = 'none';
  document.getElementById('toolSavedMsg').style.display = 'none';
  if (tool) {
    editingToolName = tool.name;
    document.getElementById('toolFormTitle').textContent = '编辑工具 · ' + tool.name;
    document.getElementById('tfName').value = tool.name;
    document.getElementById('tfType').value = tool.type || 'api';
    document.getElementById('tfDesc').value = tool.description || '';
    document.getElementById('tfMethod').value = (tool.api_config || {}).method || 'GET';
    document.getElementById('tfUrl').value = (tool.api_config || {}).url_template || '';
    try { document.getElementById('tfHeaders').value = JSON.stringify((tool.api_config || {}).headers || {}, null, 2); }
    catch(e) { document.getElementById('tfHeaders').value = '{}'; }
    document.getElementById('tfParams').value = JSON.stringify(tool.parameters || { type: 'object', properties: {}, required: [] }, null, 2);
    renderIntentCheckboxes(tool.intents || []);
  } else {
    editingToolName = null;
    document.getElementById('toolFormTitle').textContent = '添加工具';
    document.getElementById('tfName').value = ''; document.getElementById('tfType').value = 'api';
    document.getElementById('tfDesc').value = ''; document.getElementById('tfMethod').value = 'GET';
    document.getElementById('tfUrl').value = ''; document.getElementById('tfHeaders').value = '{"Content-Type": "application/json"}';
    document.getElementById('tfParams').value = JSON.stringify({ type: 'object', properties: {}, required: [] }, null, 2);
    renderIntentCheckboxes([]);
  }
}

function hideToolForm() { document.getElementById('toolFormCard').style.display = 'none'; document.getElementById('toolListCard').style.display = 'block'; editingToolName = null; }

async function saveTool() {
  var name = document.getElementById('tfName').value.trim();
  var desc = document.getElementById('tfDesc').value.trim();
  if (!name) return toast('工具名称不能为空', 'error');
  if (!desc) return toast('工具描述不能为空', 'error');
  var selIntents = Array.from(document.querySelectorAll('#tfIntents input:checked')).map(function(cb) { return cb.value; });
  var headers, params;
  try { headers = JSON.parse(document.getElementById('tfHeaders').value); }
  catch(e) { return toast('请求头 JSON 格式错误', 'error'); }
  try { params = JSON.parse(document.getElementById('tfParams').value); }
  catch(e) { return toast('参数定义 JSON 格式错误', 'error'); }
  var body = {
    name: name, description: desc, type: document.getElementById('tfType').value, intents: selIntents,
    api_config: {
      method: document.getElementById('tfMethod').value,
      url_template: document.getElementById('tfUrl').value.trim(), headers: headers,
      query_params: [], body_fields: Object.keys(params.properties || {})
    },
    parameters: params
  };
  try {
    if (editingToolName) { await api('PUT', '/tools/' + encodeURIComponent(editingToolName), body); toast('工具已更新: ' + name); }
    else { await api('POST', '/tools', body); toast('工具已添加: ' + name); }
    document.getElementById('toolSavedMsg').style.display = 'inline';
    setTimeout(function() { document.getElementById('toolSavedMsg').style.display = 'none'; }, 2000);
    hideToolForm(); loadTools();
  } catch(e) { toast('保存失败: ' + e.message, 'error'); }
}
async function editTool(name) {
  try { var tool = await api('GET', '/tools/' + encodeURIComponent(name)); showToolForm(tool); }
  catch(e) { toast('加载工具失败: ' + e.message, 'error'); }
}
async function deleteTool(name) {
  if (!confirm('确定删除工具"' + name + '"?此操作不可恢复。')) return;
  try { await api('DELETE', '/tools/' + encodeURIComponent(name)); toast('工具已删除: ' + name); loadTools(); }
  catch(e) { toast('删除失败: ' + e.message, 'error'); }
}
async function reloadTools() { try { await api('POST', '/tools/reload'); toast('工具配置已重载'); loadTools(); } catch(e) { toast('重载失败: ' + e.message, 'error'); } }
function onToolTypeChange() {}

// ================================================================
// 用户 & 角色管理
// ================================================================

var editingUsername = null;
var selectedRoleForPerm = null;

async function loadUsers() {
  try {
    var r = await api('GET', '/users');
    var div = document.getElementById('userList');
    if (!r.users || !r.users.length) { div.innerHTML = '<span style="color:var(--text-muted)">暂无用户</span>'; return; }
    div.innerHTML = '<table style="width:100%;border-collapse:collapse;font-size:13px">' +
      '<thead><tr style="border-bottom:2px solid var(--border);text-align:left">' +
      '<th style="padding:8px">用户名</th><th style="padding:8px">显示名</th><th style="padding:8px">角色</th>' +
      '<th style="padding:8px">状态</th><th style="padding:8px">创建时间</th><th style="padding:8px">操作</th></tr></thead>' +
      '<tbody>' + r.users.map(function(u) {
        return '<tr style="border-bottom:1px solid var(--border-light)">' +
          '<td style="padding:8px"><strong>' + u.username + '</strong></td>' +
          '<td style="padding:8px">' + u.display_name + '</td>' +
          '<td style="padding:8px"><span class="tag tag-purple">' + u.role_name + '</span></td>' +
          '<td style="padding:8px"><span class="tag tag-' + (u.enabled ? 'green' : 'red') + '">' + (u.enabled ? '启用' : '禁用') + '</span></td>' +
          '<td style="padding:8px;color:var(--text-muted);font-size:12px">' + ((u.created_at || '').substring(0, 10)) + '</td>' +
          '<td style="padding:8px"><button class="btn btn-sm btn-outline" onclick="editUser(\'' + u.username + '\')">编辑</button> ' +
          '<button class="btn btn-sm btn-danger" onclick="deleteUser(\'' + u.username + '\')">删除</button></td></tr>';
      }).join('') + '</tbody></table>';
  } catch(e) { document.getElementById('userList').innerHTML = '<span style="color:var(--danger)">加载失败: ' + e.message + '</span>'; }
}

function showAddUserForm() {
  editingUsername = null;
  document.getElementById('userFormTitle').textContent = '添加用户';
  document.getElementById('ufUsername').value = ''; document.getElementById('ufUsername').disabled = false;
  document.getElementById('ufDisplayName').value = ''; document.getElementById('ufPassword').value = '';
  document.getElementById('userFormCard').style.display = 'block';
  loadRoleOptions('');
}

async function editUser(username) {
  editingUsername = username;
  document.getElementById('userFormTitle').textContent = '编辑用户 · ' + username;
  document.getElementById('ufUsername').value = username; document.getElementById('ufUsername').disabled = true;
  document.getElementById('ufPassword').value = '';
  try {
    var r = await api('GET', '/users');
    var u = r.users.find(function(u) { return u.username === username; });
    if (u) { document.getElementById('ufDisplayName').value = u.display_name || ''; loadRoleOptions(u.role_name); }
    document.getElementById('userFormCard').style.display = 'block';
  } catch(e) { toast('加载用户失败', 'error'); }
}

function hideUserForm() { document.getElementById('userFormCard').style.display = 'none'; editingUsername = null; }

async function saveUser() {
  var username = document.getElementById('ufUsername').value.trim();
  var password = document.getElementById('ufPassword').value.trim();
  var display_name = document.getElementById('ufDisplayName').value.trim();
  var role_name = document.getElementById('ufRole').value;
  if (!username) return toast('用户名不能为空', 'error');
  try {
    if (editingUsername) {
      var body = { display_name: display_name, role_name: role_name };
      if (password) body.password = password;
      await api('PUT', '/users/' + encodeURIComponent(editingUsername), body);
      toast('用户已更新: ' + editingUsername);
    } else {
      if (!password) return toast('密码不能为空', 'error');
      await api('POST', '/users', { username: username, password: password, display_name: display_name || username, role_name: role_name });
      toast('用户已创建: ' + username);
    }
    hideUserForm(); loadUsers();
  } catch(e) { toast('保存失败: ' + e.message, 'error'); }
}

async function deleteUser(username) {
  if (!confirm('确定删除用户"' + username + '"?此操作不可恢复。')) return;
  try { await api('DELETE', '/users/' + encodeURIComponent(username)); toast('用户已删除'); loadUsers(); }
  catch(e) { toast('删除失败: ' + e.message, 'error'); }
}

async function loadRoles() {
  try {
    var r = await api('GET', '/roles');
    var div = document.getElementById('roleList');
    if (!r.roles || !r.roles.length) { div.innerHTML = '<span style="color:var(--text-muted)">暂无角色</span>'; return; }
    div.innerHTML = r.roles.map(function(role) {
      return '<div style="display:flex;justify-content:space-between;align-items:center;padding:11px 0;border-bottom:1px solid var(--border-light)">' +
        '<div style="flex:1"><strong>' + role.name + '</strong> ' +
        '<span style="color:var(--text-muted);font-size:12px;margin-left:8px">' + (role.description || '') + '</span> ' +
        '<span class="tag tag-blue" style="margin-left:8px">' + role.tool_count + ' 个工具权限</span></div>' +
        '<div style="display:flex;gap:4px"><button class="btn btn-sm btn-outline" onclick="editRolePermissions(\'' + role.name + '\')">工具权限</button> ' +
        '<button class="btn btn-sm btn-danger" onclick="deleteRole(\'' + role.name + '\')">删除</button></div></div>';
    }).join('');
  } catch(e) { document.getElementById('roleList').innerHTML = '<span style="color:var(--danger)">加载失败: ' + e.message + '</span>'; }
}

async function loadRoleOptions(selected) {
  try {
    var r = await api('GET', '/roles');
    document.getElementById('ufRole').innerHTML = r.roles.map(function(role) {
      return '<option value="' + role.name + '" ' + (role.name === selected ? 'selected' : '') + '>' + role.name + '</option>';
    }).join('');
  } catch(e) {}
}

async function addRole() {
  var name = document.getElementById('newRoleName').value.trim();
  if (!name) return toast('角色名不能为空', 'error');
  try { await api('POST', '/roles', { name: name }); toast('角色已添加: ' + name); document.getElementById('newRoleName').value = ''; loadRoles(); }
  catch(e) { toast('添加失败: ' + e.message, 'error'); }
}

async function deleteRole(name) {
  if (!confirm('确定删除角色"' + name + '"?此操作不可恢复。')) return;
  try { await api('DELETE', '/roles/' + encodeURIComponent(name)); toast('角色已删除'); loadRoles(); }
  catch(e) { toast('删除失败: ' + e.message, 'error'); }
}

async function editRolePermissions(roleName) {
  selectedRoleForPerm = roleName;
  document.getElementById('rolePermTitle').textContent = '工具权限 · ' + roleName;
  document.getElementById('rolePermCard').style.display = 'block';
  document.getElementById('rolePermSaved').style.display = 'none';
  try {
    var r = await api('GET', '/roles/' + encodeURIComponent(roleName) + '/permissions');
    var allowedSet = {};
    (r.tools || []).forEach(function(t) { allowedSet[t] = true; });
    var allTools = r.all_tools || [];
    document.getElementById('rolePermCheckboxes').innerHTML = allTools.map(function(tn) {
      return '<label style="font-size:12px;cursor:pointer;padding:6px 14px;border:1px solid var(--border);border-radius:18px;display:inline-flex;align-items:center;gap:6px;' +
        (allowedSet[tn] ? 'background:rgba(99,102,241,0.2);border-color:var(--primary);color:var(--primary-glow)' : '') + '">' +
        '<input type="checkbox" value="' + tn + '" ' + (allowedSet[tn] ? 'checked' : '') + ' style="margin:0"> ' + tn + '</label>';
    }).join('') || '<span style="color:var(--text-muted);font-size:12px">暂无工具可配置</span>';
  } catch(e) { toast('加载权限失败: ' + e.message, 'error'); }
}

async function saveRolePermissions() {
  if (!selectedRoleForPerm) return;
  var tools = Array.from(document.querySelectorAll('#rolePermCheckboxes input:checked')).map(function(cb) { return cb.value; });
  try {
    await api('PUT', '/roles/' + encodeURIComponent(selectedRoleForPerm) + '/permissions', { tools: tools });
    document.getElementById('rolePermSaved').style.display = 'inline';
    setTimeout(function() { document.getElementById('rolePermSaved').style.display = 'none'; }, 2000);
    loadRoles();
  } catch(e) { toast('保存权限失败: ' + e.message, 'error'); }
}

// ================================================================
// 初始化
// ================================================================

loadHealth();
setInterval(loadHealth, 15000);

// 二次清除浏览器自动填充（Chrome 可能在异步时机注入，比 checkAuth 更晚）
setTimeout(function() {
  var inp = document.getElementById('chatInput');
  if (inp && inp.value && inp.value !== '') inp.value = '';
}, 500);
