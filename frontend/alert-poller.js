/**
 * vpastock Alert Poller
 * Shared script chay tren 3 trang: watchlist, stock-detail, screener
 * 
 * Workflow:
 * 1. Request browser notification permission (1 lan)
 * 2. Poll /api/watchlist/alert/triggered moi 30s
 * 3. Neu co alert moi -> show:
 *    a. Browser notification (neu da grant)
 *    b. In-page toast (luon show)
 * 4. ACK alert ngay de khong notify lai
 */
(function () {
  // ===== CONFIG =====
  const POLL_INTERVAL = 30000; // 30s
  const INITIAL_DELAY = 5000;  // 5s sau khi load trang
  const LAST_CHECK_KEY = 'vpastock_last_alert_check';
  const USER_FP_KEY = 'vpastock_user_fp';

  // API URL detect: same logic with screener/stock-detail
  const API = window.location.origin.includes('localhost') || window.location.origin.includes('127.0.0.1')
    ? 'http://localhost:8000'
    : window.location.origin;

  // ===== INJECT CSS FOR TOAST =====
  const style = document.createElement('style');
  style.textContent = `
    #vpastock-toast-container {
      position: fixed;
      top: 70px;
      right: 20px;
      z-index: 99999;
      display: flex;
      flex-direction: column;
      gap: 10px;
      max-width: 360px;
      pointer-events: none;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }
    .vpastock-toast {
      background: #161b22;
      border: 1px solid #2a313c;
      border-left: 3px solid #ff9800;
      border-radius: 8px;
      padding: 12px 16px;
      box-shadow: 0 8px 24px rgba(0,0,0,0.6);
      color: #e6edf3;
      pointer-events: auto;
      cursor: pointer;
      animation: vpastock-toast-in 0.3s ease-out;
      transition: opacity 0.3s, transform 0.3s;
      min-width: 280px;
    }
    .vpastock-toast.fade-out {
      opacity: 0;
      transform: translateX(20px);
    }
    .vpastock-toast .vp-toast-head {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 6px;
    }
    .vpastock-toast .vp-toast-emoji {
      font-size: 18px;
    }
    .vpastock-toast .vp-toast-sym {
      font-weight: 700;
      color: #5b8def;
      font-size: 14px;
      flex: 1;
    }
    .vpastock-toast .vp-toast-close {
      background: none;
      border: none;
      color: #6b7280;
      cursor: pointer;
      font-size: 16px;
      padding: 0 4px;
    }
    .vpastock-toast .vp-toast-close:hover { color: #e6edf3; }
    .vpastock-toast .vp-toast-body {
      font-size: 12px;
      color: #94a3b8;
      line-height: 1.5;
      font-family: 'Courier New', 'Consolas', monospace;
    }
    .vpastock-toast .vp-toast-body b {
      color: #3dd9c4;
    }
    .vpastock-toast .vp-toast-note {
      font-size: 11px;
      color: #6b7280;
      margin-top: 4px;
      font-style: italic;
    }
    @keyframes vpastock-toast-in {
      from {
        opacity: 0;
        transform: translateX(40px);
      }
      to {
        opacity: 1;
        transform: translateX(0);
      }
    }
  `;
  document.head.appendChild(style);

  // ===== INJECT TOAST CONTAINER =====
  function ensureToastContainer() {
    let c = document.getElementById('vpastock-toast-container');
    if (!c) {
      c = document.createElement('div');
      c.id = 'vpastock-toast-container';
      document.body.appendChild(c);
    }
    return c;
  }

  // ===== SHOW TOAST =====
  function showToast(alert) {
    const container = ensureToastContainer();
    
    const labels = {
      price_above: 'vượt',
      price_below: 'xuống dưới',
      pct_change: 'thay đổi',
    };
    const label = labels[alert.alert_type] || alert.alert_type;
    
    const toast = document.createElement('div');
    toast.className = 'vpastock-toast';
    toast.innerHTML = `
      <div class="vp-toast-head">
        <span class="vp-toast-emoji">🔔</span>
        <span class="vp-toast-sym">${alert.symbol}</span>
        <button class="vp-toast-close" title="Đóng">✕</button>
      </div>
      <div class="vp-toast-body">
        Giá ${label} <b>${alert.threshold.toLocaleString('vi-VN')}</b>
        ${alert.note ? `<div class="vp-toast-note">📝 ${escapeHtml(alert.note)}</div>` : ''}
      </div>
    `;
    
    // Click on toast (not close button) -> open stock detail
    toast.addEventListener('click', (e) => {
      if (e.target.classList.contains('vp-toast-close')) return;
      window.open(`stock-detail-live.html?sym=${alert.symbol}`, '_blank');
      removeToast(toast);
    });
    
    // Close button
    toast.querySelector('.vp-toast-close').addEventListener('click', (e) => {
      e.stopPropagation();
      removeToast(toast);
    });
    
    container.appendChild(toast);
    
    // Auto remove after 15s
    setTimeout(() => removeToast(toast), 15000);
  }

  function removeToast(toast) {
    if (!toast || !toast.parentNode) return;
    toast.classList.add('fade-out');
    setTimeout(() => toast.remove(), 300);
  }

  function escapeHtml(s) {
    if (!s) return '';
    return String(s).replace(/[<>&'"]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;',"'":'&#39;','"':'&quot;'}[c]));
  }

  // ===== SHOW BROWSER NOTIFICATION =====
  function showBrowserNotification(alert) {
    if (!('Notification' in window)) return;
    if (Notification.permission !== 'granted') return;
    
    const labels = {
      price_above: 'vượt',
      price_below: 'xuống dưới',
      pct_change: 'thay đổi',
    };
    const label = labels[alert.alert_type] || alert.alert_type;
    
    try {
      const n = new Notification(`🔔 vpastock - ${alert.symbol}`, {
        body: `Giá ${label} ${alert.threshold.toLocaleString('vi-VN')}${alert.note ? '\n📝 ' + alert.note : ''}`,
        icon: '/favicon.ico',
        tag: `alert-${alert.id}`,
        requireInteraction: false,
      });
      n.onclick = () => {
        window.focus();
        window.open(`stock-detail-live.html?sym=${alert.symbol}`, '_blank');
        n.close();
      };
    } catch (err) {
      console.warn('Notification failed:', err);
    }
  }

  // ===== POLL ALERTS =====
  async function pollAlerts() {
    const fp = localStorage.getItem(USER_FP_KEY);
    if (!fp) return;
    
    const lastCheck = localStorage.getItem(LAST_CHECK_KEY) || '';
    
    try {
      const sinceParam = lastCheck ? `&since=${encodeURIComponent(lastCheck)}` : '';
      const res = await fetch(`${API}/api/watchlist/alert/triggered?user_fp=${fp}${sinceParam}`);
      if (!res.ok) return;
      
      const data = await res.json();
      const alerts = data.alerts || [];
      
      for (const alert of alerts) {
        // Show both: toast in-page + browser notification
        showToast(alert);
        showBrowserNotification(alert);
        
        // ACK ngay de khong notify lai
        try {
          await fetch(`${API}/api/watchlist/alert/${alert.id}/ack?user_fp=${fp}`, {
            method: 'POST',
          });
        } catch (e) {
          console.warn('ACK failed:', e);
        }
      }
      
      // Update last check time
      localStorage.setItem(LAST_CHECK_KEY, new Date().toISOString());
    } catch (err) {
      console.warn('[AlertPoller] Failed:', err);
    }
  }

  // ===== REQUEST PERMISSION =====
  function requestPermissionOnce() {
    if (!('Notification' in window)) return;
    if (Notification.permission === 'default') {
      // Hoi sau 3s de khong block UI luc load
      setTimeout(() => {
        Notification.requestPermission().then(p => {
          console.log('[AlertPoller] Notification permission:', p);
        });
      }, 3000);
    }
  }

  // ===== INIT =====
  function init() {
    requestPermissionOnce();
    
    // Poll lan dau sau 5s
    setTimeout(pollAlerts, INITIAL_DELAY);
    
    // Poll moi 30s
    setInterval(pollAlerts, POLL_INTERVAL);
    
    console.log('[AlertPoller] Started. Poll every', POLL_INTERVAL/1000, 's');
  }

  // Wait for DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
