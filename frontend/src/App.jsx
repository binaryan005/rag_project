import { useEffect, useMemo, useRef, useState } from 'react';

const API_BASE = 'http://127.0.0.1:8000';

const statusStyles = {
  neutral: 'status status-neutral',
  success: 'status status-success',
  error: 'status status-error',
  loading: 'status status-loading',
};

const SUGGESTED_QUERIES = [
  { label: '🏛️ Governing Law', prompt: 'What is the governing law and jurisdiction?' },
  { label: '🛡️ Liability Cap', prompt: 'What is the limitation of liability cap?' },
  { label: '⏳ Termination', prompt: 'Under what conditions can the agreement be terminated?' },
  { label: '💰 Payment Terms', prompt: 'What are the payment terms and invoice due dates?' },
  { label: '🤝 Indemnification', prompt: 'What are the indemnification obligations?' },
  { label: '🔄 Renewal Notice', prompt: 'What is the renewal and non-renewal notice period?' },
  { label: '🔒 Confidentiality', prompt: 'What are the confidentiality obligations and survival period?' },
];

function App() {
  const [documents, setDocuments] = useState([]);
  const [selectedDocId, setSelectedDocId] = useState(null);
  const [currentDocName, setCurrentDocName] = useState('');
  const [selectedFile, setSelectedFile] = useState(null);
  const [uploadStatus, setUploadStatus] = useState({ text: 'Upload a contract to begin', tone: 'neutral' });
  const [analysisStatus, setAnalysisStatus] = useState({ text: '', tone: 'neutral' });
  const [queryStatus, setQueryStatus] = useState({ text: '', tone: 'neutral' });
  const [analysisResult, setAnalysisResult] = useState(null);
  const [queryResult, setQueryResult] = useState(null);
  const [queryHistory, setQueryHistory] = useState([]);
  const [queryText, setQueryText] = useState('');
  const [copiedKey, setCopiedKey] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isRunningAnalysis, setIsRunningAnalysis] = useState(false);
  const [isQuerying, setIsQuerying] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef(null);
  const queryInputRef = useRef(null);

  const totalClauses = useMemo(
    () => analysisResult?.clauses?.length ?? 0,
    [analysisResult]
  );

  const visibleDocuments = useMemo(() => {
    if (!selectedFile) return documents;
    const hasFileInList = documents.some((doc) => doc.filename === selectedFile.name);
    if (hasFileInList) return documents;
    return [{
      id: `pending-${selectedFile.name}`,
      filename: selectedFile.name,
      status: 'ready',
      total_pages: 0,
      isPending: true,
    }, ...documents];
  }, [documents, selectedFile]);

  useEffect(() => {
    loadDocuments();
  }, []);

  // Auto-select the first completed document if none selected
  useEffect(() => {
    if (documents.length > 0 && !selectedDocId) {
      const activeDoc = documents.find((d) => String(d.status || '').toLowerCase() === 'completed') || documents[0];
      if (activeDoc) {
        setSelectedDocId(activeDoc.id);
        setCurrentDocName(activeDoc.filename);
      }
    }
  }, [documents, selectedDocId]);

  useEffect(() => {
    if (!documents.some((doc) => String(doc.status || '').toLowerCase() === 'processing')) {
      return undefined;
    }

    const interval = setInterval(() => {
      loadDocuments();
    }, 2500);

    return () => clearInterval(interval);
  }, [documents]);

  function getStatusLabel(status) {
    const normalized = String(status || 'uploaded').toLowerCase();
    if (normalized === 'ready') return 'Ready';
    return normalized.charAt(0).toUpperCase() + normalized.slice(1);
  }

  function copyToClipboard(text, key) {
    if (!text) return;
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(() => {
        setCopiedKey(key);
        setTimeout(() => setCopiedKey(null), 2000);
      }).catch(() => {
        fallbackCopy(text, key);
      });
    } else {
      fallbackCopy(text, key);
    }
  }

  function fallbackCopy(text, key) {
    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.position = 'fixed';
    textArea.style.left = '-999999px';
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    try {
      document.execCommand('copy');
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(null), 2000);
    } catch (err) {
      console.error('Copy failed: ', err);
    }
    document.body.removeChild(textArea);
  }

  async function loadDocuments() {
    try {
      const response = await fetch(`${API_BASE}/documents`);
      if (!response.ok) {
        throw new Error('Unable to load documents');
      }

      const data = await response.json();
      const docs = Array.isArray(data) ? data : [];
      setDocuments(docs);
    } catch (error) {
      setDocuments([]);
      setUploadStatus({
        text: 'Backend is offline or unavailable on port 8000.',
        tone: 'error',
      });
    }
  }

  async function handleUpload(event) {
    event.preventDefault();
    const file = fileInputRef.current?.files?.[0] || selectedFile;

    if (!file) {
      setUploadStatus({ text: 'Please select a PDF, DOCX, or TXT file first.', tone: 'error' });
      return;
    }

    const formData = new FormData();
    formData.append('file', file);

    setSelectedFile(file);
    setIsUploading(true);
    setUploadStatus({ text: 'Uploading document…', tone: 'loading' });

    try {
      const response = await fetch(`${API_BASE}/documents/upload`, {
        method: 'POST',
        body: formData,
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || 'Upload failed');
      }

      const uploadedDoc = data.document || data;
      setUploadStatus({
        text: `Document uploaded: ${uploadedDoc.filename || data.id || 'success'}`,
        tone: 'success',
      });

      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }

      setSelectedFile(null);
      if (uploadedDoc?.id) {
        setSelectedDocId(uploadedDoc.id);
        setCurrentDocName(uploadedDoc.filename);
      }
      await loadDocuments();
    } catch (error) {
      setUploadStatus({ text: `Upload failed: ${error.message}`, tone: 'error' });
    } finally {
      setIsUploading(false);
    }
  }

  async function analyzeDocument(docId, docName) {
    setSelectedDocId(docId);
    setCurrentDocName(docName || 'Document');
    setAnalysisStatus({ text: 'Running CUAD clause extraction…', tone: 'loading' });
    setAnalysisResult(null);
    setIsRunningAnalysis(true);

    try {
      const response = await fetch(`${API_BASE}/documents/${docId}/analyze`, {
        method: 'POST',
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || 'Analysis failed');
      }

      const clauses = data.extracted_clauses || [];
      setAnalysisResult({
        totalCategories: data.total_categories_analyzed ?? 0,
        clauses,
      });
      setAnalysisStatus({
        text: `Analysis complete — ${clauses.length} clause${clauses.length === 1 ? '' : 's'} extracted.`,
        tone: 'success',
      });
    } catch (error) {
      setAnalysisStatus({ text: `Analysis failed: ${error.message}`, tone: 'error' });
    } finally {
      setIsRunningAnalysis(false);
    }
  }

  function handleSelectForQuery(doc) {
    setSelectedDocId(doc.id);
    setCurrentDocName(doc.filename);
    setQueryStatus({ text: `Active target set to "${doc.filename}". Ready for queries.`, tone: 'neutral' });
    if (queryInputRef.current) {
      queryInputRef.current.focus();
      queryInputRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }

  async function runQuery(customPrompt) {
    const promptToRun = (customPrompt || queryText).trim();

    if (!selectedDocId) {
      setQueryStatus({ text: 'Select a document before asking a question.', tone: 'error' });
      return;
    }

    if (!promptToRun) {
      setQueryStatus({ text: 'Please enter a question to continue.', tone: 'error' });
      return;
    }

    setQueryText(promptToRun);
    setIsQuerying(true);
    setQueryStatus({ text: 'Searching semantic chunks and extracting exact clauses with RoBERTa…', tone: 'loading' });

    try {
      const response = await fetch(`${API_BASE}/documents/${selectedDocId}/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: promptToRun }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || 'Query failed');
      }

      const newEntry = {
        id: Date.now(),
        query: promptToRun,
        answer: data.answer || 'No direct answer could be identified.',
        exact_evidence_text: data.exact_evidence_text || '',
        confidence: data.confidence ?? 0,
        page_numbers: data.page_numbers || [],
        docName: currentDocName || documents.find((d) => d.id === selectedDocId)?.filename || 'Document',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };

      setQueryResult(newEntry);
      setQueryHistory((prev) => [newEntry, ...prev]);
      setQueryStatus({ text: 'Answer received with verified citations.', tone: 'success' });
    } catch (error) {
      setQueryStatus({ text: `Query failed: ${error.message}`, tone: 'error' });
    } finally {
      setIsQuerying(false);
    }
  }

  async function removeDocument(docId) {
    try {
      const response = await fetch(`${API_BASE}/documents/${docId}`, {
        method: 'DELETE',
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || 'Unable to remove document');
      }

      setDocuments((currentDocuments) => {
        const remaining = currentDocuments.filter((doc) => doc.id !== docId);
        if (selectedDocId === docId) {
          if (remaining.length > 0) {
            setSelectedDocId(remaining[0].id);
            setCurrentDocName(remaining[0].filename);
          } else {
            setSelectedDocId(null);
            setCurrentDocName('');
          }
          setQueryResult(null);
          setQueryHistory([]);
        }
        return remaining;
      });

      setUploadStatus({ text: 'Document removed successfully.', tone: 'success' });
    } catch (error) {
      setUploadStatus({ text: `Unable to remove document: ${error.message}`, tone: 'error' });
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-mark">⚖</div>
          <div>
            <p className="eyebrow">Legal intelligence</p>
            <h1>Legal RAG Intelligence</h1>
          </div>
        </div>
        <div className="topbar-pill">
          <span className="dot" />
          CUAD analysis pipeline
        </div>
      </header>

      <main className="workspace-grid">
        {/* Upload Contract */}
        <section className="panel panel-surface">
          <div className="panel-header">
            <div className="header-label">
              <span className="icon">📄</span>
              <h2>Upload contract</h2>
            </div>
          </div>

          <form onSubmit={handleUpload} className="upload-form">
            <label
              className={`drop-zone ${isDragging ? 'dragging' : ''} ${selectedFile ? 'has-file' : ''}`}
              onDragOver={(event) => {
                event.preventDefault();
                setIsDragging(true);
              }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setIsDragging(false);
                const file = event.dataTransfer.files?.[0];
                if (fileInputRef.current && file) {
                  const fileList = new DataTransfer();
                  fileList.items.add(file);
                  fileInputRef.current.files = fileList.files;
                  setSelectedFile(file);
                  setUploadStatus({ text: `${file.name} selected and ready to upload`, tone: 'neutral' });
                }
              }}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.docx,.txt"
                onChange={(event) => {
                  const file = event.target.files?.[0] || null;
                  setSelectedFile(file);
                  if (file) {
                    setUploadStatus({ text: `${file.name} selected and ready to upload`, tone: 'neutral' });
                  }
                }}
              />
              <span className="drop-icon">⬆</span>
              <p>{selectedFile ? 'File ready to upload' : 'Drag and drop a contract here or browse a file'}</p>
              {selectedFile ? <div className="selected-file-pill">{selectedFile.name}</div> : <small>PDF • DOCX • TXT</small>}
            </label>

            <button type="submit" className="primary-button" disabled={isUploading}>
              {isUploading ? 'Uploading…' : 'Upload document'}
            </button>
          </form>

          <div className={statusStyles[uploadStatus.tone] || 'status'}>{uploadStatus.text}</div>
        </section>

        {/* Documents Section */}
        <section className="panel panel-surface">
          <div className="panel-header">
            <div className="header-label">
              <span className="icon">📚</span>
              <h2>Documents</h2>
            </div>
            <button type="button" className="secondary-button" onClick={loadDocuments}>
              Refresh
            </button>
          </div>

          <div className="document-list">
            {visibleDocuments.length === 0 ? (
              <div className="empty-state">No documents uploaded yet.</div>
            ) : (
              visibleDocuments.map((doc) => {
                const status = doc.isPending ? 'ready' : String(doc.status || 'uploaded').toLowerCase();
                const isSelected = selectedDocId === doc.id;

                return (
                  <div key={doc.id} className={`document-item ${isSelected ? 'active' : ''} ${doc.isPending ? 'is-pending' : ''}`}>
                    <div className="document-copy">
                      <strong>{doc.filename}</strong>
                      <span>{doc.total_pages || 0} pages {isSelected ? '• (Active Query Target)' : ''}</span>
                    </div>

                    <div className="document-meta">
                      <span className={`badge badge-${status}`}>{doc.isPending ? 'Ready' : getStatusLabel(doc.status)}</span>
                      <div className="mini-actions">
                        <button type="button" onClick={() => analyzeDocument(doc.id, doc.filename)} disabled={doc.isPending}>
                          Analyze
                        </button>
                        <button
                          type="button"
                          className={isSelected ? 'active-target-btn' : ''}
                          onClick={() => handleSelectForQuery(doc)}
                          disabled={doc.isPending}
                        >
                          {isSelected ? '✓ Selected' : 'Query'}
                        </button>
                        <button type="button" className="danger-button" onClick={() => removeDocument(doc.id)}>
                          Remove
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </section>

        {/* Clause Extraction */}
        <section className="panel panel-surface">
          <div className="panel-header">
            <div className="header-label">
              <span className="icon">🔎</span>
              <h2>Clause extraction</h2>
            </div>
            {currentDocName && (
              <span className="panel-subtext" title={currentDocName}>
                Target: {currentDocName}
              </span>
            )}
          </div>

          {analysisStatus.text ? (
            <div className={statusStyles[analysisStatus.tone] || 'status'}>{analysisStatus.text}</div>
          ) : null}

          {isRunningAnalysis ? (
            <div className="loader-card">Running CUAD clause extraction across 41 contract categories…</div>
          ) : null}

          {analysisResult && (
            <div className="analysis-block">
              <div className="summary-row">
                <span className="summary-badge">{analysisResult.totalCategories} categories checked</span>
                <span className="summary-badge alt">{totalClauses} clauses found</span>
              </div>

              <div className="clause-grid">
                {analysisResult.clauses.map((clause, index) => {
                  const confidence = Math.round((clause.confidence || 0) * 100);
                  const confidenceTone = clause.confidence >= 0.6 ? 'high' : clause.confidence >= 0.25 ? 'medium' : 'low';

                  return (
                    <article key={`${clause.category}-${index}`} className="clause-card">
                      <div className="clause-header">
                        <span className="category-pill">{clause.category}</span>
                        <span className={`confidence-pill ${confidenceTone}`}>{confidence}%</span>
                      </div>
                      <p className="clause-text">“{clause.extracted_text || 'No clause text available.'}”</p>
                      {clause.page_number ? <small>Page {clause.page_number}</small> : null}
                    </article>
                  );
                })}
              </div>
            </div>
          )}
        </section>

        {/* Enhanced Query & Intelligence Section */}
        <section className="panel panel-surface query-intelligence-panel">
          <div className="panel-header query-panel-header">
            <div className="header-label">
              <span className="icon">💬</span>
              <h2>Ask a question</h2>
            </div>
            {selectedDocId && (
              <div className="active-contract-badge">
                <span className="pulse-indicator" />
                <span className="active-doc-text" title={currentDocName || 'Active contract'}>
                  {currentDocName || 'Contract'}
                </span>
                {documents.length > 1 && (
                  <select
                    className="doc-switcher-select"
                    value={selectedDocId}
                    onChange={(e) => {
                      const doc = documents.find((d) => d.id === e.target.value);
                      if (doc) {
                        setSelectedDocId(doc.id);
                        setCurrentDocName(doc.filename);
                      }
                    }}
                    aria-label="Switch active document"
                  >
                    {documents.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.filename}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            )}
          </div>

          {/* Quick Legal Inquiries Chips */}
          <div className="query-shortcuts">
            <span className="shortcuts-label">Quick Legal Inquiries:</span>
            <div className="shortcuts-pills">
              {SUGGESTED_QUERIES.map((item, idx) => (
                <button
                  key={idx}
                  type="button"
                  className="shortcut-chip"
                  disabled={!selectedDocId || isQuerying}
                  onClick={() => runQuery(item.prompt)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>

          {/* Query Form Input */}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              runQuery();
            }}
            className="smart-query-form"
          >
            <div className="search-bar-wrapper">
              <span className="search-symbol">🔍</span>
              <input
                ref={queryInputRef}
                type="text"
                name="query"
                value={queryText}
                onChange={(e) => setQueryText(e.target.value)}
                placeholder={
                  selectedDocId
                    ? `Ask about ${currentDocName || 'contract'} (e.g. governing law, liability cap, termination)…`
                    : 'Select or upload a contract to ask questions…'
                }
                disabled={!selectedDocId || isQuerying}
                className="smart-query-input"
              />
              {queryText && (
                <button
                  type="button"
                  className="clear-input-btn"
                  onClick={() => setQueryText('')}
                  title="Clear input"
                >
                  ✕
                </button>
              )}
              <button
                type="submit"
                className="query-submit-btn"
                disabled={!selectedDocId || !queryText.trim() || isQuerying}
              >
                {isQuerying ? (
                  <span className="btn-spinner-content">
                    <span className="btn-spinner" /> Querying…
                  </span>
                ) : (
                  <span>Ask ↵</span>
                )}
              </button>
            </div>
          </form>

          {queryStatus.text ? (
            <div className={statusStyles[queryStatus.tone] || 'status'}>{queryStatus.text}</div>
          ) : null}

          {/* Shimmer Loading Skeleton */}
          {isQuerying && (
            <div className="query-skeleton-card">
              <div className="skeleton-header">
                <div className="skeleton-pulse-dot" />
                <span className="skeleton-pulse-text">Searching semantic chunks and extracting exact clauses with RoBERTa…</span>
              </div>
              <div className="skeleton-line shimmer full" />
              <div className="skeleton-line shimmer medium" />
              <div className="skeleton-line shimmer short" />
            </div>
          )}

          {/* Query Stream / History */}
          {queryHistory.length > 0 && (
            <div className="query-history-stream">
              <div className="history-stream-header">
                <div className="history-title-wrap">
                  <span className="history-icon">📜</span>
                  <h3>Session Query Stream ({queryHistory.length})</h3>
                </div>
                <button
                  type="button"
                  className="ghost-button clear-history-btn"
                  onClick={() => {
                    setQueryHistory([]);
                    setQueryResult(null);
                  }}
                >
                  Clear Stream
                </button>
              </div>

              <div className="history-cards-container">
                {queryHistory.map((item) => {
                  const hasEvidence = Boolean(item.exact_evidence_text && (item.confidence || 0) > 0);
                  const confidencePct = Math.round((item.confidence || 0) * 100);
                  const confidenceTier = confidencePct >= 80 ? 'high' : confidencePct >= 50 ? 'medium' : 'low';
                  const isCopiedAnswer = copiedKey === `ans-${item.id}`;
                  const isCopiedEvidence = copiedKey === `ev-${item.id}`;

                  return (
                    <article key={item.id} className="query-history-card">
                      <div className="q-card-top">
                        <div className="q-badge-row">
                          <span className="question-tag">Q</span>
                          <strong className="question-text">{item.query}</strong>
                        </div>
                        <div className="q-meta-badges">
                          {hasEvidence ? (
                            <span className={`confidence-badge-pill ${confidenceTier}`} title={`Confidence: ${(item.confidence || 0).toFixed(4)}`}>
                              {confidencePct}% Confidence
                            </span>
                          ) : (
                            <span className="confidence-badge-pill not-specified" title="No matching clause found in document">
                              Not in Contract
                            </span>
                          )}
                          <span className="q-timestamp">{item.timestamp}</span>
                        </div>
                      </div>

                      <div className="q-answer-container">
                        <p className="q-answer-text">{item.answer}</p>
                        <div className="q-actions-row">
                          <button
                            type="button"
                            className={`copy-chip-btn ${isCopiedAnswer ? 'copied' : ''}`}
                            onClick={() => copyToClipboard(item.answer, `ans-${item.id}`)}
                          >
                            {isCopiedAnswer ? '✓ Copied' : '📋 Copy Answer'}
                          </button>
                          {item.exact_evidence_text && (
                            <button
                              type="button"
                              className={`copy-chip-btn ${isCopiedEvidence ? 'copied' : ''}`}
                              onClick={() =>
                                copyToClipboard(
                                  `"${item.exact_evidence_text}" — Source: ${item.docName}${
                                    (item.page_numbers || []).length ? `, Page ${item.page_numbers.join(', ')}` : ''
                                  }`,
                                  `ev-${item.id}`
                                )
                              }
                            >
                              {isCopiedEvidence ? '✓ Citation Copied' : '📑 Copy Citation'}
                            </button>
                          )}
                        </div>
                      </div>

                      {item.exact_evidence_text && (
                        <div className="exact-evidence-card">
                          <div className="evidence-header-bar">
                            <span className="evidence-tag">
                              <span className="evidence-icon">⚖</span> Verbatim Supporting Clause
                            </span>
                            <div className="evidence-source-pill">
                              <span>{item.docName}</span>
                              {(item.page_numbers || []).length > 0 && (
                                <span className="page-pill">Page {item.page_numbers.join(', ')}</span>
                              )}
                            </div>
                          </div>
                          <blockquote className="evidence-quote">
                            “{item.exact_evidence_text}”
                          </blockquote>
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
            </div>
          )}

          {!queryHistory.length && !isQuerying && (
            <div className="query-empty-hint">
              <span className="hint-icon">💡</span>
              <p>
                Select a quick legal question above or type your own prompt to extract direct answers with supporting verbatim contract clauses and verified confidence scores.
              </p>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

export default App;
