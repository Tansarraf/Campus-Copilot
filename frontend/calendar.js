/**
 * Student Academic Calendar + Admin Calendar Management.
 * Events are loaded from the shared backend store (same for every student).
 */
(function () {
  const CATEGORY_COLORS = {
    Examinations: "#c0392b",
    "Registration Deadlines": "#d35400",
    "Fee Deadlines": "#8e44ad",
    "Placement Drives": "#1f7a4d",
    Workshops: "#2471a3",
    Holidays: "#5d6d7e",
    "General University Events": "#1b2a4a",
  };

  const CATEGORIES = Object.keys(CATEGORY_COLORS);

  const calState = {
    events: [],
    viewYear: null,
    viewMonth: null, // 0-11
    selectedKey: null, // YYYY-MM-DD
    loadedAt: 0,
  };

  function el(id) {
    return document.getElementById(id);
  }

  function escapeHtml(str) {
    const d = document.createElement("div");
    d.textContent = str == null ? "" : String(str);
    return d.innerHTML;
  }

  function todayLocal() {
    const n = new Date();
    return { y: n.getFullYear(), m: n.getMonth(), d: n.getDate() };
  }

  function pad2(n) {
    return String(n).padStart(2, "0");
  }

  function dateKey(y, m, d) {
    return `${y}-${pad2(m + 1)}-${pad2(d)}`;
  }

  function parseEventLocalDate(iso) {
    if (!iso) return null;
    const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return null;
    return { y: +m[1], m: +m[2] - 1, d: +m[3], key: `${m[1]}-${m[2]}-${m[3]}` };
  }

  function formatTimeFromIso(iso) {
    if (!iso) return "";
    const m = String(iso).match(/T(\d{2}):(\d{2})/);
    if (!m) return "";
    const hh = +m[1];
    const mm = m[2];
    if (hh === 0 && mm === "00") return "";
    if (hh === 23 && mm === "59") return "";
    return `${pad2(hh)}:${mm}`;
  }

  function formatDisplayDate(iso) {
    const p = parseEventLocalDate(iso);
    if (!p) return iso || "";
    const dt = new Date(p.y, p.m, p.d);
    return dt.toLocaleDateString(undefined, {
      weekday: "short",
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  }

  function eventsOnKey(key) {
    return calState.events.filter((e) => {
      const start = parseEventLocalDate(e.start_datetime);
      if (!start) return false;
      const end = parseEventLocalDate(e.end_datetime) || start;
      return key >= start.key && key <= end.key;
    });
  }

  function categoryDot(category) {
    const color = CATEGORY_COLORS[category] || CATEGORY_COLORS["General University Events"];
    return `<span class="cal-dot" style="background:${color}" title="${escapeHtml(category)}"></span>`;
  }

  function badgeHtml(ev) {
    if (ev.is_official) return `<span class="cal-badge official">Official</span>`;
    return "";
  }

  function renderLegend() {
    const host = el("cal-legend");
    if (!host) return;
    host.innerHTML = CATEGORIES.map(
      (c) =>
        `<span class="cal-legend-item"><span class="cal-dot" style="background:${CATEGORY_COLORS[c]}"></span>${escapeHtml(c)}</span>`
    ).join("");
  }

  function renderGrid() {
    const grid = el("cal-grid");
    const label = el("cal-month-label");
    if (!grid || calState.viewYear == null) return;

    const y = calState.viewYear;
    const m = calState.viewMonth;
    const monthName = new Date(y, m, 1).toLocaleString(undefined, { month: "long", year: "numeric" });
    if (label) label.textContent = monthName;

    const firstDow = new Date(y, m, 1).getDay();
    const daysInMonth = new Date(y, m + 1, 0).getDate();
    const today = todayLocal();
    const todayKey = dateKey(today.y, today.m, today.d);

    const cells = [];
    for (let i = 0; i < firstDow; i++) {
      cells.push(`<div class="cal-cell empty" aria-hidden="true"></div>`);
    }
    for (let d = 1; d <= daysInMonth; d++) {
      const key = dateKey(y, m, d);
      const dayEvents = eventsOnKey(key);
      const isToday = key === todayKey;
      const isSelected = key === calState.selectedKey;
      const classes = ["cal-cell"];
      if (isToday) classes.push("today");
      if (isSelected) classes.push("selected");
      if (dayEvents.length) classes.push("has-events");

      const dots = dayEvents
        .slice(0, 4)
        .map((e) => categoryDot(e.category))
        .join("");
      const more = dayEvents.length > 4 ? `<span class="cal-more">+${dayEvents.length - 4}</span>` : "";

      cells.push(
        `<button type="button" class="${classes.join(" ")}" data-date="${key}" aria-label="${key}${dayEvents.length ? `, ${dayEvents.length} events` : ""}">
          <span class="cal-day-num">${d}</span>
          <span class="cal-dots">${dots}${more}</span>
        </button>`
      );
    }

    grid.innerHTML = cells.join("");
    grid.querySelectorAll(".cal-cell[data-date]").forEach((btn) => {
      btn.addEventListener("click", () => selectDate(btn.dataset.date));
      btn.addEventListener("mouseenter", (e) => showTooltip(e, btn.dataset.date));
      btn.addEventListener("mouseleave", hideTooltip);
      btn.addEventListener("focus", (e) => showTooltip(e, btn.dataset.date));
      btn.addEventListener("blur", hideTooltip);
    });
  }

  function showTooltip(domEvent, key) {
    const tip = el("cal-tooltip");
    if (!tip) return;
    const dayEvents = eventsOnKey(key);
    if (!dayEvents.length) {
      tip.innerHTML = `<strong>${escapeHtml(key)}</strong><p>No events scheduled</p>`;
    } else {
      tip.innerHTML =
        `<strong>${escapeHtml(key)}</strong>` +
        dayEvents
          .map((e) => {
            const t = formatTimeFromIso(e.start_datetime);
            return `<div class="cal-tip-row">${categoryDot(e.category)} <span>${escapeHtml(e.title)}</span>${
              t ? ` <span class="muted">${escapeHtml(t)}</span>` : ""
            } <em class="muted">${escapeHtml(e.category)}</em></div>`;
          })
          .join("");
    }
    tip.classList.remove("hidden");
    const rect = domEvent.currentTarget.getBoundingClientRect();
    const tipW = 260;
    let left = rect.left + window.scrollX + rect.width / 2 - tipW / 2;
    left = Math.max(8, Math.min(left, window.scrollX + window.innerWidth - tipW - 8));
    tip.style.left = `${left}px`;
    tip.style.top = `${rect.bottom + window.scrollY + 6}px`;
  }

  function hideTooltip() {
    el("cal-tooltip")?.classList.add("hidden");
  }

  function renderSelected() {
    const host = el("cal-selected-events");
    const heading = el("cal-selected-heading");
    if (!host) return;
    const key = calState.selectedKey;
    if (!key) {
      if (heading) heading.textContent = "Selected date";
      host.innerHTML = `<p class="muted">Select a date to view events.</p>`;
      return;
    }
    if (heading) heading.textContent = formatDisplayDate(key);
    const dayEvents = eventsOnKey(key);
    if (!dayEvents.length) {
      host.innerHTML = `<p class="muted">No events scheduled</p>`;
      return;
    }
    host.innerHTML = dayEvents
      .map((e) => {
        const startT = formatTimeFromIso(e.start_datetime);
        const endT = formatTimeFromIso(e.end_datetime);
        const timeLine =
          startT || endT
            ? `<div class="cal-ev-meta">${escapeHtml([startT, endT].filter(Boolean).join(" – "))}</div>`
            : "";
        const loc = e.location
          ? `<div class="cal-ev-meta">📍 ${escapeHtml(e.location)}</div>`
          : "";
        return `<article class="cal-ev-card">
          <div class="cal-ev-top">${categoryDot(e.category)} <strong>${escapeHtml(e.title)}</strong> ${badgeHtml(e)}</div>
          <div class="cal-ev-cat">${escapeHtml(e.category)}</div>
          ${timeLine}${loc}
          <p class="cal-ev-desc">${escapeHtml(e.description || "")}</p>
        </article>`;
      })
      .join("");
  }

  function startOfTodayKey() {
    const t = todayLocal();
    return dateKey(t.y, t.m, t.d);
  }

  function renderUpcoming() {
    const host = el("upcoming-scroller");
    if (!host) return;
    const todayKey = startOfTodayKey();
    const upcoming = calState.events
      .filter((e) => {
        const p = parseEventLocalDate(e.start_datetime);
        return p && p.key >= todayKey;
      })
      .slice()
      .sort((a, b) => String(a.start_datetime).localeCompare(String(b.start_datetime)));

    if (!upcoming.length) {
      host.innerHTML = `<p class="muted upcoming-empty">No upcoming published events.</p>`;
      return;
    }

    host.innerHTML = upcoming
      .map((e) => {
        const p = parseEventLocalDate(e.start_datetime);
        const t = formatTimeFromIso(e.start_datetime);
        const desc = (e.description || "").slice(0, 120);
        return `<button type="button" class="upcoming-card" data-date="${p.key}" data-event-id="${e.id}">
          <div class="upcoming-card-top">${categoryDot(e.category)} ${badgeHtml(e)}</div>
          <strong class="upcoming-title">${escapeHtml(e.title)}</strong>
          <div class="upcoming-meta">${escapeHtml(formatDisplayDate(e.start_datetime))}${t ? ` · ${escapeHtml(t)}` : ""}</div>
          <div class="upcoming-cat">${escapeHtml(e.category)}</div>
          ${e.location ? `<div class="upcoming-loc">${escapeHtml(e.location)}</div>` : ""}
          <p class="upcoming-desc">${escapeHtml(desc)}</p>
        </button>`;
      })
      .join("");

    host.querySelectorAll(".upcoming-card").forEach((card) => {
      card.addEventListener("click", () => {
        const key = card.dataset.date;
        const p = parseEventLocalDate(key);
        if (p) {
          calState.viewYear = p.y;
          calState.viewMonth = p.m;
          selectDate(key);
          renderGrid();
        }
      });
    });
  }

  function selectDate(key) {
    calState.selectedKey = key;
    hideTooltip();
    renderGrid();
    renderSelected();
  }

  function ensureViewMonth() {
    if (calState.viewYear == null) {
      const t = todayLocal();
      calState.viewYear = t.y;
      calState.viewMonth = t.m;
      calState.selectedKey = dateKey(t.y, t.m, t.d);
    }
  }

  function shiftMonth(delta) {
    ensureViewMonth();
    let m = calState.viewMonth + delta;
    let y = calState.viewYear;
    while (m < 0) {
      m += 12;
      y -= 1;
    }
    while (m > 11) {
      m -= 12;
      y += 1;
    }
    calState.viewMonth = m;
    calState.viewYear = y;
    renderGrid();
  }

  function shiftYear(delta) {
    ensureViewMonth();
    calState.viewYear += delta;
    renderGrid();
  }

  function goToday() {
    const t = todayLocal();
    calState.viewYear = t.y;
    calState.viewMonth = t.m;
    selectDate(dateKey(t.y, t.m, t.d));
    renderGrid();
    renderUpcoming();
  }

  async function fetchStudentEvents(force) {
    const stale = Date.now() - calState.loadedAt > 60_000;
    if (!force && calState.events.length && !stale) return calState.events;
    const events = await api("/calendar/events");
    calState.events = Array.isArray(events) ? events : [];
    calState.loadedAt = Date.now();
    return calState.events;
  }

  async function loadStudentCalendar(force) {
    ensureViewMonth();
    renderLegend();
    try {
      await fetchStudentEvents(!!force);
      renderGrid();
      renderSelected();
      renderUpcoming();
    } catch (err) {
      const host = el("cal-selected-events");
      if (host) host.innerHTML = `<p class="form-status err">${escapeHtml(err.message)}</p>`;
    }
  }

  window.loadStudentCalendar = loadStudentCalendar;

  // ---------- Admin calendar ----------
  function combineDateTime(dateStr, timeStr, fallbackTime) {
    if (!dateStr) return null;
    const t = timeStr || fallbackTime || "00:00";
    return `${dateStr}T${t}:00`;
  }

  function fillCategorySelect(selectEl) {
    if (!selectEl || selectEl.options.length) return;
    CATEGORIES.forEach((c) => {
      const opt = document.createElement("option");
      opt.value = c;
      opt.textContent = c;
      selectEl.appendChild(opt);
    });
  }

  function resetAdminForm() {
    el("acf-id").value = "";
    el("acf-title").value = "";
    el("acf-description").value = "";
    el("acf-category").selectedIndex = 0;
    el("acf-status").value = "published";
    el("acf-start-date").value = "";
    el("acf-end-date").value = "";
    el("acf-start-time").value = "";
    el("acf-end-time").value = "";
    el("acf-location").value = "";
    el("acf-official").value = "1";
    el("acf-source-doc").value = "";
    const title = el("admin-cal-form-title");
    if (title) title.textContent = "Add event";
    const status = el("admin-cal-form-status");
    if (status) {
      status.classList.add("hidden");
      status.textContent = "";
    }
  }

  function populateAdminForm(ev) {
    el("acf-id").value = String(ev.id);
    el("acf-title").value = ev.title || "";
    el("acf-description").value = ev.description || "";
    el("acf-category").value = ev.category;
    el("acf-status").value = ev.publication_status || "published";
    const start = parseEventLocalDate(ev.start_datetime);
    el("acf-start-date").value = start ? start.key : "";
    el("acf-start-time").value = formatTimeFromIso(ev.start_datetime) || "";
    const end = parseEventLocalDate(ev.end_datetime);
    el("acf-end-date").value = end ? end.key : "";
    el("acf-end-time").value = formatTimeFromIso(ev.end_datetime) || "";
    el("acf-location").value = ev.location || "";
    el("acf-official").value = ev.is_official || ev.is_demo === false ? (ev.is_demo ? "0" : "1") : "1";
    if (ev.is_demo) el("acf-official").value = "0";
    else el("acf-official").value = ev.is_official ? "1" : "0";
    el("acf-source-doc").value = ev.source_document_id || "";
    el("admin-cal-form-title").textContent = `Edit event #${ev.id}`;
  }

  async function loadAdminCalendar() {
    fillCategorySelect(el("acf-category"));
    const tbody = el("admin-cal-tbody");
    if (!tbody) return;
    tbody.innerHTML = `<tr><td colspan="6" class="muted">Loading…</td></tr>`;
    try {
      const events = await api("/admin/calendar/events?include_archived=true");
      if (!events.length) {
        tbody.innerHTML = `<tr><td colspan="6" class="muted">No events yet.</td></tr>`;
        return;
      }
      tbody.innerHTML = events
        .map((e) => {
          const kind = e.is_official ? "Official" : "Non-official";
          return `<tr data-id="${e.id}">
            <td>${escapeHtml(e.title)}</td>
            <td>${escapeHtml(e.category)}</td>
            <td>${escapeHtml(formatDisplayDate(e.start_datetime))}</td>
            <td>${escapeHtml(e.publication_status)}</td>
            <td>${escapeHtml(kind)}</td>
            <td class="admin-cal-actions">
              <button type="button" class="btn-secondary ac-edit" data-id="${e.id}">Edit</button>
              <button type="button" class="btn-danger-text ac-del" data-id="${e.id}">Delete</button>
            </td>
          </tr>`;
        })
        .join("");

      tbody.querySelectorAll(".ac-edit").forEach((btn) => {
        btn.addEventListener("click", () => {
          const ev = events.find((x) => String(x.id) === btn.dataset.id);
          if (ev) populateAdminForm(ev);
        });
      });
      tbody.querySelectorAll(".ac-del").forEach((btn) => {
        btn.addEventListener("click", async () => {
          if (!confirm("Delete this event for all students?")) return;
          try {
            await api(`/admin/calendar/events/${btn.dataset.id}`, { method: "DELETE" });
            await loadAdminCalendar();
            calState.loadedAt = 0;
          } catch (err) {
            alert(err.message);
          }
        });
      });
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="6" class="form-status err">${escapeHtml(err.message)}</td></tr>`;
    }
  }

  window.loadAdminCalendar = loadAdminCalendar;

  function setAdminFormStatus(msg, kind) {
    const node = el("admin-cal-form-status");
    if (!node) return;
    if (!msg) {
      node.classList.add("hidden");
      node.textContent = "";
      return;
    }
    node.textContent = msg;
    node.classList.remove("hidden", "ok", "err");
    node.classList.add(kind === "ok" ? "ok" : "err");
  }

  function wireCalendarUi() {
    el("cal-prev-month")?.addEventListener("click", () => shiftMonth(-1));
    el("cal-next-month")?.addEventListener("click", () => shiftMonth(1));
    el("cal-prev-year")?.addEventListener("click", () => shiftYear(-1));
    el("cal-next-year")?.addEventListener("click", () => shiftYear(1));
    el("cal-today-btn")?.addEventListener("click", goToday);
    el("calendar-refresh-btn")?.addEventListener("click", () => loadStudentCalendar(true));

    el("acf-reset-btn")?.addEventListener("click", resetAdminForm);
    el("admin-cal-reload-btn")?.addEventListener("click", loadAdminCalendar);

    el("admin-cal-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const title = (el("acf-title").value || "").trim();
      const startDate = el("acf-start-date").value;
      if (!title || !startDate) {
        setAdminFormStatus("Title and start date are required.", "err");
        return;
      }
      const start_datetime = combineDateTime(startDate, el("acf-start-time").value, "00:00");
      const endDate = el("acf-end-date").value;
      let end_datetime = null;
      if (endDate) {
        end_datetime = combineDateTime(endDate, el("acf-end-time").value, el("acf-end-time").value ? null : "23:59");
      } else if (el("acf-end-time").value) {
        end_datetime = combineDateTime(startDate, el("acf-end-time").value);
      }
      if (end_datetime && end_datetime < start_datetime) {
        setAdminFormStatus("End date/time must be on or after start.", "err");
        return;
      }
      const sourceRaw = el("acf-source-doc").value;
      const payload = {
        title,
        description: el("acf-description").value || null,
        category: el("acf-category").value,
        start_datetime,
        end_datetime,
        location: el("acf-location").value || null,
        is_official: el("acf-official").value === "1",
        publication_status: el("acf-status").value,
        source_document_id: sourceRaw ? Number(sourceRaw) : null,
      };
      const id = el("acf-id").value;
      const btn = el("acf-save-btn");
      btn.disabled = true;
      try {
        if (id) {
          await api(`/admin/calendar/events/${id}`, { method: "PATCH", body: payload });
          setAdminFormStatus("Event updated. All students see the change after refresh.", "ok");
        } else {
          await api("/admin/calendar/events", { method: "POST", body: payload });
          setAdminFormStatus("Event created and shared with all students.", "ok");
        }
        resetAdminForm();
        calState.loadedAt = 0;
        await loadAdminCalendar();
      } catch (err) {
        setAdminFormStatus(err.message, "err");
      } finally {
        btn.disabled = false;
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wireCalendarUi);
  } else {
    wireCalendarUi();
  }
})();
