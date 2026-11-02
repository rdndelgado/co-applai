const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function request(path, options = {}) {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status}: ${text}`);
  }
  return response.json();
}

export function runBatch() {
  return request("/runs/batch", { method: "POST" });
}

export function getLetter(id) {
  return request(`/letters/${id}`);
}

export function setLetterStatus(id, status, feedback = "") {
  return request(`/letters/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ status, feedback }),
  });
}

export function getUsage() {
  return request("/usage");
}

export function getLlmCalls(limit = 10) {
  return request(`/llm_calls?limit=${limit}`);
}

export function getJobs(filters = {}) {
  const params = new URLSearchParams();
  if (filters.keyword) params.set("keyword", filters.keyword);
  if (filters.job_type) params.set("job_type", filters.job_type);
  if (filters.status) params.set("status", filters.status);
  if (filters.flags && filters.flags.length) {
    filters.flags.forEach((f) => params.append("flags", f));
  }
  const query = params.toString() ? `?${params.toString()}` : "";
  return request(`/jobs${query}`);
}

export function getJobFilters() {
  return request("/jobs/filters");
}

export function draftJob(jobId) {
  return request(`/jobs/${jobId}/draft`, { method: "POST" });
}

export function draftSelectedJobs(jobIds) {
  return request("/jobs/draft-selected", {
    method: "POST",
    body: JSON.stringify({ job_ids: jobIds }),
  });
}

export function continueLetter(letterId, feedback) {
  return request(`/letters/${letterId}/continue`, {
    method: "POST",
    body: JSON.stringify({ feedback }),
  });
}
