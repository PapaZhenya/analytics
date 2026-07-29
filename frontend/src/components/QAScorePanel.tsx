import type { QAEvaluationOut } from "@/api/calls";

export function QAScorePanel({ evaluation }: { evaluation: QAEvaluationOut }) {
  const scorePercent =
    evaluation.overall_score !== null && evaluation.max_score
      ? Math.round((evaluation.overall_score / evaluation.max_score) * 100)
      : null;

  return (
    <div className="qa-score-panel">
      <h3>QA Score</h3>
      {scorePercent !== null ? (
        <div className={`score-value ${scorePercent < 60 ? "low" : scorePercent < 85 ? "mid" : "high"}`}>
          {scorePercent}%
        </div>
      ) : (
        <div className="score-value na">N/A</div>
      )}
      <p className="score-status">{evaluation.status === "reviewed" ? "Reviewed" : "Pending Review"}</p>
      <ul className="findings-summary">
        {evaluation.findings.map((f) => (
          <li key={f.id} className={`verdict-${f.current_verdict}`}>
            {f.criterion_text}: <strong>{f.current_verdict}</strong>
            {f.human_corrected && <span className="corrected-badge">corrected</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
