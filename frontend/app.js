// Same-origin by default (Nginx reverse-proxies API routes to the backend).
// Override for local non-Docker static serving: window.CAMPUS_COPILOT_API_BASE = "http://localhost:8000"
const API_BASE =
  typeof window !== "undefined" && window.CAMPUS_COPILOT_API_BASE != null
    ? String(window.CAMPUS_COPILOT_API_BASE).replace(/\/$/, "")
    : "";

let state = {
  token: localStorage.getItem("cc_token") || null,
  role: localStorage.getItem("cc_role") || null,
  fullName: localStorage.getItem("cc_full_name") || null,
  profile: null,
  history: [],
  conversationId: null,
  conversations: [],
  chatBusy: false,
  deleteBusy: false,
  pendingDeleteId: null,
  ingestBusy: false,
  docDeleteBusy: false,
  pendingDocDeleteId: null,
  docsPage: 1,
  docsPageSize: 10,
  docsCategory: "",
  docsTotal: 0,
  docsTotalPages: 1,
};

let _toastTimer = null;

// ---------- helpers ----------
async function api(path, { method = "GET", body = null, isForm = false } = {}) {
  const headers = {};
  if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
  if (!isForm && body) headers["Content-Type"] = "application/json";

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: isForm ? body : body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const payload = await res.json();
      detail = payload.detail || detail;
      if (Array.isArray(detail)) {
        detail = detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
      } else if (typeof detail === "object") {
        detail = detail.message || JSON.stringify(detail);
      }
    } catch (_) {}
    // Static file servers reject API POSTs with 405 / "Unsupported method".
    const methodBlocked =
      res.status === 405 ||
      /method not allowed|unsupported method/i.test(String(detail || res.statusText || ""));
    if (methodBlocked && typeof path === "string" && path.startsWith("/auth/")) {
      detail =
        "API is unreachable from this page origin. Open Campus Copilot at http://localhost:8080/ (Docker), or set window.CAMPUS_COPILOT_API_BASE to a running backend URL.";
    }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  if (res.status === 204) return null;
  return res.json();
}

function el(id) { return document.getElementById(id); }

function on(id, event, handler) {
  const node = el(id);
  if (!node) {
    console.error(`[Campus Copilot] Missing element #${id}; skipped ${event} handler`);
    return;
  }
  node.addEventListener(event, handler);
}

function escapeHtml(str) {
  const d = document.createElement("div");
  d.textContent = str == null ? "" : String(str);
  return d.innerHTML;
}

function showChatView() {
  document.querySelectorAll(".nav-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.view === "chat");
  });
  document.querySelectorAll("#app-main > .view").forEach((v) => v.classList.add("hidden"));
  const chat = el("view-chat");
  if (chat) chat.classList.remove("hidden");
}

function showScreen(loggedIn) {
  el("auth-screen").classList.toggle("hidden", loggedIn);
  el("app-screen").classList.toggle("hidden", !loggedIn);
  if (!loggedIn) {
    el("profile-modal").classList.add("hidden");
    el("change-password-modal")?.classList.add("hidden");
    el("user-menu-dropdown").classList.add("hidden");
  }
}

function clearFieldErrors(prefix) {
  document.querySelectorAll(`[id^="${prefix}"][id$="-error"]`).forEach((node) => {
    node.textContent = "";
  });
}

function setFormStatus(node, message, kind) {
  if (!node) return;
  if (!message) {
    node.classList.add("hidden");
    node.textContent = "";
    return;
  }
  node.textContent = message;
  node.classList.remove("hidden", "ok", "err");
  node.classList.add(kind === "ok" ? "ok" : "err");
}

function initialsFromProfile(profile) {
  const first = (profile?.first_name || "").trim();
  const last = (profile?.last_name || "").trim();
  if (first || last) return `${first.charAt(0)}${last.charAt(0)}`.toUpperCase() || first.charAt(0).toUpperCase();
  const name = (profile?.full_name || "?").trim();
  return name.slice(0, 2).toUpperCase();
}

function applyRoleVisibility() {
  const isAdmin = state.role === "admin";
  const isStudent = state.role === "student";
  document.querySelectorAll(".admin-only").forEach((n) => n.classList.toggle("hidden", !isAdmin));
  document.querySelectorAll(".student-only").forEach((n) => n.classList.toggle("hidden", !isStudent));
}

// ---------- auth panels ----------
const AUTH_PANELS = {
  login: "login-panel",
  admin: "admin-panel",
  setup: "setup-panel",
};

function showAuthPanel(name) {
  Object.values(AUTH_PANELS).forEach((id) => el(id).classList.add("hidden"));
  el(AUTH_PANELS[name] || AUTH_PANELS.login).classList.remove("hidden");
  el("auth-error").classList.add("hidden");
}

document.querySelectorAll("[data-show-panel]").forEach((btn) => {
  btn.addEventListener("click", () => showAuthPanel(btn.dataset.showPanel));
});

document.querySelectorAll(".password-toggle").forEach((btn) => {
  btn.addEventListener("click", () => {
    const input = el(btn.dataset.target);
    if (!input) return;
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
  });
});

function setSession(data) {
  state.token = data.access_token;
  state.role = data.role;
  state.fullName = data.full_name;
  localStorage.setItem("cc_token", state.token);
  localStorage.setItem("cc_role", state.role);
  localStorage.setItem("cc_full_name", state.fullName);
}

function clearSession() {
  localStorage.removeItem("cc_token");
  localStorage.removeItem("cc_role");
  localStorage.removeItem("cc_full_name");
  state = {
    token: null, role: null, fullName: null, profile: null,
    history: [], conversationId: null, conversations: [], chatBusy: false,
    deleteBusy: false, pendingDeleteId: null, ingestBusy: false,
    docDeleteBusy: false, pendingDocDeleteId: null,
    docsPage: 1, docsPageSize: 10, docsCategory: "", docsTotal: 0, docsTotalPages: 1,
  };
}

function showAuthError(err) {
  const detail = err && err.message ? err.message : String(err);
  el("auth-error").textContent = detail;
  el("auth-error").classList.remove("hidden");
}

el("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  el("auth-error").classList.add("hidden");
  const enrollment = el("login-enrollment").value.trim();
  if (!/^\d{11}$/.test(enrollment)) {
    showAuthError(new Error("Enrollment number must be exactly 11 digits"));
    return;
  }
  try {
    const data = await api("/auth/student/login", {
      method: "POST",
      body: { enrollment_number: enrollment, password: el("login-password").value },
    });
    setSession(data);
    await enterApp();
  } catch (err) {
    showAuthError(err);
  }
});

