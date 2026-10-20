// main.js – Legal RAG Intelligence Frontend

const API_BASE = "http://127.0.0.1:8000";
let selectedDocId = null;
let currentDocName = null;

// ── Helpers ──────────────────────────────────────────────
function setStatus(id, message, type = "") {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = message;
  el.className = "status-msg" + (type ? " " + type : "");
}

function show(id)  { document.getElementById(id)?.classList.remove("hidden"); }
function hide(id)  { document.getElementById(id)?.classList.add("hidden"); }

function setLoading(btnId, spinnerId, loading) {
  const btn = document.getElementById(btnId);
  const spinner = document.getElementById(spinnerId);
  if (btn) btn.disabled = loading;
  if (spinner) spinner.classList.toggle("hidden", !loading);
}

// ── 1. Upload ────────────────────────────────────────────
const uploadForm = document.getElementById("upload-form");
if (uploadForm) {
  uploadForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fileInput = document.getElementById("file-input");
    const file = fileInput.files[0];
    if (!file) return setStatus("upload-status", "Please select a file first.", "error");

    const formData = new FormData();
    formData.append("file", file);

    setStatus("upload-status", "Uploading…", "loading");
    setLoading("upload-btn", "upload-spinner", true);

    try {
      const res = await fetch(`${API_BASE}/documents/upload`, {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
      setStatus("upload-status", `✅ Uploaded: ${data.document?.filename || data.id || "success"}`, "success");
      fileInput.value = "";
      loadDocuments();
    } catch (err) {
      setStatus("upload-status", "❌ " + err.message, "error");
    } finally {
      setLoading("upload-btn", "upload-spinner", false);
    }
  });
}

// ── 2. Document list ─────────────────────────────────────
async function loadDocuments() {
  const container = document.getElementById("documents-list");
  if (!container) return;

  try {
    const res = await fetch(`${API_BASE}/documents`);
    if (!res.ok) throw new Error("Failed to fetch documents");
    const docs = await res.json();

    if (!docs.length) {
      container.innerHTML = '<p class="empty-state">No documents uploaded yet.</p>';
      return;
    }

    container.innerHTML = docs.map(doc => `
      <div class="doc-item" data-id="${doc.id}">
        <div class="doc-info">
          <span class="doc-name">${doc.filename}</span>
          <span class="doc-meta">
            <span class="status-badge status-${doc.status}">${doc.status}</span>
            &nbsp;·&nbsp;${doc.total_pages || 0} pages
          </span>
        </div>
        <div class="doc-actions">
          <button class="btn btn-action" onclick="analyzeDocument('${doc.id}', '${doc.filename.replace(/'/g, "\\'")}')">Analyze</button>
          <button class="btn btn-action" onclick="showQuerySection('${doc.id}', '${doc.filename.replace(/'/g, "\\'")}')">Query</button>
        </div>
      </div>
    `).join("");
  } catch (err) {
    container.innerHTML = `<p class="empty-state" style="color:var(--danger)">⚠️ Backend unreachable – is the server running on port 8000?</p>`;
    console.error("loadDocuments error:", err);
  }
}

// ── 3. Analyze ───────────────────────────────────────────
async function analyzeDocument(id, filename) {
  selectedDocId = id;
  currentDocName = filename || null;
  show("analysis-section");
  setStatus("analysis-status", "Running 41-category CUAD analysis… (this may take a minute)", "loading");
  document.getElementById("analysis-result").innerHTML = "";

  try {
    const res = await fetch(`${API_BASE}/documents/${id}/analyze`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || JSON.stringify(data));

    const clauses = data.extracted_clauses || [];
    document.getElementById("analysis-result").innerHTML = renderAnalysisResult(data, clauses);
    setStatus("analysis-status", `✅ Done – ${clauses.length} clause(s) extracted`, "success");
  } catch (err) {
    setStatus("analysis-status", "❌ " + err.message, "error");
  }
}

