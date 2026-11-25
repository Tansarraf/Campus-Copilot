/**
 * Student Smart Notifications — bell in the navbar, panel as a fixed overlay.
 * Depends on globals from app.js: api, el, escapeHtml, state, showToast, openDocumentFile.
 */
(function () {
  const POLL_MS = 25000;
  let pollTimer = null;
  let itemsCache = [];
  let unreadCount = 0;
  let panelOpen = false;

  function formatRelative(iso) {
    if (!iso) return "";
    const then = new Date(iso);
    const thenMs = then.getTime();
    if (Number.isNaN(thenMs)) return "";
    const diff = Date.now() - thenMs;
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "Just now";
    if (mins === 1) return "1 minute ago";
    if (mins < 60) return `${mins} minutes ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs === 1) return "1 hour ago";
    if (hrs < 24) return `${hrs} hours ago`;
    const startToday = new Date();
    startToday.setHours(0, 0, 0, 0);
    const startThen = new Date(then);
    startThen.setHours(0, 0, 0, 0);
    const dayDelta = Math.round((startToday - startThen) / 86400000);
    if (dayDelta === 1) return "Yesterday";
    if (dayDelta > 1 && dayDelta < 7) return `${dayDelta} days ago`;
    return then.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  function typeMeta(type) {
    const map = {
      document_new: { label: "Open document", kind: "document", hint: "Open document" },
      document_superseded: { label: "Updated notice", kind: "update", hint: "Open document" },
      calendar_new: { label: "Calendar", kind: "calendar", hint: "View calendar" },
      calendar_updated: { label: "Calendar change", kind: "changed", hint: "View calendar" },
      calendar_cancelled: { label: "Cancelled", kind: "cancelled", hint: "View calendar" },
      deadline_reminder: { label: "Deadline", kind: "deadline", hint: "View calendar" },
    };
    return map[type] || { label: "Update", kind: "document", hint: "Open" };
  }

  function iconSvg(kind) {
    const paths = {
      document: '<path fill="currentColor" d="M7 3.5h7.2L19 8.3V20a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 6 20V5A1.5 1.5 0 0 1 7.5 3.5H7zm7 1.2V9h4.2"/>',
      update: '<path fill="currentColor" d="M12 5a7 7 0 1 1-6.3 4H8a5 5 0 1 0 1.5-3.5L8 7V3h4l-1.4 1.4A6.9 6.9 0 0 1 12 5z"/>',
      calendar: '<path fill="currentColor" d="M7 3h2v2h6V3h2v2h2.2A1.8 1.8 0 0 1 21 6.8v12.4A1.8 1.8 0 0 1 19.2 21H4.8A1.8 1.8 0 0 1 3 19.2V6.8A1.8 1.8 0 0 1 4.8 5H7V3zm12 7H5v9.2c0 .2.1.3.3.3h13.4c.2 0 .3-.1.3-.3V10z"/>',
      changed: '<path fill="currentColor" d="M4 6.5A2.5 2.5 0 0 1 6.5 4H14l6 6v9.5a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 19.5v-13zM14 5.5V10h4.5M8 14h8M8 17h5"/>',
      cancelled: '<path fill="currentColor" d="M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17zm3.2 4.3-1.1-1.1L12 8.8 9.9 6.7 8.8 7.8 10.9 10 8.8 12.2l1.1 1.1L12 11.2l2.1 2.1 1.1-1.1L13.1 10l2.1-2.2z"/>',
      deadline: '<path fill="currentColor" d="M12 3.5a8.5 8.5 0 1 1 0 17 8.5 8.5 0 0 1 0-17zm.9 4.2h-1.8V13l4.2 2.5 0.9-1.5-3.3-2z"/>',
    };
    return `<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">${paths[kind] || paths.document}</svg>`;
  }

  function setBadge(count) {
    unreadCount = Number(count) || 0;
    const badge = el("notif-badge");
    const label = el("notif-unread-label");
    if (badge) {
      if (unreadCount <= 0) {
        badge.classList.add("hidden");
        badge.textContent = "0";
      } else {
        badge.classList.remove("hidden");
        badge.textContent = unreadCount > 99 ? "99+" : String(unreadCount);
      }
    }
    if (label) {
      if (unreadCount <= 0) {
        label.classList.add("hidden");
        label.textContent = "";
      } else {
        label.classList.remove("hidden");
        label.textContent = unreadCount === 1 ? "1 unread" : `${unreadCount} unread`;
      }
    }
  }

  function renderList(items) {
    const list = el("notif-list");
    if (!list) return;
    if (!items || !items.length) {
      list.innerHTML = `<div class="notif-empty">
        <div class="notif-empty-title">You're all caught up</div>
        <p>New notices, calendar changes and deadlines will show up here.</p>
      </div>`;
      return;
    }
    list.innerHTML = items
      .map((n) => {
        const unread = !n.is_read;
        const meta = typeMeta(n.notification_type);
        return `<button type="button" class="notif-item${unread ? " unread" : ""}" data-notif-id="${n.id}">
          <span class="notif-icon notif-icon-${meta.kind}">${iconSvg(meta.kind)}</span>
          <span class="notif-copy">
            <p class="notif-item-title">${escapeHtml(n.title)}</p>
            <p class="notif-item-msg">${escapeHtml(n.message)}</p>
            <span class="notif-item-meta">
              <span class="notif-open-hint">${escapeHtml(meta.hint)}</span>
              <time datetime="${escapeHtml(n.created_at || "")}">${escapeHtml(formatRelative(n.created_at))}</time>
            </span>
          </span>
          <span class="notif-dot" aria-hidden="true"></span>
        </button>`;
      })
      .join("");

    list.querySelectorAll(".notif-item").forEach((btn) => {
      btn.addEventListener("click", () => onItemClick(Number(btn.dataset.notifId)));
    });
  }

  function placePanel() {
    const panel = el("notif-panel");
    const btn = el("notif-bell-btn");
    if (!panel || !btn || panel.classList.contains("hidden")) return;
    const rect = btn.getBoundingClientRect();
    const margin = 8;
    const width = Math.min(380, window.innerWidth - margin * 2);
    let left = rect.right - width;
    left = Math.max(margin, Math.min(left, window.innerWidth - width - margin));
    const top = Math.min(rect.bottom + 8, window.innerHeight - 120);
    const maxHeight = Math.max(180, Math.min(480, window.innerHeight - top - margin));
    panel.style.top = `${Math.round(top)}px`;
    panel.style.left = `${Math.round(left)}px`;
    panel.style.width = `${Math.round(width)}px`;
    panel.style.maxHeight = `${Math.round(maxHeight)}px`;
    const list = el("notif-list");
    const header = panel.querySelector(".notif-panel-header");
    const headerH = header ? header.offsetHeight : 56;
    if (list) list.style.maxHeight = `${Math.max(140, Math.round(maxHeight - headerH))}px`;
  }

  async function refreshUnreadOnly() {
    if (!state.token || state.role !== "student") {
      setBadge(0);
      return;
    }
    try {
      const data = await api("/notifications/unread-count");
      setBadge(data.unread_count);
    } catch (err) {
      if (err.status === 401 || err.status === 403) stopNotificationPolling();
    }
  }

  async function refreshPanel() {
    if (!state.token || state.role !== "student") {
      itemsCache = [];
      renderList([]);
      setBadge(0);
      return;
    }
    try {
      const data = await api("/notifications?limit=40");
      itemsCache = data.items || [];
      setBadge(data.unread_count);
      renderList(itemsCache);
    } catch (err) {
      if (err.status === 401 || err.status === 403) stopNotificationPolling();
      else {
        const list = el("notif-list");
        if (list) {
          list.innerHTML = `<div class="notif-empty"><div class="notif-empty-title">Could not load notifications</div><p>${escapeHtml(err.message || "Try again in a moment.")}</p></div>`;
        }
      }
    }
  }

  function navigateToView(view) {
    const btn = document.querySelector(`.nav-btn[data-view="${view}"]`);
    if (btn) btn.click();
  }

  async function onItemClick(id) {
    const item = itemsCache.find((n) => Number(n.id) === Number(id));
    if (!item) return;
    try {
      if (!item.is_read) {
        await api(`/notifications/${id}/read`, { method: "POST" });
        item.is_read = true;
        item.read_at = new Date().toISOString();
        setBadge(Math.max(0, unreadCount - 1));
        renderList(itemsCache);
      }
    } catch (_) {
      /* still navigate */
    }
    closePanel();

    if (item.related_document_id && typeof openDocumentFile === "function") {
      navigateToView("documents");
      try {
        await openDocumentFile(Number(item.related_document_id), "inline");
      } catch (err) {
        if (typeof showToast === "function") {
          showToast(err.message || "Could not open document.", "err");
        }
      }
      return;
    }
    if (
      item.related_event_id ||
      String(item.notification_type || "").startsWith("calendar") ||
      item.notification_type === "deadline_reminder"
    ) {
      navigateToView("calendar");
      return;
    }
    navigateToView("documents");
  }

  function openPanel() {
    const panel = el("notif-panel");
    const btn = el("notif-bell-btn");
    if (!panel || !btn) return;
    panelOpen = true;
    panel.classList.remove("hidden");
    btn.setAttribute("aria-expanded", "true");
    placePanel();
    refreshPanel();
  }

  function closePanel() {
    const panel = el("notif-panel");
    const btn = el("notif-bell-btn");
    panelOpen = false;
    if (panel) panel.classList.add("hidden");
    if (btn) btn.setAttribute("aria-expanded", "false");
  }

  function togglePanel(e) {
    e.stopPropagation();
    if (panelOpen) closePanel();
    else openPanel();
  }

  function startNotificationPolling() {
    stopNotificationPolling();
    if (!state.token || state.role !== "student") {
      setBadge(0);
      return;
    }
    refreshUnreadOnly();
    pollTimer = setInterval(refreshUnreadOnly, POLL_MS);
  }

  function stopNotificationPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    closePanel();
    setBadge(0);
  }

  el("notif-bell-btn")?.addEventListener("click", togglePanel);
  el("notif-panel")?.addEventListener("click", (e) => e.stopPropagation());
  el("notif-close")?.addEventListener("click", (e) => {
    e.stopPropagation();
    closePanel();
  });
  el("notif-mark-all")?.addEventListener("click", async (e) => {
    e.stopPropagation();
    const previous = itemsCache.map((item) => ({ ...item }));
    const previousUnread = unreadCount;
    itemsCache.forEach((item) => {
      item.is_read = true;
    });
    setBadge(0);
    renderList(itemsCache);
    try {
      await api("/notifications/read-all", { method: "POST" });
    } catch (err) {
      itemsCache = previous;
      setBadge(previousUnread);
      renderList(itemsCache);
      if (typeof showToast === "function") {
        showToast(err.message || "Could not mark notifications as read.", "err");
      }
    }
  });

  document.addEventListener("click", () => {
    if (panelOpen) closePanel();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && panelOpen) closePanel();
  });
  window.addEventListener("resize", () => {
    if (panelOpen) placePanel();
  });
  window.addEventListener(
    "scroll",
    () => {
      if (panelOpen) placePanel();
    },
    true
  );

  window.startNotificationPolling = startNotificationPolling;
  window.stopNotificationPolling = stopNotificationPolling;
  window.refreshNotificationsPanel = refreshPanel;
})();
