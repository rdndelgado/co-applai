import { useEffect, useState } from "react";
import {
  continueLetter,
  draftJob,
  draftSelectedJobs,
  getJobFilters,
  getJobs,
  getLetter,
  setLetterStatus,
} from "../api";

const EDITABLE_STATUSES = ["drafted", "approved", "rejected"];

export default function JobsView() {
  const [jobs, setJobs] = useState([]);
  const [filterOptions, setFilterOptions] = useState({ keywords: [], job_types: [] });
  const [keyword, setKeyword] = useState("");
  const [jobType, setJobType] = useState("");
  const [status, setStatus] = useState("");
  const [idSearch, setIdSearch] = useState("");
  const [flags, setFlags] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [busyJobId, setBusyJobId] = useState(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [error, setError] = useState(null);
  const [reviewingId, setReviewingId] = useState(null);
  const [feedbackDrafts, setFeedbackDrafts] = useState({});
  const [statusDrafts, setStatusDrafts] = useState({});
  const [letterDetails, setLetterDetails] = useState({});

  async function refresh() {
    try {
      const data = await getJobs({ keyword, job_type: jobType, status, flags });
      setJobs(data);
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    getJobFilters().then(setFilterOptions).catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keyword, jobType, status, flags]);

  useEffect(() => {
    const hasProcessing = jobs.some((j) => j.letter_status === "processing");
    if (!hasProcessing) return;
    const interval = setInterval(refresh, 4000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobs]);

  function toggleFlag(flag) {
    setFlags((prev) => (prev.includes(flag) ? prev.filter((f) => f !== flag) : [...prev, flag]));
  }

  function toggleSelect(jobId) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });
  }

  async function handleGenerate(jobId) {
    setBusyJobId(jobId);
    setError(null);
    try {
      await draftJob(jobId);
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyJobId(null);
    }
  }

  async function handleGenerateSelected() {
    setBulkBusy(true);
    setError(null);
    try {
      await draftSelectedJobs([...selected]);
      setSelected(new Set());
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setBulkBusy(false);
    }
  }

  async function handleContinue(job) {
    setBusyJobId(job.id);
    setError(null);
    try {
      await continueLetter(job.letter_id, feedbackDrafts[job.id] || "");
      setReviewingId(null);
      await refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyJobId(null);
    }
  }

  async function handleSaveStatus(job) {
    setBusyJobId(job.id);
    setError(null);
    try {
      await setLetterStatus(
        job.letter_id,
        statusDrafts[job.id] || job.letter_status,
        feedbackDrafts[job.id] || ""
      );
      await refresh();
      setLetterDetails((prev) => {
        const next = { ...prev };
        delete next[job.id];
        return next;
      });
      setReviewingId(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyJobId(null);
    }
  }

  async function handleToggleReview(job) {
    if (reviewingId === job.id) {
      setReviewingId(null);
      return;
    }
    setReviewingId(job.id);
    if (job.letter_status && job.letter_status !== "pending" && !letterDetails[job.id]) {
      try {
        const letter = await getLetter(job.letter_id);
        setLetterDetails((prev) => ({ ...prev, [job.id]: letter }));
        setStatusDrafts((prev) => ({ ...prev, [job.id]: letter.status }));
        setFeedbackDrafts((prev) => ({ ...prev, [job.id]: letter.rejection_feedback || "" }));
      } catch (err) {
        setError(err.message);
      }
    }
  }

  const visibleJobs = idSearch
    ? jobs.filter((j) => String(j.id).includes(idSearch.trim()))
    : jobs;

  return (
    <div className="jobs-view">
      <div className="jobs-filters">
        <input
          placeholder="Search by job ID"
          value={idSearch}
          onChange={(e) => setIdSearch(e.target.value)}
          style={{ maxWidth: "140px" }}
        />

        <input
          placeholder="Filter by keyword"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          list="keyword-options"
        />
        <datalist id="keyword-options">
          {filterOptions.keywords.map((k) => (
            <option key={k} value={k} />
          ))}
        </datalist>

        <select value={jobType} onChange={(e) => setJobType(e.target.value)}>
          <option value="">All job types</option>
          {filterOptions.job_types.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>

        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          <option value="none">Not drafted</option>
          <option value="pending">Pending review</option>
          <option value="drafted">Drafted</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
        </select>

        <div className="flag-filter">
          <span>Flag:</span>
          <label>
            <input
              type="checkbox"
              checked={flags.includes("custom")}
              onChange={() => toggleFlag("custom")}
            />{" "}
            🚩 custom rules
          </label>
          <label>
            <input type="checkbox" checked={flags.includes("old")} onChange={() => toggleFlag("old")} />{" "}
            ⏳ 30+ days old
          </label>
          <label>
            <input
              type="checkbox"
              checked={flags.includes("none")}
              onChange={() => toggleFlag("none")}
            />{" "}
            no flag
          </label>
        </div>

        <button disabled={bulkBusy || selected.size === 0} onClick={handleGenerateSelected}>
          {bulkBusy ? "Generating..." : `Generate selected (${selected.size})`}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      <table className="jobs-table">
        <thead>
          <tr>
            <th></th>
            <th>ID</th>
            <th>Title</th>
            <th>Keyword</th>
            <th>Job type</th>
            <th>Rate</th>
            <th>Date posted</th>
            <th>Flag</th>
            <th>Status</th>
            <th>Last changed</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {visibleJobs.map((job) => {
            const selectable = !job.letter_status && job.status === "done";
            const isReviewing = reviewingId === job.id;
            return (
              <JobRow
                key={job.id}
                job={job}
                selectable={selectable}
                selected={selected.has(job.id)}
                onToggleSelect={() => toggleSelect(job.id)}
                busy={busyJobId === job.id}
                onGenerate={() => handleGenerate(job.id)}
                isReviewing={isReviewing}
                onToggleReview={() => handleToggleReview(job)}
                feedback={feedbackDrafts[job.id] || ""}
                onFeedbackChange={(val) => setFeedbackDrafts((prev) => ({ ...prev, [job.id]: val }))}
                onContinue={() => handleContinue(job)}
                statusDraft={statusDrafts[job.id] || job.letter_status}
                onStatusDraftChange={(val) => setStatusDrafts((prev) => ({ ...prev, [job.id]: val }))}
                letterDetail={letterDetails[job.id]}
                onSaveStatus={() => handleSaveStatus(job)}
              />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function JobRow({
  job,
  selectable,
  selected,
  onToggleSelect,
  busy,
  onGenerate,
  isReviewing,
  onToggleReview,
  feedback,
  onFeedbackChange,
  onContinue,
  statusDraft,
  onStatusDraftChange,
  letterDetail,
  onSaveStatus,
}) {
  const special = job.job_context?.special_apply_instructions;
  const hasLetter = Boolean(job.letter_id);
  const isPending = job.letter_status === "pending";

  return (
    <>
      <tr>
        <td>
          {selectable && <input type="checkbox" checked={selected} onChange={onToggleSelect} />}
        </td>
        <td>{job.id}</td>
        <td>
          <a href={job.url} target="_blank" rel="noreferrer">
            {job.title}
          </a>
        </td>
        <td>{job.keyword}</td>
        <td>{job.job_type}</td>
        <td>{job.rate}</td>
        <td>{job.date_updated ? new Date(job.date_updated).toLocaleDateString() : "-"}</td>
        <td>
          {job.flagged && <span className="flag-badge">🚩 custom rules</span>}
          {job.is_old && <span className="flag-badge flag-badge-old">⏳ 30+ days old</span>}
        </td>
        <td>
          <span className={`status status-${job.letter_status || "none"}`}>
            {job.letter_status || "not drafted"}
          </span>
        </td>
        <td>{job.letter_updated_at ? new Date(job.letter_updated_at).toLocaleString() : "-"}</td>
        <td>
          {job.letter_status === "processing" && <span className="hint">Working...</span>}
          {selectable && (
            <button disabled={busy} onClick={onGenerate}>
              {busy ? "Starting..." : "Generate"}
            </button>
          )}
          {hasLetter && job.letter_status !== "processing" && (
            <button onClick={onToggleReview}>
              {isReviewing ? "Close" : isPending ? "Review & draft" : "Review / edit"}
            </button>
          )}
        </td>
      </tr>
      {isReviewing && isPending && (
        <tr>
          <td colSpan={11}>
            <div className="pending-review">
              <h4>Custom apply instructions found</h4>
              {special?.must_start_with && (
                <p>
                  <strong>Must start with:</strong> "{special.must_start_with}"
                </p>
              )}
              {special?.questions?.length > 0 && (
                <>
                  <strong>Questions to answer:</strong>
                  <ul>
                    {special.questions.map((q, i) => (
                      <li key={i}>{q}</li>
                    ))}
                  </ul>
                </>
              )}
              {special?.requires_attachment && (
                <p>
                  <strong>Attachment requested:</strong> {special.attachment_note}
                </p>
              )}
              {special?.raw_instructions && (
                <>
                  <strong>Raw instructions</strong>
                  <pre className="letter-content">{special.raw_instructions}</pre>
                </>
              )}

              <textarea
                placeholder="Feedback/notes for the agent before it drafts this one (optional)"
                value={feedback}
                onChange={(e) => onFeedbackChange(e.target.value)}
              />
              <button disabled={busy} onClick={onContinue}>
                {busy ? "Drafting..." : "Draft with this feedback"}
              </button>
            </div>
          </td>
        </tr>
      )}
      {isReviewing && !isPending && (
        <tr>
          <td colSpan={11}>
            <div className="pending-review">
              {!letterDetail ? (
                <p className="empty">Loading...</p>
              ) : (
                <>
                  <h4>Draft</h4>
                  <pre className="letter-content">{letterDetail.content || "(no draft yet)"}</pre>

                  <label>
                    Status
                    <select value={statusDraft} onChange={(e) => onStatusDraftChange(e.target.value)}>
                      {EDITABLE_STATUSES.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                  </label>

                  <textarea
                    placeholder="Feedback (used to redraft when status is set to rejected)"
                    value={feedback}
                    onChange={(e) => onFeedbackChange(e.target.value)}
                  />

                  <button disabled={busy} onClick={onSaveStatus}>
                    {busy ? (statusDraft === "rejected" ? "Redrafting..." : "Saving...") : "Save"}
                  </button>
                  {busy && statusDraft === "rejected" && (
                    <p className="hint">
                      Runs a full Writer/Critic pass against the real model, usually 20-60s.
                    </p>
                  )}
                </>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
