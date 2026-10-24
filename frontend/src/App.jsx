
import { useState } from "react";
import "./App.css";


const API_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

function App() {
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [question, setQuestion] = useState("");
  const [answerData, setAnswerData] = useState(null);
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState("");

  const handleFileChange = (event) => {
    const selectedFile = event.target.files?.[0];

    setResult(null);
    setAnswerData(null);
    setError("");
    setAskError("");

    if (!selectedFile) {
      setFile(null);
      return;
    }

    if (
      selectedFile.type !== "application/pdf" &&
      !selectedFile.name.toLowerCase().endsWith(".pdf")
    ) {
      setFile(null);
      setError("Please select a PDF file.");
      event.target.value = "";
      return;
    }

    if (selectedFile.size > 15 * 1024 * 1024) {
      setFile(null);
      setError("The PDF must be smaller than 15 MB.");
      event.target.value = "";
      return;
    }

    setFile(selectedFile);
  };

  const uploadPaper = async () => {
    if (!file) {
      setError("Please select a research paper first.");
      return;
    }

    setLoading(true);
    setError("");
    setResult(null);
    setAnswerData(null);
    setAskError("");

    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await fetch(`${API_URL}/upload-paper`, {
        method: "POST",
        body: formData,
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Upload failed.");
      }

      setResult(data);
    } catch (err) {
      setError(
        err.message ||
          "Could not connect to the backend. Check that FastAPI is running."
      );
    } finally {
      setLoading(false);
    }
  };

  const askQuestion = async (event) => {
    event.preventDefault();

    if (!question.trim()) {
      setAskError("Please enter a question.");
      return;
    }

    setAsking(true);
    setAskError("");
    setAnswerData(null);

    try {
      const response = await fetch(`${API_URL}/ask`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          question: question.trim(),
          top_k: 5,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Could not generate an answer.");
      }

      setAnswerData(data);
    } catch (err) {
      setAskError(
        err.message ||
          "Could not connect to ResearchMate AI. Check the backend."
      );
    } finally {
      setAsking(false);
    }
  };

  return (
    <div className="app">
      <nav className="navbar">
        <a className="logo" href="#">
          <span className="logo-icon">R</span>
          ResearchMate <span className="ai-label">AI</span>
        </a>
        <span className="nav-label">Research Workspace</span>
      </nav>

      <main className="main-content">
        <div className="eyebrow">
          <span className="status-dot"></span>
          YOUR AI RESEARCH WORKSPACE
        </div>

        <h1>
          Understand research.
          <br />
          <span>One paper at a time.</span>
        </h1>

        <p className="subtitle">
          Upload research papers, ask questions in natural language,
          and explore answers grounded in retrieved paper passages.
        </p>

        {/* PDF upload */}
        <section className="upload-card">
          <div className="section-heading">
            <div>
              <h2>1. Upload a research paper</h2>
              <p>Choose a PDF to process and index.</p>
            </div>
            <span className="pdf-badge">PDF</span>
          </div>

          <label className="drop-zone" htmlFor="paper-upload">
            <div className="upload-icon">↑</div>
            <strong>
              {file ? file.name : "Choose your research paper"}
            </strong>
            <span>
              {file
                ? `${(file.size / (1024 * 1024)).toFixed(2)} MB`
                : "Click here to browse your files"}
            </span>
            <span className="file-hint">PDF only · Maximum 15 MB</span>
          </label>

          <input
            id="paper-upload"
            type="file"
            accept=".pdf,application/pdf"
            onChange={handleFileChange}
            hidden
          />

          {file && (
            <div className="selected-file">
              <span className="file-icon">PDF</span>
              <div className="file-details">
                <strong>{file.name}</strong>
                <span>Ready to process</span>
              </div>
              <button
                type="button"
                className="remove-button"
                onClick={() => {
                  setFile(null);
                  setResult(null);
                  setAnswerData(null);
                  setError("");
                  setAskError("");
                  document.getElementById("paper-upload").value = "";
                }}
                aria-label="Remove selected file"
              >
                ×
              </button>
            </div>
          )}

          <button
            type="button"
            className="upload-button"
            onClick={uploadPaper}
            disabled={!file || loading}
          >
            {loading ? (
              <>
                <span className="spinner"></span>
                Processing paper...
              </>
            ) : (
              <>Process research paper <span>→</span></>
            )}
          </button>

          {error && (
            <div className="error-message" role="alert">
              {error}
            </div>
          )}
        </section>

        {/* Upload confirmation */}
        {result && (
          <section className="results-card">
            <div className="success-heading">
              <span className="success-icon">✓</span>
              <div>
                <h2>Paper processed successfully</h2>
                <p>{result.filename}</p>
              </div>
            </div>

            <div className="stats-grid">
              <div className="stat">
                <span>Pages</span>
                <strong>{result.pages}</strong>
              </div>
              <div className="stat">
                <span>Text characters</span>
                <strong>
                  {Number(result.characters).toLocaleString()}
                </strong>
              </div>
              <div className="stat">
                <span>Stored chunks</span>
                <strong>{result.total_chunks}</strong>
              </div>
            </div>

            <p className="result-note">
              Your paper has been indexed and is ready for questions.
            </p>
          </section>
        )}

        {/* Ask ResearchMate */}
        <section className="upload-card ask-card">
          <div className="section-heading">
            <div>
              <h2>2. Ask your research paper</h2>
              <p>
                Ask a question and get an AI-generated answer with sources.
              </p>
            </div>
            <span className="pdf-badge">AI</span>
          </div>

          <form onSubmit={askQuestion}>
            <label className="question-label" htmlFor="research-question">
              Your question
            </label>

            <textarea
              id="research-question"
              className="question-input"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="e.g. What methodology does this paper use?"
              rows={4}
              maxLength={1000}
            />

            <button
              type="submit"
              className="upload-button"
              disabled={asking || !question.trim()}
            >
              {asking ? (
                <>
                  <span className="spinner"></span>
                  Researching your question...
                </>
              ) : (
                <>Ask ResearchMate AI <span>→</span></>
              )}
            </button>
          </form>

          {askError && (
            <div className="error-message" role="alert">
              {askError}
            </div>
          )}

          {answerData && (
            <div className="answer-section">
              <div className="answer-heading">
                <span className="success-icon">✦</span>
                <div>
                  <h3>ResearchMate's answer</h3>
                  <p>Generated from retrieved research passages</p>
                </div>
              </div>

              <div className="answer-text">
                {answerData.answer}
              </div>

              
<div className="sources-section">
  <h3>Sources used</h3>

  {answerData.sources?.length > 0 ? (
    answerData.sources.map((source) => (
      <details
        className="source-item"
        key={`${source.id}-${source.filename}-${source.chunk_id}`}
      >
        <summary>
          <strong>[{source.id}]</strong>{" "}
          {source.filename}
          {source.page != null
            ? ` · Page ${source.page}`
            : " · Page unavailable"}
        </summary>

        <div className="source-details">
          <p>
            <strong>Chunk:</strong>{" "}
            {source.chunk_id ?? "Unavailable"}
          </p>

          {source.similarity != null && (
            <p>
              <strong>Similarity score:</strong>{" "}
              {(Number(source.similarity) * 100).toFixed(1)}%
            </p>
          )}

          <div className="passage-preview">
            <strong>Retrieved passage</strong>
            <p>
              {source.passage ||
                "Passage text is unavailable. Please ask the question again."}
            </p>
          </div>
        </div>
      </details>
    ))
  ) : (
    <p>No source metadata was returned.</p>
  )}
</div>

            </div>
          )}
        </section>

        <footer>
          ResearchMate AI · Built for smarter literature research
        </footer>
      </main>
    </div>
  );
}

export default App;
