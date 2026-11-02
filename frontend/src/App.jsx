import { useEffect, useState } from "react";
import "./App.css";
import { getLlmCalls, getUsage, runBatch } from "./api";
import JobsView from "./components/JobsView";
import UsageView from "./components/UsageView";

export default function App() {
  const [tab, setTab] = useState("jobs");
  const [usage, setUsage] = useState(null);
  const [llmCalls, setLlmCalls] = useState([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);

  async function refreshUsage() {
    try {
      const [usageData, callsData] = await Promise.all([getUsage(), getLlmCalls(10)]);
      setUsage(usageData);
      setLlmCalls(callsData);
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    if (tab === "usage") refreshUsage();
  }, [tab]);

  async function handleRunBatch() {
    setRunning(true);
    setError(null);
    try {
      await runBatch();
    } catch (err) {
      setError(err.message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="app">
      <header>
        <h1>co-applai</h1>
        <nav>
          <button className={tab === "jobs" ? "active" : ""} onClick={() => setTab("jobs")}>
            Jobs
          </button>
          <button className={tab === "usage" ? "active" : ""} onClick={() => setTab("usage")}>
            Usage
          </button>
        </nav>
        <button disabled={running} onClick={handleRunBatch}>
          {running ? "Starting..." : "Run batch"}
        </button>
      </header>

      {error && <p className="error">{error}</p>}

      {tab === "jobs" && <JobsView />}

      {tab === "usage" && <UsageView usage={usage} llmCalls={llmCalls} />}
    </div>
  );
}
