/* ============================================================
   StockAI — 公共脚本 (Common JS)
   ============================================================ */

// ==================== 配置 ====================
const API_BASE = '';

// ==================== API 工具 ====================
async function api(path, options = {}) {
  const url = API_BASE + path;
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `HTTP ${res.status}`);
  }
  return res.json();
}

const apiGet = (path) => api(path);
const apiPost = (path, body) => api(path, { method: 'POST', body: JSON.stringify(body) });
const apiPut = (path, body) => api(path, { method: 'PUT', body: JSON.stringify(body) });
const apiDelete = (path) => api(path, { method: 'DELETE' });

// ==================== AI 配置 ====================
function getAIConfig() {
  try {
    const saved = localStorage.getItem('stockai_ai_config');
    if (saved) return JSON.parse(saved);
  } catch (e) {}
  return { provider: 'minimax', apiKey: '', model: 'MiniMax-M2.7' };
}

// ==================== Loading / Empty / Error 状态 ====================
function showLoading(container) {
  container.innerHTML = '<div class="empty-state"><div class="empty-icon">⏳</div><p>加载中…</p></div>';
}
function showEmpty(container, text) {
  container.innerHTML = `<div class="empty-state"><div class="empty-icon">📭</div><p>${text || '暂无数据'}</p></div>`;
}
function showError(container, err) {
  container.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><p>加载失败：${err.message}</p></div>`;
}

// ==================== 侧边栏 ====================
function renderSidebar(activePage) {
  const pages = [
    { id: 'holdings',   href: 'index.html',           icon: '📊', label: '我的持仓' },
    { id: 'watchlist',  href: 'watchlist.html',       icon: '⭐', label: '自选股' },
    { id: 'market',     href: 'market.html',          icon: '💹', label: '大盘指数' },
    { id: 'global',     href: 'global-news.html',    icon: '🌍', label: '全球资讯' },
    { id: 'ai',         href: 'ai-assistant.html',    icon: '🤖', label: 'AI 助手' },
    { id: 'skills',     href: 'skills.html',          icon: '🤖', label: 'Agent 工坊' },
    { id: 'transactions', href: 'transactions.html',  icon: '📝', label: '交易记录' },
  ];
  const bottomPages = [
    { id: 'settings',   href: 'settings.html',        icon: '⚙️', label: '设置' },
  ];

  const navItems = pages.map(p =>
    `<a href="${p.href}" class="nav-item${activePage === p.id ? ' active' : ''}">
      <span class="nav-icon">${p.icon}</span> ${p.label}
    </a>`
  ).join('');

  const bottomItems = bottomPages.map(p =>
    `<a href="${p.href}" class="nav-item${activePage === p.id ? ' active' : ''}">
      <span class="nav-icon">${p.icon}</span> ${p.label}
    </a>`
  ).join('');

  return `
    <div class="logo"><a href="index.html">📈 <span>StockAI</span></a></div>
    <div class="nav-section">${navItems}</div>
    <hr class="nav-divider">
    <div class="nav-section">${bottomItems}</div>
    <hr class="nav-divider">
    <div class="nav-section">
      <a href="login.html" class="nav-item" style="color:var(--text-muted);">
        <span class="nav-icon">🚪</span> 退出登录
      </a>
    </div>
  `;
}

function renderHeader(title) {
  return `
    <h2>${title}</h2>
    <div class="header-actions">
      <span class="text-sm text-secondary" id="updateTime"></span>
      <div class="avatar" title="用户">U</div>
    </div>
  `;
}

// ==================== 移动端底部导航 ====================
function renderMobileNav(activePage) {
  const mainTabs = [
    { id: 'holdings',   href: 'index.html',           icon: '📊', label: '持仓' },
    { id: 'watchlist',  href: 'watchlist.html',       icon: '⭐', label: '自选' },
    { id: 'ai',         href: 'ai-assistant.html',    icon: '🤖', label: 'AI' },
    { id: 'more',       href: '#',                    icon: '⋯', label: '更多', isMore: true },
  ];

  const moreItems = [
    { id: 'market',       href: 'market.html',         icon: '💹', label: '大盘指数' },
    { id: 'global',       href: 'global-news.html',    icon: '🌍', label: '全球资讯' },
    { id: 'skills',       href: 'skills.html',         icon: '🧩', label: 'Agent 工坊' },
    { id: 'transactions', href: 'transactions.html',   icon: '📝', label: '交易记录' },
    { id: 'divider',      href: '',                    icon: '',    label: '', isDivider: true },
    { id: 'settings',     href: 'settings.html',       icon: '⚙️', label: '设置' },
  ];

  const navHTML = mainTabs.map(t => {
    const isActive = activePage === t.id || (t.isMore && ['market','global','skills','transactions','settings'].includes(activePage));
    if (t.isMore) {
      return `<button class="nav-tab${isActive ? ' active' : ''}" onclick="toggleMoreMenu()"><span class="tab-icon">${t.icon}</span>${t.label}</button>`;
    }
    return `<a href="${t.href}" class="nav-tab${isActive ? ' active' : ''}"><span class="tab-icon">${t.icon}</span>${t.label}</a>`;
  }).join('');

  document.body.insertAdjacentHTML('beforeend', `
    <div class="mobile-nav" id="mobileNav">${navHTML}</div>
    <div class="more-menu-overlay" id="moreMenuOverlay" onclick="toggleMoreMenu()">
      <div class="more-menu" onclick="event.stopPropagation()">
        ${moreItems.map(item => {
          if (item.isDivider) return '<div class="more-divider"></div>';
          return `<a href="${item.href}" class="more-item${activePage === item.id ? ' active' : ''}"><span>${item.icon}</span> ${item.label}</a>`;
        }).join('')}
      </div>
    </div>
  `);
}

function toggleMoreMenu() {
  document.getElementById('moreMenuOverlay').classList.toggle('show');
}

function initPage(activePage, title) {
  const sidebar = document.querySelector('.sidebar');
  const header = document.querySelector('.header');
  if (sidebar) sidebar.innerHTML = renderSidebar(activePage);
  if (header) header.innerHTML = renderHeader(title);
  renderMobileNav(activePage);
  updateClock();
  setInterval(updateClock, 30000);
}

function updateClock() {
  const el = document.getElementById('updateTime');
  if (el) el.textContent = '更新: ' + new Date().toLocaleString('zh-CN');
}

// ==================== 格式化工具 ====================
function formatMoney(num) {
  if (num == null) return '-';
  return '¥' + Number(num).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatPercent(num) {
  if (num == null) return '-';
  const sign = num >= 0 ? '+' : '';
  return sign + Number(num).toFixed(2) + '%';
}

function getChangeClass(num) {
  if (num > 0) return 'up';
  if (num < 0) return 'down';
  return '';
}

// ==================== 市场标签 ====================
function getMarketTag(market) {
  if (!market) return '';
  const map = { SH: 'tag tag-sh', SZ: 'tag tag-sz', BJ: 'tag tag-bj', KC: 'tag tag-sh' };
  return `<span class="${map[market] || 'tag'}">${market === 'SH' ? '沪' : market === 'SZ' ? '深' : market === 'BJ' ? '北' : market}</span>`;
}

function marketToApi(m) {
  if (m === 'SH') return '1';
  if (m === 'SZ') return '0';
  if (m === 'BJ') return '0';
  return null;
}

function codeToMarket(code) {
  if (code.startsWith('60') || code.startsWith('68')) return 'SH';
  if (code.startsWith('4') || code.startsWith('8')) return 'BJ';
  return 'SZ';
}

// ==================== AI 对话 ====================
function setupAIChat() {
  const messages = document.getElementById('aiMessages');
  const input = document.getElementById('aiInput');
  const sendBtn = document.getElementById('aiSend');
  if (!input || !sendBtn || !messages) return;
  let conversationId = null;

  function addMessage(text, role) {
    const div = document.createElement('div');
    div.className = 'ai-msg ' + role;
    div.textContent = text;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  async function handleSend() {
    const query = input.value.trim();
    if (!query) return;
    addMessage(query, 'user');
    input.value = '';

    const aiConfig = getAIConfig();
    if (!aiConfig.apiKey) {
      addMessage('请先在 <a href="settings.html">设置页</a> 配置 API Key', 'assistant');
      return;
    }

    try {
      const data = await apiPost('/api/ai/chat', {
        message: query,
        conversationId,
        provider: aiConfig.provider,
        apiKey: aiConfig.apiKey,
        model: aiConfig.model,
        baseUrl: aiConfig.baseUrl || '',
      });
      conversationId = data.conversationId;
      addMessage(data.reply, 'assistant');
    } catch (err) {
      addMessage('发送失败: ' + err.message, 'assistant');
    }
  }

  sendBtn.addEventListener('click', handleSend);
  input.addEventListener('keydown', e => { if (e.key === 'Enter') handleSend(); });
}

// ==================== Dialog/Confirm/Prompt ====================
function showDialog(title, msg, onOk) {
  const overlay = document.createElement('div');
  overlay.className = 'dialog-overlay';
  overlay.innerHTML = `<div class="dialog-box">
    <div class="dialog-title">${title}</div>
    ${msg ? '<p class="dialog-msg">'+msg+'</p>' : ''}
    <div class="dialog-actions">
      <button class="btn btn-outline btn-sm dialog-cancel">取消</button>
      <button class="btn btn-primary btn-sm dialog-ok">确定</button>
    </div>
  </div>`;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.querySelector('.dialog-cancel').addEventListener('click', close);
  overlay.querySelector('.dialog-ok').addEventListener('click', () => { close(); onOk(); });
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
}

function showConfirm(msg, onOk) { showDialog('确认', msg, onOk); }

function showPrompt(msg, defaultValue = '') {
  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.className = 'dialog-overlay';
    overlay.innerHTML = `<div class="dialog-box">
      <p class="dialog-msg">${msg}</p>
      <input class="form-input dialog-input" value="${defaultValue.replace(/"/g,'&quot;')}" autofocus>
      <div class="dialog-actions">
        <button class="btn btn-outline btn-sm dialog-cancel">取消</button>
        <button class="btn btn-primary btn-sm dialog-ok">确定</button>
      </div>
    </div>`;
    document.body.appendChild(overlay);
    const input = overlay.querySelector('.dialog-input');
    const close = () => { overlay.remove(); resolve(null); };
    const ok = () => { const v = input.value.trim(); overlay.remove(); resolve(v || null); };
    overlay.querySelector('.dialog-cancel').addEventListener('click', close);
    overlay.querySelector('.dialog-ok').addEventListener('click', ok);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') ok(); });
    input.focus();
  });
}

// ==================== Toast 通知 ====================
function showToast(msg, type = 'info', duration = 3000) {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
  }
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  const icons = { success: '✓', error: '✕', warning: '⚠', info: 'ℹ' };
  toast.innerHTML = `<span class="toast-icon">${icons[type] || icons.info}</span><span class="toast-msg">${msg}</span><span class="toast-close" onclick="this.closest('.toast').remove()">×</span>`;
  container.appendChild(toast);
  if (duration > 0) {
    setTimeout(() => {
      toast.classList.add('toast-out');
      setTimeout(() => toast.remove(), 200);
    }, duration);
  }
}