el("admin-login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  el("auth-error").classList.add("hidden");
  try {
    const data = await api("/auth/admin/login", {
      method: "POST",
      body: { username: el("admin-username").value, password: el("admin-password").value },
    });
    setSession(data);
    await enterApp();
  } catch (err) {
    showAuthError(err);
  }
});

async function fetchProfile() {
  return api("/auth/me");
}

function updateChromeFromProfile(profile) {
  state.profile = profile;
  state.role = profile.role;
  state.fullName = profile.full_name;
  localStorage.setItem("cc_role", profile.role);
  localStorage.setItem("cc_full_name", profile.full_name);

  const first = (profile.first_name || "").trim() || profile.full_name.split(" ")[0] || "there";
  el("user-avatar").textContent = initialsFromProfile(profile);
  el("user-menu-label").textContent = profile.role === "admin"
    ? `${first} (admin)`
    : first;

  if (profile.role === "student") {
    el("student-greeting").textContent = `Welcome, ${first}!`;
    el("student-greeting-bar").classList.remove("hidden");
  } else {
    el("student-greeting-bar").classList.add("hidden");
  }

  applyRoleVisibility();
  renderOnboarding(profile);
  renderProfileModal(profile);
}

function renderOnboarding(profile) {
  const panel = el("onboarding-panel");
  const main = el("app-main");
  if (profile.role !== "student") {
    panel.classList.add("hidden");
    main.classList.remove("hidden");
    return;
  }

  const incomplete = profile.profile_complete === false;
  panel.classList.toggle("hidden", !incomplete);
  main.classList.toggle("hidden", incomplete);
  if (!incomplete) return;

  const editable = new Set(profile.editable_fields || []);
  const setLocked = (inputId, locked, value) => {
    const input = el(inputId);
    input.value = value == null ? "" : String(value);
    input.readOnly = locked;
    input.classList.toggle("readonly", locked);
    if (!locked && !value) input.required = true;
  };

  setLocked("ob-first-name", !editable.has("first_name"), profile.first_name);
  setLocked("ob-last-name", !editable.has("last_name"), profile.last_name);
  setLocked("ob-enrollment", true, profile.enrollment_number);
  setLocked("ob-course", true, profile.course);
  el("ob-course-hint").textContent = profile.course
    ? "Set by your administrator"
    : "Not set — contact your campus administrator";

  setLocked("ob-year", !editable.has("academic_year"), profile.academic_year);
  setLocked("ob-semester", !editable.has("current_semester"), profile.current_semester);
  setLocked("ob-email", !editable.has("email"), profile.email);

  clearFieldErrors("ob-");
  setFormStatus(el("onboarding-status"), "", null);
}

function renderProfileModal(profile) {
  el("pf-first-name").textContent = profile.first_name || "—";
  el("pf-last-name").textContent = profile.last_name || "—";
  el("pf-enrollment").textContent = profile.enrollment_number || "—";
  el("pf-course").textContent = profile.course || "—";
  el("pf-year").textContent = profile.academic_year || "—";
  el("pf-semester").textContent = profile.current_semester == null ? "—" : String(profile.current_semester);
  el("pf-email").textContent = profile.email || "—";
  const badge = el("pf-email-status");
  if (!profile.email) {
    badge.textContent = "Not set";
    badge.className = "email-badge muted";
  } else if (profile.email_verified) {
    badge.textContent = "Verified";
    badge.className = "email-badge ok";
  } else {
    badge.textContent = "Unverified";
    badge.className = "email-badge warn";
  }
  el("pf-email-input").value = profile.email || "";
  clearFieldErrors("pf-");
  setFormStatus(el("profile-edit-status"), "", null);
}

async function enterApp() {
  try {
    const profile = await fetchProfile();
    updateChromeFromProfile(profile);
    showScreen(true);
    if (profile.role === "admin" || profile.profile_complete) {
      showChatView();
      try {
        await startNewChat(false);
      } catch (chatErr) {
        console.error("Failed to initialize chat UI", chatErr);
        showEmptyChatState(true);
      }
      try {
        await refreshConversationList();
      } catch (listErr) {
        console.error("Failed to load conversations", listErr);
      }
      loadDocuments();
    }
    if (typeof window.startNotificationPolling === "function") {
      window.startNotificationPolling();
    }
  } catch (err) {
    console.error("enterApp failed", err);
    clearSession();
    showAuthPanel("login");
    showScreen(false);
    if (err.status !== 401) showAuthError(err);
  }
}

function logout() {
  if (typeof window.stopNotificationPolling === "function") {
    window.stopNotificationPolling();
  }
  clearSession();
  el("user-menu-dropdown").classList.add("hidden");
  el("profile-modal").classList.add("hidden");
  el("onboarding-panel").classList.add("hidden");
  el("app-main").classList.remove("hidden");
  showAuthPanel("login");
  showScreen(false);
}

el("logout-btn").addEventListener("click", logout);

// ---------- user menu ----------
el("user-menu-btn").addEventListener("click", (e) => {
  e.stopPropagation();
  el("notif-panel")?.classList.add("hidden");
  el("notif-bell-btn")?.setAttribute("aria-expanded", "false");
  const menu = el("user-menu-dropdown");
  const open = menu.classList.toggle("hidden") === false;
  el("user-menu-btn").setAttribute("aria-expanded", open ? "true" : "false");
});

document.addEventListener("click", () => {
  el("user-menu-dropdown").classList.add("hidden");
  el("user-menu-btn").setAttribute("aria-expanded", "false");
});

el("profile-menu-btn").addEventListener("click", () => {
  el("user-menu-dropdown").classList.add("hidden");
  if (state.role === "student") {
    el("profile-modal").classList.remove("hidden");
  } else {
    alert("Admin profile editing is not available in this view.");
  }
});

function resetChangePasswordForm() {
  const form = el("change-password-form");
  if (form) form.reset();
  ["cp-current", "cp-new", "cp-confirm"].forEach((id) => {
    const input = el(id);
    if (input) input.type = "password";
  });
  document.querySelectorAll("#change-password-form .password-toggle").forEach((btn) => {
    btn.setAttribute("aria-label", "Show password");
  });
  ["cp-current-error", "cp-new-error", "cp-confirm-error"].forEach((id) => {
    const node = el(id);
    if (node) node.textContent = "";
  });
  const status = el("change-password-status");
  if (status) {
    status.textContent = "";
    status.classList.add("hidden");
    status.classList.remove("ok", "err");
  }
}

function setChangePasswordStatus(message, kind) {
  const status = el("change-password-status");
  if (!status) return;
  status.textContent = message;
  status.classList.remove("hidden", "ok", "err");
  status.classList.add(kind === "ok" ? "ok" : "err");
}

