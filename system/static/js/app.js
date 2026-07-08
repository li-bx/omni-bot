/**
 * AI 数字化智能服务平台 — HTMX + Alpine.js 前端
 * Alpine.js 管理 UI 状态，HTMX 处理 AJAX 数据加载与表单提交
 */

// ---- Toast ----
function toast(msg, type) {
  type = type || 'success';
  var c = document.getElementById('toastContainer');
  var d = document.createElement('div');
  d.className = 'toast ' + type;
  d.textContent = msg;
  c.appendChild(d);
  setTimeout(function() { d.remove(); }, 2500);
}

// ---- Escape HTML (for copy button) ----
function escapeHtml(text) {
  var div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ---- Copy message to clipboard ----
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

// ---- Markdown detection (client-side fallback) ----
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

// ---- Sample checkbox toggle ----
function toggleSelectAllSamples() {
  var cbs = document.querySelectorAll('.sample-cb');
  if (!cbs.length) return;
  var allChecked = Array.from(cbs).every(function(cb) { return cb.checked; });
  cbs.forEach(function(cb) { cb.checked = !allChecked; });
}

// ================================================================
// Alpine App State
// ================================================================

function appState() {
  return {
    // Navigation
    activePanel: 'chat',

    // Auth
    token: localStorage.getItem('token') || '',
    currentUser: '',

    // Change password modal
    showPwdModal: false,
    pwdOld: '',
    pwdNew: '',
    pwdConfirm: '',

    // Intent training
    selectedIntent: null,

    // ---- Init ----
    init() {
      this.token = localStorage.getItem('token') || '';
      if (!this.token) { window.location.href = '/login'; return; }
      this.checkAuth();
      this.loadHealth();
      // Clear autofill
      setTimeout(() => {
        var inp = document.getElementById('chatInput');
        if (inp && inp.value) inp.value = '';
      }, 500);
    },

    // ---- Auth ----
    async checkAuth() {
      try {
        var r = await fetch('/user/info', { headers: { 'Authorization': 'Bearer ' + this.token } });
        if (!r.ok) { localStorage.removeItem('token'); window.location.href = '/login'; return; }
        var info = await r.json();
        this.currentUser = info.username;
        var el = document.getElementById('headerUser');
        if (el && info.role) {
          el.innerHTML = '<span class="tag tag-purple" style="font-size:10px">' + (info.name || info.username) + '</span>';
        }
      } catch(e) {}
    },

    async doLogout() {
      try { await fetch('/logout', { method: 'POST', headers: { 'Authorization': 'Bearer ' + this.token } }); } catch(e) {}
      localStorage.removeItem('token');
      window.location.href = '/login';
    },

    async changePwd() {
      if (!this.pwdOld) return toast('请输入当前密码', 'error');
      if (!this.pwdNew) return toast('请输入新密码', 'error');
      if (this.pwdNew.length < 4) return toast('新密码至少 4 位', 'error');
      if (this.pwdNew !== this.pwdConfirm) return toast('两次新密码不一致', 'error');

      try {
        var loginCheck = await fetch('/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: this.currentUser, password: this.pwdOld })
        });
        if (!loginCheck.ok) return toast('当前密码错误', 'error');

        await this.api('PUT', '/users/' + encodeURIComponent(this.currentUser), { password: this.pwdNew });
        toast('密码修改成功');
        this.showPwdModal = false;
        this.pwdOld = ''; this.pwdNew = ''; this.pwdConfirm = '';
      } catch(e) {
        toast('修改失败: ' + e.message, 'error');
      }
    },

    // ---- API helper ----
    async api(method, path, body) {
      var opts = { method: method, headers: { 'Accept': 'application/json' } };
      if (this.token) opts.headers['Authorization'] = 'Bearer ' + this.token;
      if (body) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
      var r = await fetch(path, opts);
      if (r.status === 401) { localStorage.removeItem('token'); window.location.href = '/login'; throw new Error('未登录'); }
      if (!r.ok) { var err = await r.text(); throw new Error(err || (r.status + ' ' + r.statusText)); }
      return r.json();
    },

    // ---- Navigation ----
    switchPanel(name) {
      this.activePanel = name;
      // Trigger panel-specific initial loads via HTMX
      var _this = this;
      requestAnimationFrame(function() {
        if (name === 'data') _this.loadIntents();
        if (name === 'docs') { htmx.trigger('#docList', 'refreshDocs'); htmx.trigger('#docDomain', 'refreshDomains'); }
        if (name === 'system') htmx.trigger('#metricsGrid', 'refreshHealth');
        if (name === 'train') htmx.trigger('#jobList', 'refreshJobs');
        if (name === 'tools') { htmx.trigger('#toolList', 'refreshTools'); _this.loadIntentsForTools(); }
        if (name === 'users') { htmx.trigger('#userList', 'refreshUsers'); htmx.trigger('#roleList', 'refreshRoles'); }
      });
    },

    // ---- Panel loaders ----
    async loadIntents() {
      try {
        var intents = await this.api('GET', '/data/intents');
        var priority = ['OA办公', '企业知识'];
        intents.sort(function(a, b) {
          var ai = priority.indexOf(a.name), bi = priority.indexOf(b.name);
          if (ai >= 0 && bi >= 0) return ai - bi;
          if (ai >= 0) return -1;
          if (bi >= 0) return 1;
          return a.name.localeCompare(b.name, 'zh');
        });
        var list = document.getElementById('intentList');
        if (!list) return;
        list.innerHTML = intents.map(function(i) {
          return '<span class="intent-chip" style="display:inline-flex;align-items:center;gap:6px" ' +
            ':class="selectedIntent === \'' + i.name.replace(/'/g, "\\'") + '\' ? \'intent-chip selected\' : \'intent-chip\'">' +
            '<span @click="selectIntent(\'' + i.name.replace(/'/g, "\\'") + '\')" style="cursor:pointer">' +
            i.name + ' <span style="color:var(--text-muted)">' + i.count + '</span></span>' +
            '<span hx-delete="/ui/intents/' + encodeURIComponent(i.name) + '" ' +
            'hx-target="#intentList" hx-swap="innerHTML" ' +
            'hx-confirm="确定删除意图「' + i.name.replace(/"/g, '&quot;') + '」及其所有样本？" ' +
            'title="删除意图" style="cursor:pointer;color:var(--text-muted);font-size:15px;line-height:1">&times;</span></span>';
        }).join('');
        if (!intents.length) {
          list.innerHTML = '<span style="color:var(--text-muted)">还没有意图类别，在上方添加</span>';
        } else if (!this.selectedIntent) {
          this.selectIntent(intents[0].name);
        }
      } catch(e) {}
    },

    selectIntent(name) {
      this.selectedIntent = name;
      var card = document.getElementById('sampleCard');
      if (card) card.style.display = 'block';
      var title = document.getElementById('sampleTitle');
      if (title) title.textContent = '样本管理 · ' + name;
      // Load samples via HTMX
      htmx.ajax('GET', '/ui/samples/' + encodeURIComponent(name), { target: '#sampleList', swap: 'innerHTML' });
      // Load prompt
      this.loadPrompt(name);
    },

    async loadPrompt(intent) {
      try {
        var r = await this.api('GET', '/data/prompts');
        var ta = document.getElementById('intentPrompt');
        if (ta) {
          ta.value = (r.prompts && r.prompts[intent]) ? r.prompts[intent] : '';
          document.getElementById('promptSaved').style.display = 'none';
        }
      } catch(e) {}
    },

    async savePrompt(evt) {
      if (!this.selectedIntent) return;
      var prompt = evt.target.value.trim();
      try {
        await this.api('PUT', '/data/prompts/' + encodeURIComponent(this.selectedIntent), { prompt: prompt });
        document.getElementById('promptSaved').style.display = 'inline';
        setTimeout(function() { document.getElementById('promptSaved').style.display = 'none'; }, 2000);
      } catch(e) { toast('保存失败: ' + e.message, 'error'); }
    },

    async addSamples(evt) {
      if (!this.selectedIntent) return toast('请先选择意图', 'error');
      var raw = document.getElementById('sampleTexts').value.trim();
      if (!raw) return;
      var texts = raw.split('\n').map(function(t) { return t.trim(); }).filter(Boolean);
      try {
        var r = await this.api('POST', '/data/samples/' + encodeURIComponent(this.selectedIntent), { texts: texts });
        toast('添加 ' + r.added + ' 条');
        document.getElementById('sampleTexts').value = '';
        // Refresh sample list via HTMX
        htmx.ajax('GET', '/ui/samples/' + encodeURIComponent(this.selectedIntent), { target: '#sampleList', swap: 'innerHTML' });
        this.loadIntents();
      } catch(e) { toast('添加失败: ' + e.message, 'error'); }
    },

    async autoGenerate() {
      if (!this.selectedIntent) return toast('请先选择意图', 'error');
      var btn = document.getElementById('btnAutoGen');
      btn.disabled = true; btn.textContent = '生成中...';
      try {
        var r = await this.api('POST', '/data/generate/' + encodeURIComponent(this.selectedIntent) + '?count=30');
        if (r.ok) {
          toast('LLM生成 ' + r.generated + ' 条，新增 ' + r.added + ' 条');
          htmx.ajax('GET', '/ui/samples/' + encodeURIComponent(this.selectedIntent), { target: '#sampleList', swap: 'innerHTML' });
          this.loadIntents();
        } else {
          toast(r.error || '生成失败', 'error');
        }
      } catch(e) { toast('生成失败: ' + e.message, 'error'); }
      btn.disabled = false; btn.textContent = 'LLM自动生成';
    },

    async loadIntentsForTools() {
      try {
        var r = await this.api('GET', '/data/intents');
        var allIntents = r.map(function(i) { return i.name; });
        var div = document.getElementById('tfIntents');
        if (div) {
          div.innerHTML = allIntents.map(function(i) {
            return '<label style="font-size:12px;cursor:pointer;padding:5px 12px;border:1px solid var(--border);border-radius:16px;display:inline-flex;align-items:center;gap:5px">' +
              '<input type="checkbox" name="intent" value="' + i + '" style="margin:0"> ' + i + '</label>';
          }).join('') || '<span style="color:var(--text-muted);font-size:12px">暂无意图类别，请先在"训练数据"中添加</span>';
        }
      } catch(e) {}
    },

    async loadHealth() {
      try {
        var h = await this.api('GET', '/health');
        var el;
        el = document.getElementById('statusIntent'); if (el) el.innerHTML = '<span class="status-pulse ' + (h.intent_model ? 'on' : 'off') + '"></span>意图';
        el = document.getElementById('statusEmbed'); if (el) el.innerHTML = '<span class="status-pulse ' + (h.embedding_model ? 'on' : 'off') + '"></span>检索';
        el = document.getElementById('statusKb'); if (el) el.innerHTML = '<span class="status-pulse ' + (h.kb_chunks > 0 ? 'on' : 'off') + '"></span>知识库';
        el = document.getElementById('statusTools'); if (el) el.innerHTML = '<span class="status-pulse ' + (h.tool_count > 0 ? 'on' : 'off') + '"></span>工具';
        var grid = document.getElementById('metricsGrid');
        if (grid) {
          grid.innerHTML =
            '<div class="metric"><div class="value">' + h.intent_categories + '</div><div class="label">意图类别</div></div>' +
            '<div class="metric"><div class="value">' + h.uploaded_docs + '</div><div class="label">知识库文档</div></div>' +
            '<div class="metric"><div class="value">' + h.kb_chunks + '</div><div class="label">知识库段落</div></div>' +
            '<div class="metric"><div class="value">' + (h.tool_count || 0) + '</div><div class="label">API 工具</div></div>' +
            '<div class="metric"><div class="value">' + (h.intent_model ? '已加载' : '未加载') + '</div><div class="label">意图模型</div></div>' +
            '<div class="metric"><div class="value">' + (h.embedding_model ? '已加载' : '未加载') + '</div><div class="label">检索模型</div></div>';
        }
      } catch(e) {}
    },

    // ---- Chat ----
    sessionId: 'sess_' + Date.now(),

    clearChat() {
      var _this = this;
      fetch('/ui/chat/session/' + this.sessionId, {
        method: 'DELETE',
        headers: { 'Authorization': 'Bearer ' + this.token }
      }).then(function() {
        _this.sessionId = 'sess_' + Date.now();
        var box = document.getElementById('chatBox');
        // Fetch empty chat state from server
        htmx.ajax('GET', '/ui/chat/empty', { target: '#chatBox', swap: 'innerHTML' });
        toast('对话已刷新');
      }).catch(function() {
        _this.sessionId = 'sess_' + Date.now();
        htmx.ajax('GET', '/ui/chat/empty', { target: '#chatBox', swap: 'innerHTML' });
      });
    },

    // ---- Polling for training jobs ----
    pollJob(jobId, statusElId, btn) {
      var el = document.getElementById(statusElId);
      if (!el) return;
      el.innerHTML = '<span class="tag tag-blue">queued</span> 排队中...';
      var _this = this;
      var iv = setInterval(async function() {
        try {
          var j = await _this.api('GET', '/train/jobs/' + jobId);
          if (j.status === 'completed') {
            el.innerHTML = '<span class="tag tag-green">完成</span> ' + (j.message || '');
            if (btn) { btn.disabled = false; btn.textContent = '重新训练'; }
            clearInterval(iv);
            toast('训练完成！请点击"重新加载模型"');
            _this.loadJobs();
          } else if (j.status === 'failed') {
            el.innerHTML = '<span class="tag tag-red">失败</span> ' + (j.message || '');
            if (btn) { btn.disabled = false; btn.textContent = '重试'; }
            clearInterval(iv);
            _this.loadJobs();
          } else {
            el.innerHTML = '<span class="tag tag-blue">' + j.status + '</span> ' + (j.message || '') +
              ' <div class="progress-bar" style="width:200px;display:inline-block;vertical-align:middle"><div class="fill" style="width:' + ((j.progress || 0) * 100).toFixed(0) + '%"></div></div>';
          }
        } catch(e) { clearInterval(iv); }
      }, 2000);
    },

    async loadJobs() {
      var div = document.getElementById('jobList');
      if (!div) return;
      try {
        var jobs = await this.api('GET', '/train/jobs');
        if (!jobs.length) { div.innerHTML = '<span style="color:var(--text-muted)">无训练任务</span>'; return; }
        div.innerHTML = jobs.map(function(j) {
          return '<div style="padding:9px 0;border-bottom:1px solid var(--border-light);font-size:13px">' +
            '<span class="tag tag-' + (j.status === 'completed' ? 'green' : j.status === 'failed' ? 'red' : 'blue') + '">' + j.status + '</span> ' +
            (j.type || '') + ' · ' + (j.message || '') + ' · ' + ((j.progress || 0) * 100).toFixed(0) + '%</div>';
        }).join('');
      } catch(e) { div.innerHTML = '<span style="color:var(--text-muted)">加载失败</span>'; }
    },

    // ---- Training actions ----
    async trainIntent() {
      var btn = document.getElementById('btnTrainIntent');
      btn.disabled = true; btn.textContent = '训练中...';
      try {
        var r = await this.api('POST', '/train/intent');
        toast('训练任务已启动: ' + r.job_id);
        this.pollJob(r.job_id, 'intentJobStatus', btn);
      } catch(e) { toast('启动失败: ' + e.message, 'error'); btn.disabled = false; btn.textContent = '开始训练'; }
    },

    async trainEmbedding() {
      var btn = document.getElementById('btnTrainEmbed');
      btn.disabled = true; btn.textContent = '训练中...';
      try {
        var r = await this.api('POST', '/train/embedding');
        toast('训练任务已启动: ' + r.job_id);
        this.pollJob(r.job_id, 'embedJobStatus', btn);
      } catch(e) { toast('启动失败: ' + e.message, 'error'); btn.disabled = false; btn.textContent = '开始微调'; }
    },

    async reloadModels() {
      try {
        var r = await this.api('POST', '/models/reload');
        toast('模型重载完成');
        this.loadHealth();
      } catch(e) { toast('重载失败: ' + e.message, 'error'); }
    },

    async rebuildKB() {
      var btn = document.getElementById('btnRebuildKB');
      var span = document.getElementById('rebuildStatus');
      btn.disabled = true; btn.textContent = '重建中...';
      span.innerHTML = '<span class="tag tag-blue">running</span> 正在重建索引...';
      try {
        var r = await this.api('POST', '/models/rebuild-kb');
        if (r.ok) {
          span.innerHTML = '<span class="tag tag-green">完成</span> ' + r.chunks + ' 个段落';
          toast('知识库重建完成: ' + r.chunks + ' 个段落');
          this.loadHealth();
        } else {
          span.innerHTML = '<span class="tag tag-red">失败</span> ' + (r.error || '');
          toast('重建失败', 'error');
        }
      } catch(e) { toast('请求失败: ' + e.message, 'error'); span.innerHTML = ''; }
      btn.disabled = false; btn.textContent = '🔨 重建知识库索引';
    },
  };
}

// ================================================================
// Optimistic chat — append user message immediately, before LLM responds
// ================================================================

function appendUserMessage(text) {
  var escaped = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
  var html = '<div class="chat-msg user">' +
    '<div class="avatar-sm">👤</div>' +
    '<div class="body"><div class="bubble">' + escaped + '</div></div>' +
    '</div>';
  document.getElementById('chatBox').insertAdjacentHTML('beforeend', html);
  // Scroll to bottom for the user message
  var box = document.getElementById('chatBox');
  requestAnimationFrame(function() { box.scrollTop = box.scrollHeight; });
}

// ================================================================
// HTMX event listeners (after Alpine swaps DOM)
// ================================================================

// ---- Chat send/stop button toggle ----
window._activeChatXhr = null;

function _showChatStop() {
  window._activeChatXhr = null;
  document.getElementById('btnSend').style.display = 'none';
  document.getElementById('btnStop').style.display = 'inline-flex';
  // Disable suggestion tags during request
  document.querySelectorAll('.suggestion-tag').forEach(function(el) {
    el.style.pointerEvents = 'none';
    el.style.opacity = '0.5';
  });
}
function _hideChatStop() {
  window._activeChatXhr = null;
  document.getElementById('btnSend').style.display = '';
  document.getElementById('btnStop').style.display = 'none';
  // Re-enable suggestion tags
  document.querySelectorAll('.suggestion-tag').forEach(function(el) {
    el.style.pointerEvents = '';
    el.style.opacity = '';
  });
}

document.body.addEventListener('htmx:beforeRequest', function(evt) {
  var isChatRequest = evt.detail.target.id === 'chatBox' && evt.detail.requestConfig.verb === 'post';
  if (!isChatRequest) return;

  // Validate non-empty for form submits
  if (evt.detail.elt.id === 'chatForm') {
    var input = document.getElementById('chatInput');
    if (!input || !input.value.trim()) {
      evt.preventDefault();
      toast('请输入内容', 'error');
      return;
    }
  }

  // Reset stopped flag for new request
  window._chatStopped = false;
  window._activeChatXhr = evt.detail.xhr;
  _showChatStop();
});

// Prevent aborted requests from swapping content into chat
document.body.addEventListener('htmx:beforeSwap', function(evt) {
  if (window._chatStopped && evt.detail.target.id === 'chatBox') {
    evt.preventDefault();
    window._chatStopped = false;
  }
});

document.body.addEventListener('htmx:afterRequest', function(evt) {
  if (evt.detail.target.id === 'chatBox' && evt.detail.requestConfig && evt.detail.requestConfig.verb === 'post') {
    _hideChatStop();
  }
});

function stopChatRequest() {
  window._chatStopped = true;
  if (window._activeChatXhr) {
    window._activeChatXhr.abort();
    window._activeChatXhr = null;
  }
  // Remove welcome / suggestion tags
  var empty = document.getElementById('chatEmpty');
  if (empty) empty.remove();
  _hideChatStop();
  var t = document.getElementById('chatThinking');
  if (t) t.classList.remove('htmx-request');
}

document.body.addEventListener('htmx:afterSwap', function(evt) {
  // Scroll chat to bottom after new messages
  var chatBox = document.getElementById('chatBox');
  if (chatBox && (evt.detail.target === chatBox || chatBox.contains(evt.detail.target))) {
    requestAnimationFrame(function() {
      chatBox.scrollTop = chatBox.scrollHeight;
    });
  }
});

// Refresh events — when HTMX triggers custom events, re-fetch lists
document.body.addEventListener('toastError', function() {
  toast('请先勾选文档', 'error');
});

document.body.addEventListener('toastOk', function() {
  toast('已成功加入知识库');
});

document.body.addEventListener('refreshDocs', function() {
  htmx.ajax('GET', '/ui/docs', { target: '#docList', swap: 'innerHTML' });
  htmx.ajax('GET', '/ui/domains', { target: '#docDomain', swap: 'innerHTML' });
});

document.body.addEventListener('refreshTools', function() {
  htmx.ajax('GET', '/ui/tools', { target: '#toolList', swap: 'innerHTML' });
});

document.body.addEventListener('refreshUsers', function() {
  htmx.ajax('GET', '/ui/users', { target: '#userList', swap: 'innerHTML' });
});

document.body.addEventListener('refreshRoles', function() {
  htmx.ajax('GET', '/ui/roles', { target: '#roleList', swap: 'innerHTML' });
});

document.body.addEventListener('refreshHealth', function() {
  htmx.ajax('GET', '/ui/health', { target: '#metricsGrid', swap: 'outerHTML' });
});

document.body.addEventListener('refreshJobs', function() {
  htmx.ajax('GET', '/ui/jobs', { target: '#jobList', swap: 'innerHTML' });
});

// When an intent is deleted, refresh the list
document.body.addEventListener('intentDeleted', function() {
  var app = document.querySelector('[x-data]')._x_dataStack[0];
  if (app && app.loadIntents) app.loadIntents();
});

// When training starts, begin polling
document.body.addEventListener('trainStarted', function() {
  var app = document.querySelector('[x-data]')._x_dataStack[0];
  if (app && app.loadJobs) app.loadJobs();
});

// When models are reloaded, refresh health
document.body.addEventListener('modelsReloaded', function() {
  var app = document.querySelector('[x-data]')._x_dataStack[0];
  if (app && app.loadHealth) app.loadHealth();
});

// When KB is rebuilt, refresh health
document.body.addEventListener('kbRebuilt', function() {
  var app = document.querySelector('[x-data]')._x_dataStack[0];
  if (app && app.loadHealth) app.loadHealth();
});

// When prompt is saved, show indicator temporarily
document.body.addEventListener('promptSaved', function() {
  var el = document.getElementById('promptSaved');
  if (el) {
    el.style.display = 'inline';
    setTimeout(function() { el.style.display = 'none'; }, 2000);
  }
});

// ================================================================
// HTMX config — include auth token in all requests
// ================================================================

document.body.addEventListener('htmx:configRequest', function(evt) {
  var token = localStorage.getItem('token');
  if (token) {
    evt.detail.headers['Authorization'] = 'Bearer ' + token;
  }
});

// Handle 401 from HTMX responses
document.body.addEventListener('htmx:responseError', function(evt) {
  if (evt.detail.xhr && evt.detail.xhr.status === 401) {
    localStorage.removeItem('token');
    window.location.href = '/login';
  }
});
