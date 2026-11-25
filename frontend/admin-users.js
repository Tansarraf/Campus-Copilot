/**
 * Admin student directory. Uses the existing api() helper from app.js.
 * Setup codes are shown once in a modal and are not written to the console.
 */
(function () {
  const state = { page: 1, pageSize: 10, totalPages: 1 };

  function statusLabel(value) {
    if (value === "pending_activation") return "Pending setup";
    if (value === "disabled") return "Disabled";
    return "Active";
  }

  function showFormError(message) {
    const node = el("um-form-error");
    if (!node) return;
    node.textContent = message || "";
    node.classList.toggle("hidden", !message);
  }

  function openModal(mode, student) {
    el("um-modal").classList.remove("hidden");
    el("um-modal-title").textContent = mode === "edit" ? "Edit student" : "Create student";
    el("um-form-submit").textContent = mode === "edit" ? "Save changes" : "Create student";
    el("um-edit-id").value = student ? String(student.id) : "";
    el("um-name").value = student ? student.full_name : "";
    el("um-enrollment").value = student ? student.enrollment_number : "";
    el("um-enrollment").disabled = mode === "edit";
    el("um-email").value = student ? student.email || "" : "";
    el("um-course-input").value = student ? student.course || "" : "";
    el("um-year-input").value = student ? student.academic_year || "" : "";
    el("um-semester").value = student ? student.current_semester : "";
    showFormError("");
  }

  function closeModal() {
    el("um-modal")?.classList.add("hidden");
  }

  function showHandoff(setup) {
    el("um-handoff-note").textContent = setup.delivery || "No email was sent.";
    el("um-handoff-token").value = setup.token || "";
    el("um-handoff-exp").textContent = setup.expires_at ? new Date(setup.expires_at).toLocaleString() : "";
    el("um-handoff").classList.remove("hidden");
  }

  function validateClient(payload, editing) {
    if (!payload.full_name || payload.full_name.trim().split(/\s+/).length < 2) {
      return "Full name must include a first and last name.";
    }
    if (!editing && !/^\d{11}$/.test(payload.enrollment_number || "")) {
      return "Enrollment number must be exactly 11 digits.";
    }
    if (!payload.email || !payload.email.includes("@")) return "A valid email is required.";
    if (!payload.course) return "Course / department is required.";
    if (!payload.academic_year) return "Academic year is required.";
    const sem = Number(payload.current_semester);
    if (!Number.isInteger(sem) || sem < 1 || sem > 12) return "Semester must be between 1 and 12.";
    return "";
  }

  async function loadFilters() {
    const data = await api("/admin/students/filters");
    const course = el("um-course");
    const year = el("um-year");
    const courseVal = course.value;
    const yearVal = year.value;
    course.innerHTML = `<option value="">All courses</option>` + (data.courses || []).map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("");
    year.innerHTML = `<option value="">All years</option>` + (data.academic_years || []).map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("");
    course.value = courseVal;
    year.value = yearVal;
  }

  function renderRows(items) {
    const body = el("um-rows");
    if (!items.length) {
      body.innerHTML = `<tr><td colspan="8" class="muted">No students match these filters.</td></tr>`;
      return;
    }
    body.innerHTML = items.map((s) => `
      <tr data-id="${s.id}">
        <td>${escapeHtml(s.full_name)}</td>
        <td>${escapeHtml(s.enrollment_number)}</td>
        <td>${escapeHtml(s.email || "")}</td>
        <td>${escapeHtml(s.course || "")}</td>
        <td>${escapeHtml(s.academic_year || "")}</td>
        <td><span class="um-status um-${escapeHtml(s.account_status)}">${escapeHtml(statusLabel(s.account_status))}</span></td>
        <td>${escapeHtml((s.created_at || "").slice(0, 10))}</td>
        <td class="um-actions">
          <button type="button" data-um-edit="${s.id}">Edit</button>
          <button type="button" data-um-status="${s.id}" data-next="${s.account_status === "disabled" ? "active" : "disabled"}">${s.account_status === "disabled" ? "Activate" : "Deactivate"}</button>
          <button type="button" data-um-reset="${s.id}">Reset password</button>
        </td>
      </tr>
    `).join("");
    body.querySelectorAll("[data-um-edit]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const student = items.find((s) => String(s.id) === btn.dataset.umEdit);
        if (student) openModal("edit", student);
      });
    });
    body.querySelectorAll("[data-um-status]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await api(`/admin/students/${btn.dataset.umStatus}/status`, {
            method: "POST",
            body: { account_status: btn.dataset.next },
          });
          await loadAdminUsers();
        } catch (err) {
          if (typeof showToast === "function") showToast(err.message || "Could not update status.", "err");
        }
      });
    });
    body.querySelectorAll("[data-um-reset]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          const result = await api(`/admin/students/${btn.dataset.umReset}/password-reset`, { method: "POST" });
          showHandoff(result.setup);
          await loadAdminUsers();
        } catch (err) {
          if (typeof showToast === "function") showToast(err.message || "Could not reset password.", "err");
        }
      });
    });
  }

  async function loadAdminUsers() {
    const params = new URLSearchParams({
      page: String(state.page),
      page_size: String(state.pageSize),
    });
    const q = el("um-q")?.value.trim();
    const course = el("um-course")?.value;
    const year = el("um-year")?.value;
    const status = el("um-status")?.value;
    if (q) params.set("q", q);
    if (course) params.set("course", course);
    if (year) params.set("academic_year", year);
    if (status) params.set("account_status", status);
    const data = await api(`/admin/students?${params.toString()}`);
    el("um-count-total").textContent = String(data.student_count ?? data.total);
    el("um-count-active").textContent = String(data.active_count ?? "—");
    state.totalPages = data.total_pages || 1;
    el("um-page-label").textContent = `Page ${data.page} of ${state.totalPages} · ${data.total} shown`;
    renderRows(data.items || []);
    try { await loadFilters(); } catch (_) { /* filters are optional */ }
  }

  el("um-create-open")?.addEventListener("click", () => openModal("create"));
  el("um-modal-close")?.addEventListener("click", closeModal);
  el("um-form-cancel")?.addEventListener("click", closeModal);
  el("um-filters")?.addEventListener("submit", (e) => {
    e.preventDefault();
    state.page = 1;
    loadAdminUsers().catch((err) => showToast(err.message || "Could not load students.", "err"));
  });
  el("um-prev")?.addEventListener("click", () => {
    if (state.page > 1) {
      state.page -= 1;
      loadAdminUsers();
    }
  });
  el("um-next")?.addEventListener("click", () => {
    if (state.page < state.totalPages) {
      state.page += 1;
      loadAdminUsers();
    }
  });
  el("um-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const editing = Boolean(el("um-edit-id").value);
    const payload = {
      full_name: el("um-name").value.trim(),
      enrollment_number: el("um-enrollment").value.trim(),
      email: el("um-email").value.trim(),
      course: el("um-course-input").value.trim(),
      academic_year: el("um-year-input").value.trim(),
      current_semester: Number(el("um-semester").value),
    };
    const problem = validateClient(payload, editing);
    if (problem) {
      showFormError(problem);
      return;
    }
    try {
      if (editing) {
        const { enrollment_number, ...editable } = payload;
        await api(`/admin/students/${el("um-edit-id").value}`, { method: "PATCH", body: editable });
        closeModal();
        if (typeof showToast === "function") showToast("Student updated.");
      } else {
        const created = await api("/admin/students", { method: "POST", body: payload });
        closeModal();
        showHandoff(created.setup);
      }
      state.page = 1;
      await loadAdminUsers();
    } catch (err) {
      showFormError(err.message || "Could not save student.");
    }
  });
  el("um-handoff-close")?.addEventListener("click", () => el("um-handoff").classList.add("hidden"));
  el("um-handoff-done")?.addEventListener("click", () => el("um-handoff").classList.add("hidden"));
  el("um-handoff-copy")?.addEventListener("click", async () => {
    const value = el("um-handoff-token").value;
    try {
      await navigator.clipboard.writeText(value);
      if (typeof showToast === "function") showToast("Setup code copied.");
    } catch (_) {
      el("um-handoff-token").select();
    }
  });

  el("setup-password-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const statusNode = el("setup-status");
    const body = {
      token: el("setup-token").value.trim(),
      new_password: el("setup-password").value,
      confirm_password: el("setup-confirm").value,
    };
    try {
      const result = await api("/auth/setup-password", { method: "POST", body });
      statusNode.textContent = result.message || "Password saved.";
      statusNode.className = "form-status ok";
      el("setup-password").value = "";
      el("setup-confirm").value = "";
    } catch (err) {
      statusNode.textContent = err.message || "Could not save password.";
      statusNode.className = "form-status err";
    }
  });

  window.loadAdminUsers = loadAdminUsers;
})();