function clientPasswordError(password) {
  if (!password || password.length < 8) {
    return "Password must be at least 8 characters.";
  }
  if (!/[A-Za-z]/.test(password) || !/\d/.test(password)) {
    return "Password must include at least one letter and one number.";
  }
  return "";
}

function openChangePasswordModal() {
  el("user-menu-dropdown").classList.add("hidden");
  resetChangePasswordForm();
  el("change-password-modal").classList.remove("hidden");
  el("cp-current")?.focus();
}

function closeChangePasswordModal() {
  el("change-password-modal").classList.add("hidden");
  resetChangePasswordForm();
}

el("change-password-menu-btn").addEventListener("click", openChangePasswordModal);

el("change-password-close").addEventListener("click", closeChangePasswordModal);

el("change-password-modal").addEventListener("click", (e) => {
  if (e.target === el("change-password-modal")) closeChangePasswordModal();
});

el("change-password-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const current = el("cp-current").value;
  const next = el("cp-new").value;
  const confirm = el("cp-confirm").value;
  const submit = el("change-password-submit");
  ["cp-current-error", "cp-new-error", "cp-confirm-error"].forEach((id) => {
    el(id).textContent = "";
  });
  el("change-password-status").classList.add("hidden");

  let blocked = false;
  if (!current) {
    el("cp-current-error").textContent = "Enter your current password.";
    blocked = true;
  }
  const strength = clientPasswordError(next);
  if (strength) {
    el("cp-new-error").textContent = strength;
    blocked = true;
  }
  if (next !== confirm) {
    el("cp-confirm-error").textContent = "New passwords do not match.";
    blocked = true;
  }
  if (current && next && current === next && !strength) {
    el("cp-new-error").textContent = "New password must differ from current password.";
    blocked = true;
  }
  if (blocked) {
    setChangePasswordStatus("Please correct the highlighted fields.", "err");
    return;
  }

  submit.disabled = true;
  submit.textContent = "Updating…";
  try {
    const data = await api("/auth/change-password", {
      method: "POST",
      body: {
        current_password: current,
        new_password: next,
        confirm_password: confirm,
      },
    });
    el("cp-current").value = "";
    el("cp-new").value = "";
    el("cp-confirm").value = "";
    setChangePasswordStatus(
      (data && data.message) || "Password changed successfully.",
      "ok",
    );
  } catch (err) {
    if (err.status === 401) {
      setChangePasswordStatus("Session expired; please log in again.", "err");
      setTimeout(logout, 1200);
    } else {
      const message = err && err.message ? err.message : "Unable to change password.";
      if (/incorrect current password/i.test(message)) {
        el("cp-current-error").textContent = "Incorrect current password.";
      }
      setChangePasswordStatus(message, "err");
    }
  } finally {
    submit.disabled = false;
    submit.textContent = "Update password";
  }
});

el("profile-modal-close").addEventListener("click", () => {
  el("profile-modal").classList.add("hidden");
});

el("profile-modal").addEventListener("click", (e) => {
  if (e.target === el("profile-modal")) el("profile-modal").classList.add("hidden");
});

function validateEmail(value) {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value);
}

el("onboarding-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  clearFieldErrors("ob-");
  setFormStatus(el("onboarding-status"), "", null);

  const profile = state.profile || {};
  const editable = new Set(profile.editable_fields || []);
  const body = {};
  let valid = true;

  const take = (field, inputId, errorId, check) => {
    if (!editable.has(field)) return;
    const raw = el(inputId).value.trim();
    const err = check(raw);
    if (err) {
      el(errorId).textContent = err;
      valid = false;
      return;
    }
    if (field === "current_semester") body[field] = Number(raw);
    else body[field] = raw;
  };

  take("first_name", "ob-first-name", "ob-first-name-error", (v) => (!v ? "First name is required" : ""));
  take("last_name", "ob-last-name", "ob-last-name-error", (v) => (!v ? "Last name is required" : ""));
  take("academic_year", "ob-year", "ob-year-error", (v) => (!v ? "Academic year is required" : ""));
  take("current_semester", "ob-semester", "ob-semester-error", (v) => {
    const n = Number(v);
    if (!v || Number.isNaN(n) || n < 1 || n > 12) return "Enter a semester between 1 and 12";
    return "";
  });
  take("email", "ob-email", "ob-email-error", (v) => {
    if (!v) return "Email is required";
    if (!validateEmail(v)) return "Enter a valid email address";
    return "";
  });

  // Admin-provisioned gaps that students cannot fill.
  if (!(profile.enrollment_number || "").trim() || !(profile.course || "").trim()) {
    setFormStatus(
      el("onboarding-status"),
      "Enrollment or course is missing from your account. Contact an administrator.",
      "err",
    );
    return;
  }

  if (!valid) return;

  const btn = el("onboarding-save-btn");
  btn.disabled = true;
  btn.textContent = "Saving…";
  try {
    const updated = await api("/auth/me", { method: "PATCH", body });
    updateChromeFromProfile(updated);
    setFormStatus(el("onboarding-status"), "Profile saved.", "ok");
    if (updated.profile_complete) {
      loadDocuments();
      showChatView();
      await startNewChat(true);
    }
  } catch (err) {
    setFormStatus(el("onboarding-status"), err.message, "err");
  } finally {
    btn.disabled = false;
    btn.textContent = "Save Profile";
  }
});

el("profile-edit-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  clearFieldErrors("pf-");
  const email = el("pf-email-input").value.trim();
  if (!email || !validateEmail(email)) {
    el("pf-email-input-error").textContent = "Enter a valid email address";
    return;
  }
  const btn = el("profile-save-btn");
  btn.disabled = true;
  btn.textContent = "Saving…";
  try {
    const updated = await api("/auth/me", { method: "PATCH", body: { email } });
    updateChromeFromProfile(updated);
    setFormStatus(el("profile-edit-status"), "Email updated. Verification required before password recovery.", "ok");
  } catch (err) {
    setFormStatus(el("profile-edit-status"), err.message, "err");
  } finally {
    btn.disabled = false;
    btn.textContent = "Save Changes";
  }
});

// ---------- nav ----------
document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    document.querySelectorAll("#app-main > .view").forEach((v) => v.classList.add("hidden"));
    el(`view-${btn.dataset.view}`).classList.remove("hidden");
    if (btn.dataset.view === "documents") loadDocuments();
    if (btn.dataset.view === "calendar" && typeof window.loadStudentCalendar === "function") {
      window.loadStudentCalendar();
    }
    if (btn.dataset.view === "admin") {
      if (typeof window.openAdminPanel === "function") {
        window.openAdminPanel("overview");
      } else {
        loadAdminInsights();
      }
    }
  });
});