function renderAnalysisResult(data, clauses) {
  if (!clauses.length) {
    return `
      <div class="no-clauses">
        <span class="no-clauses-icon">📭</span>
        <p>No clauses were extracted from this document.</p>
        <p style="font-size:0.8rem; margin-top:0.3rem;">The document may not contain standard legal contract language.</p>
      </div>
    `;
  }

  const summaryHtml = `
    <div class="analysis-summary">
      <span class="analysis-summary-icon">⚖️</span>
      <p class="analysis-summary-text">
        Analyzed <strong>${data.total_categories_analyzed}</strong> CUAD categories · Found <strong>${clauses.length}</strong> clause(s)
      </p>
    </div>
  `;

  const cardsHtml = clauses.map((c, i) => {
    const pct = Math.round(c.confidence * 100);
    const level = getConfidenceLevel(c.confidence);
    return `
      <div class="clause-card" style="animation-delay: ${i * 60}ms">
        <div class="clause-card-header">
          <div class="clause-category">
            <span class="clause-category-icon">§</span>
            ${escapeHtml(c.category)}
          </div>
          <span class="clause-confidence-pill ${level}">${pct}%</span>
        </div>
        <div class="clause-card-body">
          <p class="clause-extracted-text">"${escapeHtml(c.extracted_text)}"</p>
        </div>
        ${c.page_number ? `
        <div class="clause-card-footer">
          <span>📍</span> Page ${c.page_number}
        </div>
        ` : ""}
      </div>
    `;
  }).join("");

  return `<div class="analysis-results-container">${summaryHtml}${cardsHtml}</div>`;
}

// ── 4. Query ─────────────────────────────────────────────
function showQuerySection(id, filename) {
  selectedDocId = id;
  currentDocName = filename || null;
  show("query-section");
  document.getElementById("query-input")?.focus();
}

const queryForm = document.getElementById("query-form");
if (queryForm) {
  queryForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!selectedDocId) return setStatus("query-status", "Select a document first.", "error");

    const query = document.getElementById("query-input").value.trim();
    if (!query) return;

    setStatus("query-status", "Querying document…", "loading");
    setLoading("query-btn", "query-spinner", true);
    document.getElementById("query-result").innerHTML = "";
    const docWebResult = document.getElementById("doc-websearch-result");
    if (docWebResult) docWebResult.innerHTML = "";

    const includeWeb = document.getElementById("include-web-search-toggle")?.checked;

    try {
      const res = await fetch(`${API_BASE}/documents/${selectedDocId}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || JSON.stringify(data));

      document.getElementById("query-result").innerHTML = renderAnswerCard(data, query);
      setStatus("query-status", "✅ Answer received", "success");

      if (includeWeb) {
        if (docWebResult) {
          docWebResult.innerHTML = `<p class="status-msg loading">🔍 Searching live legal web sources (India Code, Courts, BNS 2023)…</p>`;
          try {
            const webRes = await fetch(`${API_BASE}/web-search`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ query }),
            });
            const webData = await webRes.json();
            if (webRes.ok) {
              docWebResult.innerHTML = `<h3 style="margin: 1.25rem 0 0.5rem; font-size: 1rem; color: var(--accent-secondary); display: flex; align-items: center; gap: 0.5rem;"><span>🌐</span> Verified External Legal Sources (Web)</h3>` + renderWebSearchResult(webData);
            } else {
              docWebResult.innerHTML = renderSearxngError(webData.detail || "Search backend unavailable");
            }
          } catch (webErr) {
            docWebResult.innerHTML = `<p class="status-msg error">❌ Web search failed: ${escapeHtml(webErr.message)}</p>`;
          }
        }
      } else if (data.confidence < 0.15) {
        if (docWebResult) {
          docWebResult.innerHTML = `
            <div style="margin-top: 1rem; padding: 0.9rem 1.1rem; background: rgba(108, 92, 231, 0.08); border: 1px dashed var(--border-color); border-radius: var(--border-radius-sm); text-align: center;">
              <p style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 0.6rem;">
                Looking for statutory provisions or case law? This contract had no direct match.
              </p>
              <button type="button" class="btn btn-primary btn-sm" onclick="triggerWebSearchFromQuery('${escapeHtml(query).replace(/'/g, "\\'")}')">
                🌐 Search Live Web for "${escapeHtml(query.length > 55 ? query.slice(0, 52) + '…' : query)}"
              </button>
            </div>
          `;
        }
      }
    } catch (err) {
      setStatus("query-status", "❌ " + err.message, "error");
    } finally {
      setLoading("query-btn", "query-spinner", false);
    }
  });
}

// ── 5. Live Legal Web Search ─────────────────────────────
const websearchForm = document.getElementById("websearch-form");
if (websearchForm) {
  websearchForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = document.getElementById("websearch-input").value.trim();
    if (!query) return;
    executeWebSearch(query);
  });
}

// Quick Suggestion Chips
document.querySelectorAll(".quick-chips .chip").forEach(chip => {
  chip.addEventListener("click", () => {
    const q = chip.getAttribute("data-query");
    if (!q) return;
    const input = document.getElementById("websearch-input");
    if (input) input.value = q;
    executeWebSearch(q);
  });
});

function triggerWebSearchFromQuery(q) {
  const input = document.getElementById("websearch-input");
  if (input) {
    input.value = q;
    input.scrollIntoView({ behavior: "smooth" });
  }
  executeWebSearch(q);
}

async function executeWebSearch(query) {
  setStatus("websearch-status", "Searching verified legal sources… (India Code, Supreme Court, BNS 2023)", "loading");
  setLoading("websearch-btn", "websearch-spinner", true);
  const container = document.getElementById("websearch-result");
  if (container) container.innerHTML = "";

  try {
    const res = await fetch(`${API_BASE}/web-search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    const data = await res.json();
    if (!res.ok) {
      if (res.status === 503) {
        if (container) container.innerHTML = renderSearxngError(data.detail);
        setStatus("websearch-status", "⚠️ SearXNG backend configuration required", "warning");
        return;
      }
      throw new Error(data.detail || JSON.stringify(data));
    }

    if (container) container.innerHTML = renderWebSearchResult(data);
    const count = (data.citations || []).length;
    setStatus("websearch-status", `✅ Found ${count} verified legal citation(s)`, "success");
  } catch (err) {
    setStatus("websearch-status", "❌ " + err.message, "error");
    if (container) {
      container.innerHTML = `<p class="status-msg error">Search failed: ${escapeHtml(err.message)}</p>`;
    }
  } finally {
    setLoading("websearch-btn", "websearch-spinner", false);
  }
}

