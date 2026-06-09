/* ============================================================
   StockAI — 公共脚本 (Common JS)
   ============================================================ */

// ==================== 配置 ====================
const API_BASE = '';

// ==================== 认证 ====================
function getToken() {
  try { return localStorage.getItem('stockai_token'); } catch(e) { return null; }
}
function setToken(token) {
  try { localStorage.setItem('stockai_token', token); } catch(e) {}
}
function clearToken() {
  try { localStorage.removeItem('stockai_token'); } catch(e) {}
}

function requireAuth() {
  // 登录页不需要重定向
  if (window.location.pathname.endsWith('login.html')) return;
  if (!getToken()) {
    window.location.href = 'login.html';
  }
}

// ==================== API 工具 ====================
async function api(path, options = {}) {
  const token = getToken();
  const headers = { 'Content-Type': 'application/json', ...options.headers };
  if (token) {
    headers['Authorization'] = 'Bearer ' + token;
  }

  const url = API_BASE + path;
  const res = await fetch(url, { headers, ...options });

  // 401 → 跳转登录页
  if (res.status === 401) {
    clearToken();
    if (!window.location.pathname.endsWith('login.html')) {
      window.location.href = 'login.html';
    }
    throw new Error('未登录');
  }

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
  // 优先从 localStorage 读（快速），同时返回标记表示是否已配置
  try {
    const saved = localStorage.getItem('stockai_ai_config');
    if (saved) {
      const cfg = JSON.parse(saved);
      if (cfg.apiKey) return cfg;
    }
  } catch (e) {}
  // 返回空配置，后端会从 settings 表读取已保存的 Key
  return { provider: '', apiKey: '', model: '' };
}

// ==================== Loading / Empty / Error 状态 ====================
function showLoading(container) {
  container.innerHTML = `<div class="skeleton-card">
    <div class="skeleton skeleton-title"></div>
    <div class="skeleton skeleton-row"><div class="skeleton skeleton-cell"></div><div class="skeleton skeleton-cell"></div><div class="skeleton skeleton-cell-sm"></div></div>
    <div class="skeleton skeleton-row"><div class="skeleton skeleton-cell"></div><div class="skeleton skeleton-cell"></div><div class="skeleton skeleton-cell-sm"></div></div>
  </div>`;
}
function showEmpty(container, text, ctaText, ctaHref) {
  const cta = ctaText ? `<a href="${ctaHref || '#'}" class="btn btn-primary" style="margin-top:16px">${ctaText}</a>` : '';
  container.innerHTML = `<div class="empty-state">
    <svg class="empty-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 5v14M5 12h14"/></svg>
    <p>${text || '暂无数据'}</p>
    ${cta}
  </div>`;
}
function showError(container, err, retryFn) {
  const retry = retryFn ? `<button class="btn btn-retry" onclick="(${retryFn.toString()})()">重新加载</button>` : '';
  container.innerHTML = `<div class="empty-state error-state">
    <svg class="empty-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/></svg>
    <p>${err?.message || err || '加载失败'}</p>
    ${retry}
  </div>`;
}

// ==================== 共享 SVG 图标 (Heroicons MIT) ====================
var STOCKAI_ICONS = {
  holdings:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 9h18M9 3v18"/></svg>',
  watchlist:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 15 9 22 9 16 14 18 22 12 17 6 22 8 14 2 9 9 9"/></svg>',
  market:     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>',
  global:     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15 15 0 000 20"/></svg>',
  review:     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 012-2h2a2 2 0 012 2M9 14l2 2 4-4"/></svg>',
  quant:      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><path d="M7 16l4-8 4 4 4-8"/></svg>',
  skills:     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="20" rx="5"/><path d="M7 8h10M7 12h10M7 16h6"/></svg>',
  transactions: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 014-4h14"/><path d="M7 23l-4-4 4-4"/><path d="M21 13v2a4 4 0 01-4 4H3"/></svg>',
  settings:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"/></svg>',
  ai:         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>',
  success:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>',
  error:      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
  warning:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
  info:       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
  close:      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
  more:       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/></svg>',
};