// ---------- chat ----------
function timeOfDayGreeting(firstName) {
  const hour = new Date().getHours();
  const part = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  return `${part}, ${firstName || "there"}!`;
}

function formatRelativeTime(iso) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diff = Date.now() - then;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

function showEmptyChatState(show) {
  const empty = el("chat-empty-state");
  const log = el("chat-log");
  if (empty) empty.classList.toggle("hidden", !show);
  if (log) log.classList.toggle("hidden", show);
  if (show) {
    const first = (state.profile?.first_name || "").trim()
      || (state.fullName || "").split(" ")[0]
      || "there";
    const greeting = el("chat-time-greeting");
    if (greeting) greeting.textContent = timeOfDayGreeting(first);
    // No announcements feature/table yet — keep Campus Updates hidden (no fictional notices).
    el("campus-updates")?.classList.add("hidden");
  }
}

async function startNewChat(refreshList = true) {
  showChatView();
  state.conversationId = null;
  state.history = [];
  state.chatBusy = false;
  const log = el("chat-log");
  if (log) log.innerHTML = "";
  showEmptyChatState(true);
  document.querySelectorAll(".conversation-item.active").forEach((n) => n.classList.remove("active"));
  const sendBtn = el("chat-send-btn");
  if (sendBtn) sendBtn.disabled = false;
  if (refreshList) await refreshConversationList();
}

function showToast(message, kind = "ok") {
  const toast = el("app-toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.remove("hidden", "err");
  if (kind === "err") toast.classList.add("err");
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => {
    toast.classList.add("hidden");
  }, 3200);
}

function closeAllConvMenus() {
  document.querySelectorAll(".conv-menu-dropdown").forEach((node) => node.classList.add("hidden"));
  document.querySelectorAll(".conv-menu-btn").forEach((btn) => btn.setAttribute("aria-expanded", "false"));
}

function trashIconSvg() {
  return `<svg class="conv-menu-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <polyline points="3 6 5 6 21 6"></polyline>
    <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path>
    <path d="M10 11v6"></path><path d="M14 11v6"></path>
    <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"></path>
  </svg>`;
}

function openDeleteChatModal(conversationId) {
  state.pendingDeleteId = conversationId;
  closeAllConvMenus();
  el("delete-chat-modal")?.classList.remove("hidden");
  el("delete-chat-confirm")?.focus();
}

function closeDeleteChatModal() {
  if (state.deleteBusy) return;
  state.pendingDeleteId = null;
  el("delete-chat-modal")?.classList.add("hidden");
}

async function confirmDeleteChat() {
  const id = state.pendingDeleteId;
  if (!id || state.deleteBusy) return;
  state.deleteBusy = true;
  const confirmBtn = el("delete-chat-confirm");
  const cancelBtn = el("delete-chat-cancel");
  if (confirmBtn) {
    confirmBtn.disabled = true;
    confirmBtn.textContent = "Deleting…";
  }
  if (cancelBtn) cancelBtn.disabled = true;
  try {
    await api(`/conversations/${id}`, { method: "DELETE" });
    const wasOpen = state.conversationId === id;
    state.conversations = (state.conversations || []).filter((c) => c.id !== id);
    state.pendingDeleteId = null;
    el("delete-chat-modal")?.classList.add("hidden");
    showToast("Conversation deleted successfully.");
    if (wasOpen) {
      await startNewChat(false);
    }
    await refreshConversationList(el("conversation-search")?.value || "");
  } catch (err) {
    showToast(err.message || "Could not delete conversation.", "err");
  } finally {
    state.deleteBusy = false;
    if (confirmBtn) {
      confirmBtn.disabled = false;
      confirmBtn.textContent = "Delete Chat";
    }
    if (cancelBtn) cancelBtn.disabled = false;
  }
}

async function refreshConversationList(search = "") {
  const list = el("conversation-list");
  if (!list) return;
  try {
    const q = search ? `?q=${encodeURIComponent(search)}` : "";
    state.conversations = await api(`/conversations${q}`);
    list.innerHTML = "";
    if (!state.conversations.length) {
      list.innerHTML = `<p class="sidebar-empty">No conversations yet.</p>`;
      return;
    }
    state.conversations.forEach((c) => {
      const row = document.createElement("div");
      row.className = "conversation-item" + (c.id === state.conversationId ? " active" : "");
      row.setAttribute("role", "listitem");
      row.dataset.id = String(c.id);

      const openBtn = document.createElement("button");
      openBtn.type = "button";
      openBtn.className = "conv-open-btn";
      openBtn.innerHTML =
        `<span class="conv-title">${escapeHtml(c.title)}</span>` +
        `<span class="conv-time">${escapeHtml(formatRelativeTime(c.updated_at))}</span>`;
      openBtn.addEventListener("click", () => {
        closeAllConvMenus();
        loadConversation(c.id);
      });

      const menuWrap = document.createElement("div");
      menuWrap.className = "conv-menu-wrap";

      const menuBtn = document.createElement("button");
      menuBtn.type = "button";
      menuBtn.className = "conv-menu-btn";
      menuBtn.setAttribute("aria-label", `Options for ${c.title}`);
      menuBtn.setAttribute("aria-haspopup", "true");
      menuBtn.setAttribute("aria-expanded", "false");
      menuBtn.textContent = "⋮";

      const dropdown = document.createElement("div");
      dropdown.className = "conv-menu-dropdown hidden";
      dropdown.setAttribute("role", "menu");

      const deleteItem = document.createElement("button");
      deleteItem.type = "button";
      deleteItem.className = "conv-menu-item";
      deleteItem.setAttribute("role", "menuitem");
      deleteItem.innerHTML = `${trashIconSvg()}<span>Delete Chat</span>`;
      deleteItem.addEventListener("click", (e) => {
        e.stopPropagation();
        openDeleteChatModal(c.id);
      });

      menuBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const open = !dropdown.classList.contains("hidden");
        closeAllConvMenus();
        if (!open) {
          dropdown.classList.remove("hidden");
          menuBtn.setAttribute("aria-expanded", "true");
        }
      });

      dropdown.appendChild(deleteItem);
      menuWrap.appendChild(menuBtn);
      menuWrap.appendChild(dropdown);
      row.appendChild(openBtn);
      row.appendChild(menuWrap);
      list.appendChild(row);
    });
  } catch (err) {
    console.error(err);
    list.innerHTML = `<p class="sidebar-empty">Could not load conversations.</p>`;
  }
}