function renderSearxngError(detail) {
  return `
    <div class="searxng-banner">
      <h4>⚠️ Search Backend Setup Required</h4>
      <p style="font-size:0.88rem; line-height: 1.5; margin-bottom: 0.5rem;">${escapeHtml(detail)}</p>
      <p style="font-size:0.82rem; color: var(--text-secondary); margin-bottom: 0.3rem;">Run this command in Docker to launch SearXNG with JSON search enabled:</p>
      <code>docker run -d -p 8080:8080 -v \${PWD}/searxng:/etc/searxng searxng/searxng</code>
      <p style="font-size:0.8rem; color: var(--text-muted); margin-top: 0.3rem;">Ensure <code>search.formats: [html, json]</code> is set in <code>settings.yml</code>, or configure <code>SEARXNG_URL</code> in backend <code>.env</code>.</p>
    </div>
  `;
}

function renderWebSearchResult(data) {
  const citations = data.citations || [];
  const primary = data.primary_sources || citations.filter(c => c.source_tier === "primary" || c.is_official);
  const secondary = data.secondary_sources || citations.filter(c => c.source_tier === "secondary");
  const other = citations.filter(c => !primary.includes(c) && !secondary.includes(c));

  let answerHtml = "";
  if (data.answer && data.answer.trim()) {
    answerHtml = `
      <div class="web-answer-box">
        <div class="web-answer-title">
          <span>💡</span> Legal Analysis &amp; Statutory Synthesis
        </div>
        <p class="web-answer-text">${escapeHtml(data.answer)}</p>
      </div>
    `;
  }

  function renderCitationCard(c) {
    const isPrimary = c.source_tier === "primary" || c.is_official;
    return `
      <div class="citation-card">
        <div class="citation-card-header">
          <a class="citation-title-link" href="${encodeURI(c.url)}" target="_blank" rel="noopener noreferrer">
            ${escapeHtml(c.title || c.url)} ↗
          </a>
          <div class="badge-group">
            ${isPrimary ? '<span class="badge-official">🏛️ Official / Primary</span>' : '<span class="badge-secondary">📚 Secondary Source</span>'}
          </div>
        </div>
        <div class="citation-meta">
          <span>${escapeHtml(c.source_name || c.domain)}</span>
          &bull;
          <a class="citation-url" href="${encodeURI(c.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(c.url)}</a>
          ${c.jurisdiction ? `&bull; <span>${escapeHtml(c.jurisdiction)}</span>` : ""}
        </div>
        ${c.snippet ? `
          <div class="citation-snippet">
            "${escapeHtml(c.snippet)}"
          </div>
        ` : ""}
      </div>
    `;
  }

  let primaryHtml = "";
  if (primary.length > 0) {
    primaryHtml = `
      <div class="sources-group-title primary">
        <span>🏛️</span> Official &amp; Primary Legal Sources (${primary.length})
      </div>
      <div class="sources-grid">
        ${primary.map(renderCitationCard).join("")}
      </div>
    `;
  }

  let secondaryHtml = "";
  const nonPrimaryList = [...secondary, ...other];
  if (nonPrimaryList.length > 0) {
    secondaryHtml = `
      <div class="sources-group-title secondary">
        <span>📚</span> Secondary Commentary &amp; Statutory Comparisons (${nonPrimaryList.length})
      </div>
      <div class="sources-grid">
        ${nonPrimaryList.map(renderCitationCard).join("")}
      </div>
    `;
  }

  if (!citations.length && !data.answer) {
    return `
      <div class="no-clauses">
        <span class="no-clauses-icon">📭</span>
        <p>No verified legal sources found for this query.</p>
      </div>
    `;
  }

  return `
    <div class="web-results-container">
      ${answerHtml}
      ${primaryHtml}
      ${secondaryHtml}
    </div>
  `;
}

