export default function UsageView({ usage, llmCalls }) {
  if (!usage) {
    return <p className="empty">Loading usage...</p>;
  }

  return (
    <div className="usage-view">
      <div className="usage-summary">
        <div>
          <strong>{usage.llm_calls}</strong>
          <span>LLM calls</span>
        </div>
        <div>
          <strong>{usage.tool_calls}</strong>
          <span>Tool calls</span>
        </div>
        <div>
          <strong>{usage.total_tokens}</strong>
          <span>Total tokens</span>
        </div>
        <div>
          <strong>${usage.total_cost_usd.toFixed(6)}</strong>
          <span>Estimated cost</span>
        </div>
      </div>

      <h3>By agent</h3>
      <table>
        <thead>
          <tr>
            <th>Agent</th>
            <th>Calls</th>
            <th>Tokens</th>
            <th>Cost (USD)</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(usage.by_node).map(([node, stats]) => (
            <tr key={node}>
              <td>{node}</td>
              <td>{stats.calls}</td>
              <td>{stats.tokens}</td>
              <td>${stats.cost.toFixed(6)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>API calls</h3>
      {!llmCalls || llmCalls.length === 0 ? (
        <p className="empty">No calls logged yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Timestamp</th>
              <th>Agent</th>
              <th>Model</th>
              <th>Input</th>
              <th>Output</th>
              <th>Cached</th>
              <th>Cost (USD)</th>
              <th>Duration</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {llmCalls.map((call) => (
              <tr key={call.id} className={call.status === "error" ? "row-error" : ""}>
                <td>{new Date(call.created_at).toLocaleString()}</td>
                <td>{call.node_name}</td>
                <td>{call.model}</td>
                <td>{call.input_tokens ?? "-"}</td>
                <td>{call.output_tokens ?? "-"}</td>
                <td>{call.cached_tokens ?? "-"}</td>
                <td>${(call.estimated_cost_usd ?? 0).toFixed(6)}</td>
                <td>{call.duration_ms != null ? `${call.duration_ms}ms` : "-"}</td>
                <td>
                  <span className={`status status-${call.status}`}>{call.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