async function ensureConversation(firstQuestion) {
  if (state.conversationId) return state.conversationId;
  const created = await api("/conversations", {
    method: "POST",
    body: { title: firstQuestion.slice(0, 80) },
  });
  state.conversationId = created.id;
  await refreshConversationList(el("conversation-search")?.value || "");
  return state.conversationId;
}

async function persistMessage(payload) {
  if (!state.conversationId) return;
  await api(`/conversations/${state.conversationId}/messages`, {
    method: "POST",
    body: payload,
  });
}

function formatAssistantHtml(text) {
  // Escape then lightly format markdown-like lists/paragraphs without inventing content.
  const escaped = escapeHtml(text);
  const lines = escaped.split("\n");
  let html = "";
  let inUl = false;
  let inOl = false;
  const closeLists = () => {
    if (inUl) { html += "</ul>"; inUl = false; }
    if (inOl) { html += "</ol>"; inOl = false; }
  };
  lines.forEach((line) => {
    const bullet = line.match(/^(\s*)[-*]\s+(.+)$/);
    const numbered = line.match(/^(\s*)\d+\.\s+(.+)$/);
    if (bullet) {
      if (inOl) { html += "</ol>"; inOl = false; }
      if (!inUl) { html += "<ul>"; inUl = true; }
      html += `<li>${bullet[2]}</li>`;
    } else if (numbered) {
      if (inUl) { html += "</ul>"; inUl = false; }
      if (!inOl) { html += "<ol>"; inOl = true; }
      html += `<li>${numbered[2]}</li>`;
    } else if (!line.trim()) {
      closeLists();
    } else {
      closeLists();
      html += `<p>${line}</p>`;
    }
  });
  closeLists();
  return html || `<p>${escaped}</p>`;
}

function appendUserMessage(content) {
  showEmptyChatState(false);
  const wrap = document.createElement("div");
  wrap.className = "msg user";
  wrap.innerHTML = `<div class="bubble">${escapeHtml(content)}</div>`;
  el("chat-log").appendChild(wrap);
  el("chat-log").scrollTop = el("chat-log").scrollHeight;
  return wrap;
}

function appendTypingIndicator() {
  showEmptyChatState(false);
  const wrap = document.createElement("div");
  wrap.className = "msg assistant typing-msg";
  wrap.innerHTML = `
    <div class="msg-avatar" aria-hidden="true"><img src="assets/campus-copilot-logo.jpg" alt="" /></div>
    <div class="bubble typing-bubble"><span class="typing-dots" aria-label="Assistant is typing"><i></i><i></i><i></i></span></div>`;
  el("chat-log").appendChild(wrap);
  el("chat-log").scrollTop = el("chat-log").scrollHeight;
  return wrap;
}

function renderCitations(container, citations) {
  if (!citations || citations.length === 0) return;
  const details = document.createElement("details");
  details.className = "citations sources-panel";
  const summary = document.createElement("summary");
  summary.textContent = `Sources (${citations.length})`;
  details.appendChild(summary);
  citations.forEach((c) => {
    const div = document.createElement("div");
    div.className = "citation-item";
    const bits = [];
    if (c.title) bits.push(`<span class="cite-title">${escapeHtml(c.title)}</span>`);
    if (c.section_label) bits.push(`<span class="cite-meta">${escapeHtml(c.section_label)}</span>`);
    if (c.page_number != null) bits.push(`<span class="cite-meta">Page ${escapeHtml(String(c.page_number))}</span>`);
    if (typeof c.score === "number") bits.push(`<span class="cite-score">sim ${c.score.toFixed(2)}</span>`);
    div.innerHTML = bits.join(" ") +
      (c.text_preview ? `<p class="cite-preview">${escapeHtml(c.text_preview)}</p>` : "");
    details.appendChild(div);
  });
  container.appendChild(details);
}

function renderMessageActions(container, answerText, queryLogId) {
  const row = document.createElement("div");
  row.className = "msg-actions";

  const copyBtn = document.createElement("button");
  copyBtn.type = "button";
  copyBtn.className = "msg-action-btn";
  copyBtn.textContent = "Copy";
  copyBtn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(answerText);
      copyBtn.textContent = "Copied";
      setTimeout(() => { copyBtn.textContent = "Copy"; }, 1500);
    } catch (_) {
      copyBtn.textContent = "Failed";
      setTimeout(() => { copyBtn.textContent = "Copy"; }, 1500);
    }
  });
  row.appendChild(copyBtn);

  if (queryLogId != null) {
    const up = document.createElement("button");
    up.type = "button";
    up.className = "msg-action-btn";
    up.textContent = "👍";
    up.title = "Helpful";
    const down = document.createElement("button");
    down.type = "button";
    down.className = "msg-action-btn";
    down.textContent = "👎";
    down.title = "Not helpful";
    const send = async (rating, btn, other) => {
      try {
        await api("/feedback", { method: "POST", body: { query_log_id: queryLogId, rating } });
        btn.classList.add(rating === 1 ? "selected-up" : "selected-down");
        btn.disabled = true;
        other.disabled = true;
      } catch (err) { console.error(err); }
    };
    up.addEventListener("click", () => send(1, up, down));
    down.addEventListener("click", () => send(-1, down, up));
    row.appendChild(up);
    row.appendChild(down);
  }

  container.appendChild(row);
}

function appendAssistantMessage({ content, citations, queryLogId, confident }) {
  showEmptyChatState(false);
  const wrap = document.createElement("div");
  wrap.className = "msg assistant" + (confident === false ? " low-confidence" : "");
  const avatar = document.createElement("div");
  avatar.className = "msg-avatar";
  avatar.innerHTML = `<img src="assets/campus-copilot-logo.jpg" alt="" />`;
  const stack = document.createElement("div");
  stack.className = "msg-stack";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.innerHTML = formatAssistantHtml(content);
  stack.appendChild(bubble);
  renderCitations(stack, citations || []);
  renderMessageActions(stack, content, queryLogId);
  wrap.appendChild(avatar);
  wrap.appendChild(stack);
  el("chat-log").appendChild(wrap);
  el("chat-log").scrollTop = el("chat-log").scrollHeight;
  return wrap;
}

async function loadConversation(id) {
  try {
    showChatView();
    const detail = await api(`/conversations/${id}`);
    state.conversationId = detail.id;
    state.history = [];
    const log = el("chat-log");
    if (log) log.innerHTML = "";
    if (!detail.messages || !detail.messages.length) {
      showEmptyChatState(true);
    } else {
      showEmptyChatState(false);
      detail.messages.forEach((m) => {
        if (m.role === "user") {
          appendUserMessage(m.content);
          state.history.push({ role: "user", content: m.content });
        } else {
          appendAssistantMessage({
            content: m.content,
            citations: m.citations || [],
            queryLogId: m.query_log_id,
            confident: m.confident,
          });
          state.history.push({ role: "assistant", content: m.content });
        }
      });
    }
    await refreshConversationList(el("conversation-search")?.value || "");
  } catch (err) {
    console.error("loadConversation failed", err);
    alert(err.message || "Could not open conversation");
  }
}

