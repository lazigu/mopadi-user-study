/* annotate.js — MOPADI Annotation Platform helpers */

// Multi-tab detection: warn if the same study is open in another tab
(function () {
  var KEY = 'mopadi_tab_active';
  var tabId = Date.now().toString(36) + Math.random().toString(36).slice(2);

  function claimTab() {
    localStorage.setItem(KEY, JSON.stringify({ id: tabId, ts: Date.now() }));
  }

  function checkMultiTab() {
    try {
      var stored = JSON.parse(localStorage.getItem(KEY) || 'null');
      if (stored && stored.id !== tabId && Date.now() - stored.ts < 8000) {
        var banner = document.createElement('div');
        banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:9999;background:#e67e22;color:#fff;text-align:center;padding:10px 16px;font-size:0.9rem;font-weight:600;';
        banner.textContent = '⚠ This study is open in another tab. Please use only one tab to avoid overwriting your answers.';
        document.body.prepend(banner);
      }
    } catch (e) {}
    claimTab();
  }

  // Check on load and keep heartbeat so other tabs can detect us
  window.addEventListener('load', checkMultiTab);
  setInterval(claimTab, 4000);

  // Clear on unload so navigating away doesn't leave stale claim
  window.addEventListener('pagehide', function () {
    try {
      var stored = JSON.parse(localStorage.getItem(KEY) || 'null');
      if (stored && stored.id === tabId) localStorage.removeItem(KEY);
    } catch (e) {}
  });
})();

// Reset double-submit guard when browser restores page from bfcache (back button)
window.addEventListener('pageshow', function (e) {
  if (e.persisted) {
    document.querySelectorAll('form').forEach(function (f) {
      f._submitted = false;
      f.querySelectorAll('button[type="submit"]').forEach(function (btn) {
        btn.disabled = false;
        btn.style.opacity = '';
      });
    });
  }
});

// Track which submit button was clicked and prevent double-submit
(function () {
  // Record the clicked submitter so we can preserve its value
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('button[type="submit"]');
    if (!btn) return;
    var form = btn.form;
    if (!form) return;
    form._submitter = btn;
  }, true);

  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (form._submitted) {
      e.preventDefault();
      return;
    }
    form._submitted = true;

    // If a submit button triggered this, copy its value to a hidden field
    // so disabling it doesn't lose the value
    var submitter = form._submitter;
    if (submitter && submitter.name) {
      var hidden = document.createElement('input');
      hidden.type = 'hidden';
      hidden.name = submitter.name;
      hidden.value = submitter.value;
      form.appendChild(hidden);
    }

    // Disable submit buttons for visual feedback (safe now — value already captured)
    form.querySelectorAll('button[type="submit"]').forEach(function (btn) {
      btn.disabled = true;
      btn.style.opacity = '0.6';
    });
  });
})();