// ── Render helpers ────────────────────────────────────────
function getConfidenceLevel(score) {
  if (score >= 0.6) return "high";
  if (score >= 0.25) return "medium";
  return "low";
}

function renderAnswerCard(data, query) {
  const pct = Math.round(data.confidence * 100);
  const level = getConfidenceLevel(data.confidence);
  const pages = (data.page_numbers || []).map(p => `Page ${p}`).join(", ") || "—";
  const docName = currentDocName || "Document";

  return `
    <div class="answer-card">
      <div class="answer-section">
        <div class="answer-label">
          <span class="answer-label-icon">💡</span>
          Contract Answer
        </div>
        <p class="answer-text">${escapeHtml(data.answer)}</p>
      </div>

      <hr class="answer-divider" />

      <div class="answer-source">
        <div class="source-item">
          <span class="source-icon">📄</span>
          <span class="source-value">${escapeHtml(docName)}</span>
        </div>
        <div class="source-item">
          <span class="source-icon">📍</span>
          <span class="source-value">${pages}</span>
        </div>
      </div>

      ${data.exact_evidence_text && data.exact_evidence_text.trim() ? `
      <hr class="answer-divider" />
      <div class="answer-clause">
        <div class="clause-label">
          <span>📜</span> Supporting Clause
        </div>
        <p class="clause-text">"${escapeHtml(data.exact_evidence_text)}"</p>
      </div>
      ` : ""}

      <div class="confidence-section">
        <span class="confidence-label">Confidence</span>
        <div class="confidence-bar-track">
          <div class="confidence-bar-fill ${level}" style="width: ${pct}%"></div>
        </div>
        <span class="confidence-value ${level}">${pct}%</span>
      </div>
    </div>
  `;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ── 6. Refresh button ────────────────────────────────────
document.getElementById("refresh-btn")?.addEventListener("click", loadDocuments);

// ── 7. Drag & drop visual feedback ──────────────────────
const dropZone = document.getElementById("drop-zone");
if (dropZone) {
  ["dragenter", "dragover"].forEach(evt =>
    dropZone.addEventListener(evt, (e) => { e.preventDefault(); dropZone.classList.add("drag-over"); })
  );
  ["dragleave", "drop"].forEach(evt =>
    dropZone.addEventListener(evt, () => dropZone.classList.remove("drag-over"))
  );
}

// ── Init ─────────────────────────────────────────────────
loadDocuments();