async function submitQuestion(question) {
  const q = (question || "").trim();
  if (!q || state.chatBusy) return;

  showChatView();
  state.chatBusy = true;
  const sendBtn = el("chat-send-btn");
  const input = el("chat-input");
  if (sendBtn) sendBtn.disabled = true;
  if (input) input.value = "";

  appendUserMessage(q);
  state.history.push({ role: "user", content: q });

  // Persistence is best-effort and must NEVER block the /query call.
  let persistError = null;
  try {
    await ensureConversation(q);
    try {
      await persistMessage({ role: "user", content: q });
    } catch (err) {
      persistError = err.message || String(err);
      console.warn("Failed to persist user message", err);
    }
  } catch (err) {
    persistError = err.message || String(err);
    console.warn("Failed to create/open conversation", err);
  }

  const typing = appendTypingIndicator();
  try {
    const prior = state.history.slice(0, -1).slice(-8);
    const data = await api("/query", {
      method: "POST",
      body: { question: q, history: prior },
    });
    typing.remove();
    appendAssistantMessage({
      content: data.answer,
      citations: data.citations || [],
      queryLogId: data.query_log_id,
      confident: data.confident,
    });
    state.history.push({ role: "assistant", content: data.answer });

    if (state.conversationId) {
      try {
        await persistMessage({
          role: "assistant",
          content: data.answer,
          citations: data.citations || [],
          query_log_id: data.query_log_id,
          confident: data.confident,
        });
        await refreshConversationList(el("conversation-search")?.value || "");
      } catch (err) {
        persistError = err.message || String(err);
        console.warn("Failed to persist assistant message", err);
      }
    }

    if (persistError) {
      appendAssistantMessage({
        content: `Note: the answer above was generated, but saving this chat failed (${persistError}). You can still read the reply here.`,
        citations: [],
        queryLogId: null,
        confident: false,
      });
    }
  } catch (err) {
    typing.remove();
    console.error("Query failed", err);
    appendAssistantMessage({
      content: `Sorry — I couldn't complete that request. ${err.message || err}`,
      citations: [],
      queryLogId: null,
      confident: false,
    });
  } finally {
    state.chatBusy = false;
    if (sendBtn) sendBtn.disabled = false;
    if (input) input.focus();
  }
}

on("chat-form", "submit", async (e) => {
  e.preventDefault();
  await submitQuestion(el("chat-input")?.value || "");
});

document.querySelectorAll(".category-card, .suggestion-chip").forEach((btn) => {
  btn.addEventListener("click", (e) => {
    e.preventDefault();
    const q = btn.getAttribute("data-query") || btn.dataset.query;
    if (!q) {
      console.error("Missing data-query on suggestion control", btn);
      return;
    }
    submitQuestion(q);
  });
});

on("new-chat-btn", "click", () => {
  startNewChat(true).catch((err) => console.error("New Chat failed", err));
});

on("conversation-search", "input", (e) => {
  refreshConversationList(e.target.value.trim());
});

on("clear-history-btn", "click", async () => {
  const ok = window.confirm(
    "Delete all of your saved conversations? This cannot be undone and only affects your account.",
  );
  if (!ok) return;
  try {
    await api("/conversations", { method: "DELETE" });
    await startNewChat(true);
  } catch (err) {
    alert(err.message || "Could not clear history");
  }
});

on("sidebar-toggle-btn", "click", () => {
  el("view-chat")?.classList.toggle("sidebar-collapsed");
});

on("delete-chat-cancel", "click", () => closeDeleteChatModal());
on("delete-chat-close", "click", () => closeDeleteChatModal());
on("delete-chat-confirm", "click", () => {
  confirmDeleteChat().catch((err) => console.error("Delete chat failed", err));
});
el("delete-chat-modal")?.addEventListener("click", (e) => {
  if (e.target === el("delete-chat-modal")) closeDeleteChatModal();
});
on("delete-doc-cancel", "click", () => closeDeleteDocumentModal());
on("delete-doc-close", "click", () => closeDeleteDocumentModal());
on("delete-doc-confirm", "click", () => {
  confirmDeleteDocument().catch((err) => console.error("Delete document failed", err));
});
el("delete-doc-modal")?.addEventListener("click", (e) => {
  if (e.target === el("delete-doc-modal")) closeDeleteDocumentModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeAllConvMenus();
    closeDeleteChatModal();
    closeDeleteDocumentModal();
  }
});
document.addEventListener("click", () => closeAllConvMenus());

// ---------- documents ----------
function documentFileUrl(docId, disposition = "inline") {
  const q = new URLSearchParams({ disposition });
  return `${API_BASE}/documents/${docId}/file?${q.toString()}`;
}

