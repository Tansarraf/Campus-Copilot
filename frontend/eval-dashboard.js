/**
 * Admin Evaluation Dashboard — loads Evaluation Framework v2 persistence via
 * /admin/evaluations/* APIs. Never fabricates metric values.
 */
(function () {
  const evalState = {
    selectedRunId: null,
    questionsOffset: 0,
    questionsLimit: 25,
    questionsTotal: 0,
    historyOffset: 0,
    historyLimit: 20,
    compareA: null,
    compareB: null,
    categories: [],
  };

  function fmtPct(v) {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return null;
    return `${(Number(v) * 100).toFixed(1)}%`;
  }

  function fmtNum(v, digits = 3) {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return null;
    return Number(v).toFixed(digits);
  }

  function fmtMs(v) {
    if (v === null || v === undefined || Number.isNaN(Number(v))) return null;
    return `${Number(v).toFixed(1)} ms`;
  }

  function metricCard(label, value, formatter = fmtPct) {
    const formatted = formatter(value);
    if (formatted === null) {
      return `<div class="stat-card metric-unavailable"><div class="value unavailable">Unavailable</div><div class="label">${escapeHtml(label)}</div></div>`;
    }
    return `<div class="stat-card"><div class="value">${escapeHtml(formatted)}</div><div class="label">${escapeHtml(label)}</div></div>`;
  }

  function modePill(mock) {
    return mock
      ? `<span class="eval-mode-pill mock">Mock evaluation</span>`
      : `<span class="eval-mode-pill real">Real Gemini evaluation</span>`;
  }

  function barChart(rows) {
    // rows: [{label, value 0..1 or null}]
    if (!rows.length || rows.every((r) => r.value === null || r.value === undefined)) {
      return `<div class="eval-empty">No chart data available for this metric set.</div>`;
    }
    return `<div class="bar-chart">${rows.map((r) => {
      if (r.value === null || r.value === undefined) {
        return `<div class="bar-row"><div class="bar-label">${escapeHtml(r.label)}</div><div class="bar-track"></div><div class="bar-value na">n/a</div></div>`;
      }
      const pct = Math.max(0, Math.min(100, Number(r.value) * (r.rawMs ? 1 : 100)));
      const width = r.rawMs ? Math.max(2, Math.min(100, (Number(r.value) / (r.maxMs || 100)) * 100)) : pct;
      const display = r.rawMs ? fmtMs(r.value) : fmtPct(r.value);
      return `<div class="bar-row"><div class="bar-label">${escapeHtml(r.label)}</div><div class="bar-track"><div class="bar-fill${r.alt ? " alt" : ""}" style="width:${width}%"></div></div><div class="bar-value">${escapeHtml(display || "n/a")}</div></div>`;
    }).join("")}</div>`;
  }

  function metaGrid(meta) {
    const fields = [
      ["Run ID", meta.run_id],
      ["Timestamp", meta.timestamp ? new Date(meta.timestamp).toLocaleString() : "—"],
      ["Benchmark", `${meta.benchmark_pack} @ ${meta.benchmark_version}`],
      ["Corpus", meta.corpus_identity],
      ["Fingerprint", meta.corpus_fingerprint],
      ["Documents / chunks", `${meta.document_count} / ${meta.chunk_count}`],
      ["Embedding", `${meta.embedding_provider}/${meta.embedding_model} (dim ${meta.embedding_dim ?? "—"})`],
      ["Generation", `${meta.generation_provider}/${meta.generation_model}`],
      ["Top-K / threshold", `${meta.top_k} / ${meta.confidence_threshold}`],
      ["Status", meta.status_label || meta.status],
    ];
    return `<div class="eval-meta-grid">${fields.map(([k, v]) => `
      <div><span class="k">${escapeHtml(k)}</span><span class="v ${k === "Fingerprint" ? "fingerprint" : ""}">${escapeHtml(v == null ? "—" : String(v))}</span></div>
    `).join("")}</div>`;
  }

  function emptyEvalState(message, cliHint) {
    return `<div class="eval-empty">
      <p><strong>No evaluation available</strong></p>
      <p>${escapeHtml(message || "No evaluation results are available yet.")}</p>
      <p>Evaluations are executed from the backend CLI (UI trigger is not enabled in this milestone):</p>
      <code>${escapeHtml(cliHint || "python scripts/evaluate.py --benchmark synthetic_v1")}</code>
    </div>`;
  }

  async function ensureSelectedRun() {
    if (evalState.selectedRunId) return evalState.selectedRunId;
    const summary = await api("/admin/evaluations/summary");
    if (!summary.has_runs) return null;
    evalState.selectedRunId = summary.latest.run_id;
    return evalState.selectedRunId;
  }

  // ---------- panel routing ----------
  function showAdminPanel(name) {
    document.querySelectorAll(".admin-panel").forEach((p) => p.classList.add("hidden"));
    const panel = el(`admin-panel-${name}`);
    if (panel) panel.classList.remove("hidden");

    document.querySelectorAll(".admin-nav-btn[data-admin-panel]").forEach((b) => {
      b.classList.toggle("active", b.dataset.adminPanel === name);
    });

    if (name === "documents") {
      document.querySelectorAll(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === "documents"));
      document.querySelectorAll("#app-main > .view").forEach((v) => v.classList.add("hidden"));
      el("view-documents").classList.remove("hidden");
      loadDocuments();
      return;
    }

    if (name === "calendar") {
      if (typeof window.loadAdminCalendar === "function") {
        window.loadAdminCalendar();
      }
    }

    if (name === "users" && typeof window.loadAdminUsers === "function") {
      window.loadAdminUsers();
    }

    if (["overview", "insights", "query-logs", "feedback"].includes(name)) {
      loadAdminInsights().then((data) => {
        if (name === "overview") renderOverviewBanner();
      });
    }
    if (name === "eval-overview") renderEvalOverview();
    if (name === "eval-retrieval") renderRetrieval();
    if (name === "eval-answer") renderAnswerQuality();
    if (name === "eval-questions") renderQuestions();
    if (name === "eval-history") renderHistory();
    if (name === "eval-experiments") renderExperiments();
  }

  window.openAdminPanel = function openAdminPanel(name) {
    const view = el("view-admin");
    if (view) {
      document.querySelectorAll("#app-main > .view").forEach((v) => v.classList.add("hidden"));
      view.classList.remove("hidden");
      document.querySelectorAll(".nav-btn").forEach((b) => {
        b.classList.toggle("active", b.dataset.view === "admin");
      });
    }
    showAdminPanel(name || "overview");
  };

  document.querySelectorAll(".admin-nav-btn[data-admin-panel]").forEach((btn) => {
    btn.addEventListener("click", () => showAdminPanel(btn.dataset.adminPanel));
  });

  const evalToggle = el("admin-nav-eval-toggle");
  if (evalToggle) {
    evalToggle.addEventListener("click", () => {
      const kids = el("admin-nav-eval-children");
      const open = !kids.classList.contains("collapsed");
      kids.classList.toggle("collapsed", open);
      evalToggle.setAttribute("aria-expanded", String(!open));
    });
  }

  const sideToggle = el("admin-sidebar-toggle");
  if (sideToggle) {
    sideToggle.addEventListener("click", () => {
      el("view-admin")?.classList.toggle("admin-sidebar-collapsed");
    });
  }

  async function renderOverviewBanner() {
    const host = el("overview-eval-banner");
    if (!host) return;
    try {
      const summary = await api("/admin/evaluations/summary");
      if (!summary.has_runs) {
        host.innerHTML = emptyEvalState(summary.message, summary.cli_hint);
        return;
      }
      const latest = summary.latest;
      evalState.selectedRunId = latest.run_id;
      const dm = latest.display_metrics;
      host.innerHTML = `
        <div style="margin-bottom:10px">${modePill(latest.meta.mock_mode)}
          <strong>${escapeHtml(latest.meta.status_label)}</strong>
          <button type="button" class="secondary" id="overview-open-eval" style="margin-left:12px;padding:4px 10px;border:1px solid var(--border);border-radius:6px;background:#fff;cursor:pointer;font-family:inherit">Open Evaluation Overview</button>
        </div>
        <p class="muted" style="margin:0 0 10px">Latest run <code>${escapeHtml(latest.run_id)}</code> · ${escapeHtml(latest.meta.corpus_identity)} · ${escapeHtml(latest.meta.embedding_model)}</p>
        <div class="stat-grid">
          ${metricCard("Doc Recall@5", dm.retrieval.doc_recall["5"])}
          ${metricCard("Doc Precision@5", dm.retrieval.doc_precision["5"])}
          ${metricCard("Hit Rate@5", dm.retrieval.doc_hit_rate["5"])}
          ${metricCard("MRR (doc)", dm.retrieval.mrr_doc, fmtNum)}
        </div>
      `;
      el("overview-open-eval")?.addEventListener("click", () => showAdminPanel("eval-overview"));
    } catch (err) {
      host.innerHTML = `<div class="eval-empty">Could not load evaluation summary: ${escapeHtml(err.message)} <button type="button" id="overview-eval-retry">Retry</button></div>`;
      el("overview-eval-retry")?.addEventListener("click", renderOverviewBanner);
    }
  }

  async function renderEvalOverview() {
    const host = el("eval-overview-content");
    if (!host) return;
    host.innerHTML = `<p class="muted">Loading…</p>`;
    try {
      let run = null;
      if (evalState.selectedRunId) {
        run = await api(`/admin/evaluations/runs/${encodeURIComponent(evalState.selectedRunId)}`);
      } else {
        const summary = await api("/admin/evaluations/summary");
        if (!summary.has_runs) {
          host.innerHTML = emptyEvalState(summary.message, summary.cli_hint);
          return;
        }
        run = summary.latest;
        evalState.selectedRunId = run.run_id;
      }
      const dm = run.display_metrics;
      const aq = dm.answer_quality;
      host.innerHTML = `
        <div style="margin-bottom:12px">${modePill(run.meta.mock_mode)}<strong>${escapeHtml(run.meta.status_label)}</strong></div>
        ${metaGrid(run.meta)}
        <div class="stat-grid" style="margin-top:16px">
          <div class="stat-card"><div class="value">${run.num_questions ?? "—"}</div><div class="label">Questions</div></div>
          <div class="stat-card"><div class="value">${run.num_evaluated ?? "—"}</div><div class="label">Evaluated</div></div>
          <div class="stat-card"><div class="value">${run.num_skipped ?? "—"}</div><div class="label">Skipped</div></div>
          <div class="stat-card"><div class="value">${run.num_api_failures ?? "—"}</div><div class="label">API failures</div></div>
        </div>
        <h3 class="eval-section-title">Retrieval</h3>
        <div class="stat-grid">
          ${metricCard("Doc Recall@5", dm.retrieval.doc_recall["5"])}
          ${metricCard("Doc Precision@5", dm.retrieval.doc_precision["5"])}
          ${metricCard("Chunk Recall@5", dm.retrieval.chunk_recall["5"])}
          ${metricCard("Chunk Precision@5", dm.retrieval.chunk_precision["5"])}
          ${metricCard("Hit Rate@5", dm.retrieval.doc_hit_rate["5"])}
          ${metricCard("MRR (doc)", dm.retrieval.mrr_doc, fmtNum)}
        </div>
        <h3 class="eval-section-title">Answer quality</h3>
        <div class="stat-grid">
          ${metricCard("Faithfulness", aq.faithfulness)}
          ${metricCard("Answer correctness", aq.answer_correctness)}
          ${metricCard("Citation precision", aq.citation_precision_doc)}
          ${metricCard("Citation coverage", aq.citation_coverage_doc)}
          ${metricCard("Correct abstention rate", aq.correct_abstention_rate)}
          ${metricCard("False answer rate", aq.false_answer_rate)}
          ${metricCard("False abstention rate", aq.false_abstention_rate)}
        </div>
        <h3 class="eval-section-title">Performance</h3>
        <div class="stat-grid">
          ${metricCard("Retrieval p50", dm.performance.retrieval_p50_ms, fmtMs)}
          ${metricCard("Retrieval p95", dm.performance.retrieval_p95_ms, fmtMs)}
          ${metricCard("Generation p50", dm.performance.generation_p50_ms, fmtMs)}
          ${metricCard("Generation p95", dm.performance.generation_p95_ms, fmtMs)}
          ${metricCard("E2E p50", dm.performance.e2e_p50_ms, fmtMs)}
          ${metricCard("E2E p95", dm.performance.e2e_p95_ms, fmtMs)}
        </div>
        ${dm.unavailable_reasons && Object.keys(dm.unavailable_reasons).length ? `
          <h3 class="eval-section-title">Unavailable / not measured</h3>
          <ul class="muted">${Object.entries(dm.unavailable_reasons).slice(0, 12).map(([k, v]) =>
            `<li><strong>${escapeHtml(k)}</strong> — ${escapeHtml(v)}</li>`).join("")}</ul>
        ` : ""}
      `;
    } catch (err) {
      host.innerHTML = `<div class="eval-empty">Error: ${escapeHtml(err.message)} <button type="button" id="eval-ov-retry">Retry</button></div>`;
      el("eval-ov-retry")?.addEventListener("click", renderEvalOverview);
    }
  }

  async function renderRetrieval() {
    const host = el("eval-retrieval-content");
    if (!host) return;
    host.innerHTML = `<p class="muted">Loading…</p>`;
    try {
      const runId = await ensureSelectedRun();
      if (!runId) {
        host.innerHTML = emptyEvalState();
        return;
      }
      const data = await api(`/admin/evaluations/runs/${encodeURIComponent(runId)}/retrieval`);
      const m = data.metrics;
      const kVals = data.k_values || [1, 3, 5];
      host.innerHTML = `
        <div style="margin-bottom:12px">${modePill(data.meta.mock_mode)}
          <span class="muted">Run ${escapeHtml(runId)}</span>
        </div>
        <p class="muted">Questions without gold evidence excluded from category averages: <strong>${data.excluded_no_gold_count}</strong></p>
        <h3 class="eval-section-title">Document-level metrics across K</h3>
        ${barChart(kVals.flatMap((k) => [
          { label: `Doc Precision@${k}`, value: m.doc_precision[String(k)] },
          { label: `Doc Recall@${k}`, value: m.doc_recall[String(k)], alt: true },
          { label: `Doc Hit Rate@${k}`, value: m.doc_hit_rate[String(k)] },
        ]))}
        <h3 class="eval-section-title">Chunk-level metrics across K</h3>
        ${barChart(kVals.flatMap((k) => [
          { label: `Chunk Precision@${k}`, value: m.chunk_precision[String(k)] },
          { label: `Chunk Recall@${k}`, value: m.chunk_recall[String(k)], alt: true },
        ]))}
        <div class="stat-grid">
          ${metricCard("MRR (document)", m.mrr_doc, fmtNum)}
          ${metricCard("MRR (chunk)", m.mrr_chunk, fmtNum)}
          ${metricCard("Retrieval p50", data.latency.retrieval_p50_ms, fmtMs)}
          ${metricCard("Retrieval p95", data.latency.retrieval_p95_ms, fmtMs)}
        </div>
        <h3 class="eval-section-title">Category-wise retrieval (doc @5)</h3>
        ${barChart((data.category_breakdown || []).map((c) => ({
          label: c.category,
          value: c["doc_hit_rate@5"],
        })))}
        <h3 class="eval-section-title">No relevant document retrieved</h3>
        ${renderMiniTable(data.no_relevant_retrieved)}
        <h3 class="eval-section-title">Low retrieval ranking (MRR &lt; 0.5)</h3>
        ${renderMiniTable(data.low_ranking)}
        <h3 class="eval-section-title">Successful retrieval samples</h3>
        ${renderMiniTable(data.successful_retrievals)}
      `;
    } catch (err) {
      host.innerHTML = `<div class="eval-empty">Error: ${escapeHtml(err.message)}</div>`;
    }
  }

  function renderMiniTable(items) {
    if (!items || !items.length) return `<div class="eval-empty">None in this category.</div>`;
    return `<div class="table-scroll"><table class="log-table"><thead><tr><th>Question ID</th><th>Question</th><th>Expected</th><th>Top retrieved</th><th>Hit@5</th><th>MRR</th></tr></thead><tbody>
      ${items.slice(0, 20).map((i) => `<tr>
        <td>${escapeHtml(i.question_id)}</td>
        <td>${escapeHtml((i.question || "").slice(0, 80))}</td>
        <td>${escapeHtml((i.expected_documents || []).join(", "))}</td>
        <td>${escapeHtml((i.retrieved || []).slice(0, 3).map((r) => r.document_key || r.filename).join(", "))}</td>
        <td>${i["doc_hit_rate@5"] == null ? "n/a" : fmtPct(i["doc_hit_rate@5"])}</td>
        <td>${i.mrr_doc == null ? "n/a" : fmtNum(i.mrr_doc)}</td>
      </tr>`).join("")}
    </tbody></table></div>`;
  }

  async function renderAnswerQuality() {
    const host = el("eval-answer-content");
    if (!host) return;
    host.innerHTML = `<p class="muted">Loading…</p>`;
    try {
      const runId = await ensureSelectedRun();
      if (!runId) {
        host.innerHTML = emptyEvalState();
        return;
      }
      const run = await api(`/admin/evaluations/runs/${encodeURIComponent(runId)}`);
      const aq = run.display_metrics.answer_quality;
      const counts = aq.answerability_counts || {};
      host.innerHTML = `
        <div style="margin-bottom:12px">${modePill(run.meta.mock_mode)}
          <strong>${escapeHtml(run.meta.status_label)}</strong>
        </div>
        ${run.meta.mock_mode ? `<div class="warning-box">This is a <strong>mock evaluation</strong>. Faithfulness and genuine Gemini answer quality are not measured. Generation latency is shown only when generation actually ran.</div>` : ""}
        <h3 class="eval-section-title">Answerability performance (counts from run)</h3>
        <div class="stat-grid">
          <div class="stat-card"><div class="value">${counts.answerable_total ?? "—"}</div><div class="label">Answerable questions</div></div>
          <div class="stat-card"><div class="value">${counts.answerable_correct_answer ?? "—"}</div><div class="label">Correct answers</div></div>
          <div class="stat-card"><div class="value">${counts.answerable_false_abstention ?? "—"}</div><div class="label">False abstentions</div></div>
          <div class="stat-card"><div class="value">${counts.unanswerable_total ?? "—"}</div><div class="label">Unanswerable questions</div></div>
          <div class="stat-card"><div class="value">${counts.unanswerable_correct_abstention ?? "—"}</div><div class="label">Correct abstentions</div></div>
          <div class="stat-card"><div class="value">${counts.unanswerable_false_answer ?? "—"}</div><div class="label">False answers</div></div>
          <div class="stat-card"><div class="value">${counts.partial_total ?? "—"}</div><div class="label">Partial questions</div></div>
        </div>
        <h3 class="eval-section-title">Rates</h3>
        <div class="stat-grid">
          ${metricCard("Correct abstention rate", aq.correct_abstention_rate)}
          ${metricCard("False answer rate", aq.false_answer_rate)}
          ${metricCard("False abstention rate", aq.false_abstention_rate)}
          ${metricCard("Answerable correct-answer rate", aq.answerable_correct_answer_rate)}
        </div>
        <h3 class="eval-section-title">Citations &amp; LLM-judge (structure ready)</h3>
        <div class="stat-grid">
          ${metricCard("Citation precision (doc)", aq.citation_precision_doc)}
          ${metricCard("Citation coverage (doc)", aq.citation_coverage_doc)}
          ${metricCard("Citation precision (chunk)", aq.citation_precision_chunk)}
          ${metricCard("Citation coverage (chunk)", aq.citation_coverage_chunk)}
          ${metricCard("Faithfulness (LLM judge)", aq.faithfulness)}
          ${metricCard("Answer correctness (LLM judge)", aq.answer_correctness)}
        </div>
        <h3 class="eval-section-title">Generation latency</h3>
        <div class="stat-grid">
          ${metricCard("Generation p50", run.display_metrics.performance.generation_p50_ms, fmtMs)}
          ${metricCard("Generation p95", run.display_metrics.performance.generation_p95_ms, fmtMs)}
        </div>
      `;
    } catch (err) {
      host.innerHTML = `<div class="eval-empty">Error: ${escapeHtml(err.message)}</div>`;
    }
  }

  function buildQuestionsToolbar(categories) {
    const host = el("eval-questions-toolbar");
    if (!host) return;
    host.innerHTML = `
      <input type="search" id="eq-search" placeholder="Search question / ID" />
      <select id="eq-category"><option value="">All categories</option>${(categories || []).map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("")}</select>
      <select id="eq-answerability">
        <option value="">All answerability</option>
        <option value="answerable">answerable</option>
        <option value="unanswerable">unanswerable</option>
        <option value="partial">partial</option>
      </select>
      <select id="eq-difficulty">
        <option value="">All difficulty</option>
        <option value="easy">easy</option>
        <option value="medium">medium</option>
        <option value="hard">hard</option>
      </select>
      <select id="eq-decision">
        <option value="">Answered / abstained</option>
        <option value="answered">answered</option>
        <option value="abstained">abstained</option>
        <option value="api_failure">api_failure</option>
        <option value="retrieval_only">retrieval_only</option>
      </select>
      <select id="eq-retrieval">
        <option value="">Retrieval any</option>
        <option value="success">retrieval success</option>
        <option value="failure">retrieval failure</option>
      </select>
      <select id="eq-status">
        <option value="">Status any</option>
        <option value="ok">ok</option>
        <option value="skipped">skipped</option>
        <option value="error">error</option>
        <option value="passed">passed</option>
        <option value="failed">failed</option>
      </select>
      <button type="button" id="eq-apply">Apply</button>
    `;
    el("eq-apply")?.addEventListener("click", () => {
      evalState.questionsOffset = 0;
      loadQuestionsPage();
    });
  }

  async function renderQuestions() {
    const runId = await ensureSelectedRun();
    if (!runId) {
      el("eval-questions-body").innerHTML = "";
      el("eval-questions-toolbar").innerHTML = emptyEvalState();
      return;
    }
    // fetch once for categories
    const probe = await api(`/admin/evaluations/runs/${encodeURIComponent(runId)}/questions?limit=1&offset=0`);
    evalState.categories = probe.categories || [];
    buildQuestionsToolbar(evalState.categories);
    await loadQuestionsPage();
  }

  async function loadQuestionsPage() {
    const runId = evalState.selectedRunId;
    const body = el("eval-questions-body");
    if (!body || !runId) return;
    body.innerHTML = `<tr><td colspan="12">Loading…</td></tr>`;
    const params = new URLSearchParams({
      limit: String(evalState.questionsLimit),
      offset: String(evalState.questionsOffset),
    });
    const map = {
      q: "eq-search",
      category: "eq-category",
      answerability: "eq-answerability",
      difficulty: "eq-difficulty",
      decision: "eq-decision",
      retrieval: "eq-retrieval",
      status: "eq-status",
    };
    Object.entries(map).forEach(([param, id]) => {
      const node = el(id);
      if (node && node.value) params.set(param, node.value);
    });
    try {
      const data = await api(`/admin/evaluations/runs/${encodeURIComponent(runId)}/questions?${params}`);
      evalState.questionsTotal = data.total;
      body.innerHTML = "";
      if (!data.questions.length) {
        body.innerHTML = `<tr><td colspan="12">No questions match the filters.</td></tr>`;
      }
      data.questions.forEach((q) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${escapeHtml(q.question_id)}</td>
          <td>${escapeHtml((q.question || "").slice(0, 70))}</td>
          <td>${escapeHtml(q.category || "")}</td>
          <td>${escapeHtml(q.difficulty || "")}</td>
          <td>${escapeHtml(q.answerability || "")}</td>
          <td>${escapeHtml(q.evaluation_status)}${q.passed === true ? " ✓" : q.passed === false ? " ✗" : ""}</td>
          <td>${escapeHtml((q.expected_documents || [])[0] || "—")}</td>
          <td>${escapeHtml((q.retrieved_documents || [])[0] || "—")}</td>
          <td>${q.retrieval_rank ?? "—"}</td>
          <td>${escapeHtml(q.system_decision || "—")}</td>
          <td>${escapeHtml(q.citation_status || "—")}</td>
          <td>${q.latency_ms == null ? "—" : Number(q.latency_ms).toFixed(1)}</td>
        `;
        tr.addEventListener("click", () => openQuestionDetail(runId, q.question_id, tr));
        body.appendChild(tr);
      });
      const pager = el("eval-questions-pager");
      const start = evalState.questionsOffset + 1;
      const end = Math.min(evalState.questionsOffset + evalState.questionsLimit, data.total);
      pager.innerHTML = `
        <button type="button" id="eq-prev" ${evalState.questionsOffset <= 0 ? "disabled" : ""}>Prev</button>
        <span>${data.total ? `${start}–${end} of ${data.total}` : "0 results"}</span>
        <button type="button" id="eq-next" ${evalState.questionsOffset + evalState.questionsLimit >= data.total ? "disabled" : ""}>Next</button>
      `;
      el("eq-prev")?.addEventListener("click", () => {
        evalState.questionsOffset = Math.max(0, evalState.questionsOffset - evalState.questionsLimit);
        loadQuestionsPage();
      });
      el("eq-next")?.addEventListener("click", () => {
        evalState.questionsOffset += evalState.questionsLimit;
        loadQuestionsPage();
      });
    } catch (err) {
      body.innerHTML = `<tr><td colspan="12">Error: ${escapeHtml(err.message)}</td></tr>`;
    }
  }

  async function openQuestionDetail(runId, questionId, rowEl) {
    document.querySelectorAll(".eval-q-table tbody tr").forEach((r) => r.classList.remove("selected"));
    rowEl?.classList.add("selected");
    const host = el("eval-question-detail");
    host.classList.remove("hidden");
    host.innerHTML = `<p class="muted">Loading ${escapeHtml(questionId)}…</p>`;
    try {
      const data = await api(`/admin/evaluations/runs/${encodeURIComponent(runId)}/questions/${encodeURIComponent(questionId)}`);
      const q = data.question;
      const retrieved = q.retrieved || [];
      host.innerHTML = `
        <h3>${escapeHtml(q.question_id)}</h3>
        <p><strong>Question:</strong> ${escapeHtml(q.question)}</p>
        <p><strong>Expected answer:</strong> ${q.expected_answer == null ? "<em class='muted'>None</em>" : escapeHtml(String(q.expected_answer))}</p>
        <p><strong>Expected documents:</strong> ${escapeHtml((q.expected_document_keys || []).join(", ") || "—")}</p>
        <p><strong>Expected chunks:</strong> ${escapeHtml((q.expected_chunk_keys || []).join(", ") || "—")}</p>
        <p><strong>Decision:</strong> ${escapeHtml(q.system_decision || "—")} · confident=${q.confident === true ? "yes" : q.confident === false ? "no" : "—"}</p>
        <p><strong>Generated answer:</strong></p>
        <pre style="white-space:pre-wrap;background:var(--bg);padding:10px;border-radius:8px;font-size:0.85rem">${q.generated_answer == null ? "<em class='muted'>Not generated</em>" : escapeHtml(q.generated_answer)}</pre>
        <p><strong>Citations:</strong> ${
          q.citations
            ? escapeHtml(JSON.stringify(q.citations.document_keys || [])) +
              (q.citations.note ? ` <span class="muted">(${escapeHtml(q.citations.note)})</span>` : "")
            : "<em class='muted'>None</em>"
        }</p>
        <h4>Retrieved (ranked)</h4>
        <div class="table-scroll"><table class="log-table"><thead><tr><th>Rank</th><th>Document</th><th>Chunk</th><th>Score</th></tr></thead><tbody>
          ${retrieved.map((r) => `<tr>
            <td>${r.rank}</td><td>${escapeHtml(r.document_key || r.filename || "")}</td>
            <td>${escapeHtml(r.chunk_key || "")}</td><td>${r.score == null ? "—" : Number(r.score).toFixed(4)}</td>
          </tr>`).join("") || `<tr><td colspan="4">No retrievals</td></tr>`}
        </tbody></table></div>
        <h4>Metric contributions</h4>
        <pre style="white-space:pre-wrap;background:var(--bg);padding:10px;border-radius:8px;font-size:0.78rem">${escapeHtml(JSON.stringify(q.metrics || {}, null, 2))}</pre>
        ${q.error || q.skip_reason ? `<div class="warning-box">${escapeHtml(q.error || q.skip_reason)}</div>` : ""}
        <p class="muted">Retrieval ${q.retrieval_latency_ms ?? "—"} ms · Generation ${q.generation_latency_ms ?? "not measured"} · E2E ${q.e2e_latency_ms ?? "—"} ms</p>
      `;
    } catch (err) {
      host.innerHTML = `<div class="eval-empty">Error: ${escapeHtml(err.message)}</div>`;
    }
  }

  function buildHistoryToolbar() {
    const host = el("eval-history-toolbar");
    host.innerHTML = `
      <input type="search" id="eh-search" placeholder="Search run ID / corpus / model" />
      <select id="eh-corpus">
        <option value="">All corpora</option>
        <option value="synthetic_v1">synthetic_v1</option>
        <option value="university_v1">university_v1</option>
      </select>
      <select id="eh-mode">
        <option value="">Mock or real</option>
        <option value="true">Mock only</option>
        <option value="false">Real only</option>
      </select>
      <button type="button" id="eh-apply">Apply</button>
      <button type="button" class="secondary" id="eh-compare">Compare selected</button>
    `;
    el("eh-apply")?.addEventListener("click", () => {
      evalState.historyOffset = 0;
      loadHistoryPage();
    });
    el("eh-compare")?.addEventListener("click", runCompare);
  }

  async function renderHistory() {
    buildHistoryToolbar();
    await loadHistoryPage();
  }

  async function loadHistoryPage() {
    const body = el("eval-history-body");
    body.innerHTML = `<tr><td colspan="12">Loading…</td></tr>`;
    const params = new URLSearchParams({
      limit: String(evalState.historyLimit),
      offset: String(evalState.historyOffset),
    });
    const q = el("eh-search")?.value;
    const corpus = el("eh-corpus")?.value;
    const mode = el("eh-mode")?.value;
    if (q) params.set("q", q);
    if (corpus) params.set("corpus", corpus);
    if (mode === "true" || mode === "false") params.set("mock_mode", mode);
    try {
      const data = await api(`/admin/evaluations/runs?${params}`);
      body.innerHTML = "";
      if (!data.runs.length) {
        body.innerHTML = `<tr><td colspan="12">${emptyEvalState()}</td></tr>`;
      }
      data.runs.forEach((r) => {
        const tr = document.createElement("tr");
        const checkedA = evalState.compareA === r.run_id ? "checked" : "";
        const checkedB = evalState.compareB === r.run_id ? "checked" : "";
        tr.innerHTML = `
          <td>
            <label title="Run A"><input type="radio" name="cmp-a" value="${escapeHtml(r.run_id)}" ${checkedA}/> A</label>
            <label title="Run B"><input type="radio" name="cmp-b" value="${escapeHtml(r.run_id)}" ${checkedB}/> B</label>
          </td>
          <td><button type="button" class="text-link eh-open" data-run="${escapeHtml(r.run_id)}" style="background:none;border:none;color:var(--navy);cursor:pointer;font-family:inherit;font-weight:600">${escapeHtml(r.run_id.slice(0, 28))}…</button></td>
          <td>${escapeHtml(new Date(r.created_at).toLocaleString())}</td>
          <td>${escapeHtml(r.benchmark_version)}</td>
          <td>${escapeHtml(r.corpus_identity)}</td>
          <td>${escapeHtml(r.embedding_model || "")}</td>
          <td>${escapeHtml(r.generation_model || "")}</td>
          <td>${r.mock_mode ? "Mock" : "Real"}</td>
          <td>${r.num_questions ?? "—"}</td>
          <td>${escapeHtml(r.status_label)}</td>
          <td>${r.key_metrics?.["doc_recall@5"] == null ? "n/a" : fmtPct(r.key_metrics["doc_recall@5"])}</td>
          <td>${r.key_metrics?.mrr_doc == null ? "n/a" : fmtNum(r.key_metrics.mrr_doc)}</td>
        `;
        body.appendChild(tr);
      });
      body.querySelectorAll("input[name=cmp-a]").forEach((inp) => {
        inp.addEventListener("change", () => { evalState.compareA = inp.value; });
      });
      body.querySelectorAll("input[name=cmp-b]").forEach((inp) => {
        inp.addEventListener("change", () => { evalState.compareB = inp.value; });
      });
      body.querySelectorAll(".eh-open").forEach((btn) => {
        btn.addEventListener("click", () => {
          evalState.selectedRunId = btn.dataset.run;
          showAdminPanel("eval-overview");
          renderEvalOverview();
        });
      });
      const pager = el("eval-history-pager");
      pager.innerHTML = `
        <button type="button" id="eh-prev" ${evalState.historyOffset <= 0 ? "disabled" : ""}>Prev</button>
        <span>${data.total} run(s)</span>
        <button type="button" id="eh-next" ${evalState.historyOffset + evalState.historyLimit >= data.total ? "disabled" : ""}>Next</button>
      `;
      el("eh-prev")?.addEventListener("click", () => {
        evalState.historyOffset = Math.max(0, evalState.historyOffset - evalState.historyLimit);
        loadHistoryPage();
      });
      el("eh-next")?.addEventListener("click", () => {
        evalState.historyOffset += evalState.historyLimit;
        loadHistoryPage();
      });
    } catch (err) {
      body.innerHTML = `<tr><td colspan="12">Error: ${escapeHtml(err.message)}</td></tr>`;
    }
  }

  async function runCompare() {
    const host = el("eval-compare-panel");
    if (!evalState.compareA || !evalState.compareB) {
      host.classList.remove("hidden");
      host.innerHTML = `<div class="warning-box">Select two different runs (A and B) to compare.</div>`;
      return;
    }
    host.classList.remove("hidden");
    host.innerHTML = `<p class="muted">Comparing…</p>`;
    try {
      const data = await api(`/admin/evaluations/compare?run_a=${encodeURIComponent(evalState.compareA)}&run_b=${encodeURIComponent(evalState.compareB)}`);
      host.innerHTML = `
        <h3>Comparison</h3>
        <p>${modePill(data.run_a.meta.mock_mode)} vs ${modePill(data.run_b.meta.mock_mode)}</p>
        ${(data.warnings || []).map((w) => `<div class="warning-box">${escapeHtml(w)}</div>`).join("")}
        <div class="table-scroll"><table class="log-table"><thead><tr><th>Metric</th><th>Run A</th><th>Run B</th><th>Δ (B−A)</th></tr></thead><tbody>
          ${data.comparisons.map((c) => `<tr>
            <td>${escapeHtml(c.metric)}</td>
            <td>${c.run_a == null ? "Unavailable" : escapeHtml(String(c.run_a))}</td>
            <td>${c.run_b == null ? "Unavailable" : escapeHtml(String(c.run_b))}</td>
            <td>${c.delta == null ? "—" : escapeHtml(String(c.delta))}</td>
          </tr>`).join("")}
        </tbody></table></div>
      `;
    } catch (err) {
      host.innerHTML = `<div class="eval-empty">Error: ${escapeHtml(err.message)}</div>`;
    }
  }

  async function renderExperiments() {
    const host = el("eval-experiments-content");
    host.innerHTML = `<p class="muted">Loading…</p>`;
    try {
      const data = await api("/admin/evaluations/experiments");
      if (!data.has_runs) {
        host.innerHTML = emptyEvalState(data.message);
        return;
      }
      host.innerHTML = `
        <h3 class="eval-section-title">Tracked dimensions (from run metadata)</h3>
        <ul>${data.dimensions.map((d) => `<li><strong>${escapeHtml(d.label)}</strong> — <span class="muted">${escapeHtml(d.note)}</span></li>`).join("")}</ul>
        <h3 class="eval-section-title">Not implemented in this milestone</h3>
        <ul class="muted">${data.unimplemented_dimensions.map((d) => `<li>${escapeHtml(d)}</li>`).join("")}</ul>
        <h3 class="eval-section-title">Configuration groups with completed runs</h3>
        ${(data.experiments || []).map((ex) => `
          <div class="eval-detail-card">
            <div>${modePill(ex.mock_mode)} <strong>${escapeHtml(ex.embedding_model)}</strong> / ${escapeHtml(ex.generation_model)}</div>
            <p class="muted">top_k=${escapeHtml(String(ex.top_k))} · threshold=${escapeHtml(String(ex.confidence_threshold))} · ${ex.run_count} run(s)</p>
            <p>Latest: <button type="button" class="text-link ex-open" data-run="${escapeHtml(ex.latest_run_id)}" style="background:none;border:none;color:var(--navy);cursor:pointer;font-family:inherit">${escapeHtml(ex.latest_run_id)}</button></p>
          </div>
        `).join("") || `<div class="eval-empty">No experiment groups yet.</div>`}
      `;
      host.querySelectorAll(".ex-open").forEach((btn) => {
        btn.addEventListener("click", () => {
          evalState.selectedRunId = btn.dataset.run;
          showAdminPanel("eval-overview");
        });
      });
    } catch (err) {
      host.innerHTML = `<div class="eval-empty">Error: ${escapeHtml(err.message)}</div>`;
    }
  }
})();