// ==================== 侧边栏 ====================
function renderSidebar(activePage) {
  var I = STOCKAI_ICONS;
  var pages = [
    { id: 'holdings',   href: 'index.html',           icon: I.holdings, label: '我的持仓' },
    { id: 'watchlist',  href: 'watchlist.html',       icon: I.watchlist, label: '自选股' },
    { id: 'market',     href: 'market.html',          icon: I.market, label: '大盘指数' },
    { id: 'global',     href: 'global-news.html',    icon: I.global, label: '全球资讯' },
    { id: 'review',     href: 'review.html',          icon: I.review, label: 'AI 复盘' },
    { id: 'quant',      href: 'quant.html',          icon: I.quant, label: '量化分析' },
    { id: 'screener',   href: 'screener.html',       icon: '🔎', label: 'AI选股' },
    { id: 'skills',     href: 'skills.html',          icon: I.skills, label: 'Agent 工坊' },
    { id: 'transactions', href: 'transactions.html',  icon: I.transactions, label: '交易记录' },
  ];
  var bottomPages = [
    { id: 'settings',   href: 'settings.html',        icon: I.settings, label: '设置' },
    { id: 'ai-chat',    href: 'ai-assistant.html',    icon: I.ai, label: 'AI 对话' },
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
    <div class="logo"><a href="index.html"><svg class="logo-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg> <span>StockAI</span></a></div>
    <div class="nav-section">${navItems}</div>
    <hr class="nav-divider">
    <div class="nav-section">${bottomItems}</div>
    <hr class="nav-divider">
    <div class="nav-section shortcut-hint">
      <kbd>G</kbd> <kbd>H</kbd> 首页 &middot; <kbd>G</kbd> <kbd>A</kbd> 复盘 &middot; <kbd>?</kbd> 快捷键
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
  var I = STOCKAI_ICONS;
  var mainTabs = [
    { id: 'holdings',   href: 'index.html',           icon: I.holdings, label: '持仓' },
    { id: 'watchlist',  href: 'watchlist.html',       icon: I.watchlist, label: '自选' },
    { id: 'ai',         href: 'ai-assistant.html',    icon: I.ai, label: 'AI' },
    { id: 'more',       href: '#',                    icon: I.more, label: '更多', isMore: true },
  ];

  var moreItems = [
    { id: 'market',       href: 'market.html',         icon: I.market, label: '大盘指数' },
    { id: 'global',       href: 'global-news.html',    icon: I.global, label: '全球资讯' },
    { id: 'review',       href: 'review.html',         icon: I.review, label: 'AI 复盘' },
    { id: 'quant',        href: 'quant.html',          icon: I.quant, label: '量化分析' },
    { id: 'screener',     href: 'screener.html',       icon: '🔎', label: 'AI选股' },
    { id: 'skills',       href: 'skills.html',         icon: I.skills, label: 'Agent 工坊' },
    { id: 'transactions', href: 'transactions.html',   icon: I.transactions, label: '交易记录' },
    { id: 'divider',      href: '',                    icon: '',    label: '', isDivider: true },
    { id: 'settings',     href: 'settings.html',       icon: I.settings, label: '设置' },
  ];

  const navHTML = mainTabs.map(t => {
    const isActive = activePage === t.id || (t.isMore && ['market','global','review','screener','skills','transactions','settings'].includes(activePage));
    if (t.isMore) {
      const morePages = ['market','global','review','screener','skills','transactions','settings'];
      return `<button class="nav-tab${morePages.includes(activePage) ? ' active' : ''}" onclick="toggleMoreMenu()"><span class="tab-icon">${t.icon}</span>${t.label}</button>`;
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
  requireAuth();
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
  const icons = {
    success: '<span class="toast-icon-svg">' + STOCKAI_ICONS.success + '</span>',
    error:   '<span class="toast-icon-svg">' + STOCKAI_ICONS.error + '</span>',
    warning: '<span class="toast-icon-svg">' + STOCKAI_ICONS.warning + '</span>',
    info:    '<span class="toast-icon-svg">' + STOCKAI_ICONS.info + '</span>',
  };
  toast.innerHTML = `${icons[type] || icons.info}<span class="toast-msg">${msg}</span><span class="toast-close" onclick="this.closest('.toast').remove()">${STOCKAI_ICONS.close}</span>`;
  container.appendChild(toast);
  if (duration > 0) {
    setTimeout(() => {
      toast.classList.add('toast-out');
      setTimeout(() => toast.remove(), 200);
    }, duration);
  }
}

// ==================== 键盘快捷键 ====================
document.addEventListener('keydown', function(e) {
  // Only fire when no input/textarea/contenteditable is focused
  const tag = document.activeElement?.tagName?.toLowerCase();
  if (tag === 'input' || tag === 'textarea' || document.activeElement?.isContentEditable) return;

  if (e.key === '?' && !e.ctrlKey && !e.metaKey) {
    e.preventDefault();
    showShortcutHelp();
    return;
  }

  // Two-key shortcuts: G + H/M/A
  if (e.key === 'g' || e.key === 'G') {
    window._shortcutPrefix = 'g';
    clearTimeout(window._shortcutTimer);
    window._shortcutTimer = setTimeout(function() { window._shortcutPrefix = null; }, 1500);
    return;
  }
  if (window._shortcutPrefix === 'g') {
    window._shortcutPrefix = null;
    if (e.key === 'h' || e.key === 'H') { window.location.href = 'index.html'; }
    else if (e.key === 'm' || e.key === 'M') { window.location.href = 'market.html'; }
    else if (e.key === 'a' || e.key === 'A') { window.location.href = 'review.html'; }
  }
});

function showShortcutHelp() {
  var existing = document.getElementById('shortcut-dialog');
  if (existing) { existing.remove(); return; }
  var d = document.createElement('div');
  d.id = 'shortcut-dialog';
  d.className = 'dialog-overlay';
  d.innerHTML = `<div class="dialog" style="max-width:360px">
    <h3>键盘快捷键</h3>
    <div class="shortcut-list">
      <div class="shortcut-row"><kbd>G</kbd> <kbd>H</kbd> <span>首页 — 持仓仪表盘</span></div>
      <div class="shortcut-row"><kbd>G</kbd> <kbd>M</kbd> <span>大盘指数</span></div>
      <div class="shortcut-row"><kbd>G</kbd> <kbd>A</kbd> <span>AI 复盘报告</span></div>
      <div class="shortcut-row"><kbd>?</kbd> <span>显示/隐藏快捷键帮助</span></div>
    </div>
    <button class="btn btn-primary" onclick="document.getElementById('shortcut-dialog').remove()" style="margin-top:16px;width:100%">关闭</button>
  </div>`;
  d.onclick = function(e) { if (e.target === d) d.remove(); };
  document.body.appendChild(d);
}