function filenameFromContentDisposition(header) {
  if (!header) return "document";
  const utf = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (utf) {
    try {
      return decodeURIComponent(utf[1].trim());
    } catch (_) {
      return utf[1].trim();
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain ? plain[1].trim() : "document";
}

async function openDocumentFile(docId, disposition = "inline") {
  if (!state.token) {
    showToast("Please sign in to open documents.", "err");
    return;
  }
  try {
    const res = await fetch(documentFileUrl(docId, disposition), {
      headers: { Authorization: `Bearer ${state.token}` },
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const payload = await res.json();
        detail = payload.detail || detail;
      } catch (_) {}
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    const filename = filenameFromContentDisposition(res.headers.get("Content-Disposition"));
    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    if (disposition === "attachment") {
      const a = document.createElement("a");
      a.href = objectUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 30_000);
    } else {
      window.open(objectUrl, "_blank", "noopener,noreferrer");
      setTimeout(() => URL.revokeObjectURL(objectUrl), 120_000);
    }
  } catch (err) {
    showToast(err.message || "Could not open document.", "err");
  }
}

function setUploadStatus(message, kind) {
  const node = el("upload-status");
  if (!node) return;
  if (!message) {
    node.classList.add("hidden");
    node.textContent = "";
    node.classList.remove("ok", "err");
    return;
  }
  node.textContent = message;
  node.classList.remove("hidden", "ok", "err");
  if (kind === "ok") node.classList.add("ok");
  if (kind === "err") node.classList.add("err");
}

function resetUploadFormFields() {
  const form = el("upload-form");
  if (form) form.reset();
  setUploadStatus("", null);
}

function openDeleteDocumentModal(documentId) {
  if (state.role !== "admin" || state.docDeleteBusy) return;
  state.pendingDocDeleteId = documentId;
  el("delete-doc-modal")?.classList.remove("hidden");
  el("delete-doc-confirm")?.focus();
}

function closeDeleteDocumentModal() {
  if (state.docDeleteBusy) return;
  state.pendingDocDeleteId = null;
  el("delete-doc-modal")?.classList.add("hidden");
}

async function confirmDeleteDocument() {
  const id = state.pendingDocDeleteId;
  if (!id || state.docDeleteBusy || state.role !== "admin") return;
  state.docDeleteBusy = true;
  const confirmBtn = el("delete-doc-confirm");
  const cancelBtn = el("delete-doc-cancel");
  if (confirmBtn) {
    confirmBtn.disabled = true;
    confirmBtn.textContent = "Deleting…";
  }
  if (cancelBtn) cancelBtn.disabled = true;
  try {
    await api(`/documents/${id}`, { method: "DELETE" });
    state.pendingDocDeleteId = null;
    el("delete-doc-modal")?.classList.add("hidden");
    showToast("Document permanently deleted successfully.");
    await loadDocuments();
  } catch (err) {
    showToast(err.message || "Could not delete document.", "err");
    await loadDocuments();
  } finally {
    state.docDeleteBusy = false;
    if (confirmBtn) {
      confirmBtn.disabled = false;
      confirmBtn.textContent = "Permanently Delete";
    }
    if (cancelBtn) cancelBtn.disabled = false;
  }
}

const UNCATEGORIZED_CATEGORY = "__uncategorized__";

function setDocListError(message) {
  const node = el("doc-list-error");
  if (!node) return;
  if (!message) {
    node.classList.add("hidden");
    node.textContent = "";
    return;
  }
  node.textContent = message;
  node.classList.remove("hidden");
}

function documentsQueryPath() {
  const params = new URLSearchParams();
  params.set("page", String(state.docsPage || 1));
  params.set("page_size", String(state.docsPageSize || 10));
  if (state.docsCategory) params.set("category", state.docsCategory);
  return `/documents?${params.toString()}`;
}

async function refreshDocumentCategories() {
  const select = el("doc-category-filter");
  if (!select) return;
  const previous = state.docsCategory || "";
  try {
    const data = await api("/documents/categories");
    const categories = data.categories || [];
    select.innerHTML = `<option value="">All Categories</option>`;
    categories.forEach((name) => {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      select.appendChild(opt);
    });
    if (data.has_uncategorized) {
      const opt = document.createElement("option");
      opt.value = UNCATEGORIZED_CATEGORY;
      opt.textContent = "Uncategorized";
      select.appendChild(opt);
    }
    const stillValid =
      previous === "" ||
      (previous === UNCATEGORIZED_CATEGORY && data.has_uncategorized) ||
      categories.includes(previous);
    if (!stillValid) {
      state.docsCategory = "";
      state.docsPage = 1;
    }
    select.value = state.docsCategory || "";
  } catch (err) {
    console.error("Failed to load document categories", err);
  }
}

function renderDocumentPager() {
  const pager = el("doc-pager");
  const meta = el("doc-list-meta");
  const total = state.docsTotal || 0;
  const page = state.docsPage || 1;
  const pages = state.docsTotalPages || 1;
  if (meta) {
    meta.textContent = total
      ? `${total} document${total === 1 ? "" : "s"} · page ${page} of ${pages}`
      : "0 documents";
  }
  if (!pager) return;
  if (!total) {
    pager.innerHTML = "";
    return;
  }
  pager.innerHTML =
    `<button type="button" id="doc-page-prev"${page <= 1 ? " disabled" : ""}>Previous</button>` +
    `<span>Page ${page} of ${pages}</span>` +
    `<button type="button" id="doc-page-next"${page >= pages ? " disabled" : ""}>Next</button>`;
  el("doc-page-prev")?.addEventListener("click", () => {
    if (state.docsPage <= 1) return;
    state.docsPage -= 1;
    loadDocuments();
  });
  el("doc-page-next")?.addEventListener("click", () => {
    if (state.docsPage >= (state.docsTotalPages || 1)) return;
    state.docsPage += 1;
    loadDocuments();
  });
}

async function loadDocuments({ resetPage = false } = {}) {
  const tbody = el("doc-table-body");
  if (resetPage) state.docsPage = 1;
  setDocListError("");
  if (tbody) {
    tbody.innerHTML = `<tr><td colspan="7" class="muted">Loading documents…</td></tr>`;
  }
  try {
    await refreshDocumentCategories();
    const data = await api(documentsQueryPath());
    const docs = Array.isArray(data)
      ? data
      : (data && (data.items || data.documents)) || [];
    state.docsTotal = Array.isArray(data) ? docs.length : (data.total ?? docs.length);
    state.docsPage = Array.isArray(data) ? 1 : (data.page || 1);
    state.docsPageSize = Array.isArray(data) ? (state.docsPageSize || 10) : (data.page_size || 10);
    state.docsTotalPages = Array.isArray(data) ? 1 : Math.max(1, data.total_pages || 1);

    if (!docs.length && state.docsPage > 1 && state.docsTotal > 0) {
      state.docsPage = Math.max(1, state.docsTotalPages || 1);
      return loadDocuments();
    }

    if (tbody) tbody.innerHTML = "";
    if (!docs.length) {
      const empty = state.docsCategory
        ? "No documents match this category."
        : "No documents indexed yet.";
      if (tbody) tbody.innerHTML = `<tr><td colspan="7" class="muted">${empty}</td></tr>`;
      renderDocumentPager();
      return;
    }
    const isAdmin = state.role === "admin";
    docs.forEach((d) => {
      const tr = document.createElement("tr");
      tr.dataset.documentId = String(d.id);
      tr.dataset.docId = String(d.id);
      const status = d.processing_status || d.document_status || "—";
      const titleCell = d.has_original_file
        ? `<button type="button" class="doc-title-link" data-doc-id="${d.id}">${escapeHtml(d.title)}</button>`
        : `<span>${escapeHtml(d.title)}</span>`;
      const fileBits = [];
      if (d.has_original_file) {
        fileBits.push(
          `<button type="button" class="doc-download-link" data-doc-id="${d.id}">Download</button>`
        );
      }
      if (isAdmin) {
        fileBits.push(
          `<button type="button" class="doc-delete-btn" data-doc-id="${d.id}" title="Permanently delete" aria-label="Permanently delete ${escapeHtml(d.title)}">${trashIconSvg()}</button>`
        );
      }
      const actions = fileBits.length
        ? `<div class="doc-file-actions">${fileBits.join("")}</div>`
        : `<span class="muted">—</span>`;
      const categoryLabel = (d.category && String(d.category).trim()) || "Uncategorized";
      tr.innerHTML =
        `<td>${titleCell}<div class="doc-filename muted">${escapeHtml(d.filename || "")}</div></td>` +
        `<td>${escapeHtml(categoryLabel)}${d.academic_year ? `<div class="muted">${escapeHtml(d.academic_year)}</div>` : ""}</td>` +
        `<td>${escapeHtml((d.file_type || "").toUpperCase())}</td>` +
        `<td>${escapeHtml(status)}</td>` +
        `<td>${d.chunk_count ?? 0}</td>` +
        `<td>${new Date(d.uploaded_at).toLocaleString()}</td>` +
        `<td>${actions}</td>`;
      tbody.appendChild(tr);
    });
    tbody.querySelectorAll(".doc-title-link").forEach((btn) => {
      btn.addEventListener("click", () => openDocumentFile(Number(btn.dataset.docId), "inline"));
    });
    tbody.querySelectorAll(".doc-download-link").forEach((btn) => {
      btn.addEventListener("click", () => openDocumentFile(Number(btn.dataset.docId), "attachment"));
    });
    tbody.querySelectorAll(".doc-delete-btn").forEach((btn) => {
      btn.addEventListener("click", () => openDeleteDocumentModal(Number(btn.dataset.docId)));
    });
    renderDocumentPager();
  } catch (err) {
    console.error(err);
    const message = err.message || "Could not load documents.";
    setDocListError(message);
    if (tbody) tbody.innerHTML = `<tr><td colspan="7" class="muted">Could not load documents.</td></tr>`;
    showToast(message, "err");
    renderDocumentPager();
  }
}

el("doc-category-filter")?.addEventListener("change", () => {
  state.docsCategory = el("doc-category-filter").value || "";
  loadDocuments({ resetPage: true });
});

el("upload-toggle-btn")?.addEventListener("click", () => {
  el("upload-form")?.classList.toggle("hidden");
});

el("upload-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (state.ingestBusy) return;

  const fileInput = el("upload-file");
  const file = fileInput?.files?.[0];
  const title = (el("upload-title")?.value || "").trim();
  const category = (el("upload-category")?.value || "").trim();
  if (!file) {
    setUploadStatus("Please select a file to ingest.", "err");
    return;
  }
  if (!title || !category) {
    setUploadStatus("Title and category are required.", "err");
    return;
  }

  const fd = new FormData();
  fd.append("file", file);
  fd.append("title", title);
  fd.append("category", category);
  if (el("upload-department")?.value) fd.append("department", el("upload-department").value.trim());
  if (el("upload-year")?.value) fd.append("academic_year", el("upload-year").value.trim());

  const submitBtn = el("ingest-submit-btn");
  state.ingestBusy = true;
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = "Ingesting…";
  }
  setUploadStatus("Uploading and embedding document — this may take a moment…");
  showToast("Ingesting document…");

  try {
    const created = await api("/documents/upload", { method: "POST", body: fd, isForm: true });
    resetUploadFormFields();
    el("upload-form")?.classList.add("hidden");
    showToast("Document ingested successfully.");
    setUploadStatus("", null);
    await loadDocuments({ resetPage: true });
    if (created?.id) {
      const row = el("doc-table-body")?.querySelector(`[data-doc-id="${created.id}"]`);
      row?.closest("tr")?.classList.add("doc-row-new");
    }
  } catch (err) {
    setUploadStatus(err.message || "Ingestion failed.", "err");
    showToast(err.message || "Ingestion failed.", "err");
    // Keep metadata/file selection so the admin can retry.
    await loadDocuments();
  } finally {
    state.ingestBusy = false;
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = "Ingest document";
    }
  }
});

// ---------- admin insights (platform monitoring) ----------
async function loadAdminInsights() {
  try {
    const data = await api("/admin/insights");
    const statsHtml = `
      <div class="stat-card"><div class="value">${data.total_queries}</div><div class="label">Total queries</div></div>
      <div class="stat-card"><div class="value">${data.avg_latency_ms} ms</div><div class="label">Avg latency</div></div>
      <div class="stat-card"><div class="value">${data.feedback_up}</div><div class="label">Helpful</div></div>
      <div class="stat-card"><div class="value">${data.feedback_down}</div><div class="label">Not helpful</div></div>
    `;
    if (el("stat-grid")) el("stat-grid").innerHTML = statsHtml;
    if (el("overview-stat-grid")) el("overview-stat-grid").innerHTML = statsHtml;
    if (el("feedback-stat-grid")) {
      el("feedback-stat-grid").innerHTML = `
        <div class="stat-card"><div class="value">${data.feedback_up}</div><div class="label">Helpful ratings</div></div>
        <div class="stat-card"><div class="value">${data.feedback_down}</div><div class="label">Not helpful ratings</div></div>
        <div class="stat-card"><div class="value">${data.total_queries}</div><div class="label">Total queries logged</div></div>
      `;
    }
    const faqBody = el("faq-table-body");
    if (faqBody) {
      faqBody.innerHTML = "";
      (data.frequent_questions || []).forEach((f) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${escapeHtml(f.example_query_text)}</td><td>${f.occurrences}</td><td>${new Date(f.last_asked_at).toLocaleString()}</td>`;
        faqBody.appendChild(tr);
      });
    }

    const gapsBody = el("gaps-table-body");
    if (gapsBody) {
      gapsBody.innerHTML = "";
      data.informational_gaps.forEach((g) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${escapeHtml(g.query_text)}</td><td>${g.top_similarity?.toFixed(2) ?? "-"}</td><td>${new Date(g.created_at).toLocaleString()}</td>`;
        gapsBody.appendChild(tr);
      });
    }
    const recentBody = el("recent-table-body");
    if (recentBody) {
      recentBody.innerHTML = "";
      data.recent_queries.forEach((r) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${escapeHtml(r.query_text)}</td><td>${r.top_similarity?.toFixed(2) ?? "-"}</td><td>${r.latency_ms?.toFixed(0) ?? "-"}</td><td>${new Date(r.created_at).toLocaleString()}</td>`;
        recentBody.appendChild(tr);
      });
    }
    return data;
  } catch (err) {
    console.error(err);
    return null;
  }
}

// ---------- init ----------
(async function init() {
  if (state.token) {
    await enterApp();
  } else {
    showScreen(false);
  }
})();
