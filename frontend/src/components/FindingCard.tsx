import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FindingOut } from "@/api/calls";
import { getFindingHistory, reviewFinding } from "@/api/findings";
import { EvidenceChip } from "@/components/EvidenceChip";

interface FindingCardProps {
  callId: string;
  finding: FindingOut;
  onJumpToAudio: (seconds: number) => void;
}

function FindingHistory({ findingId }: { findingId: string }) {
  const { data: history, isLoading } = useQuery({
    queryKey: ["finding-history", findingId],
    queryFn: () => getFindingHistory(findingId),
  });

  if (isLoading) return <p className="history-loading">Loading history...</p>;
  if (!history || history.length === 0) return <p className="history-empty">No review actions yet.</p>;

  return (
    <ul className="finding-history">
      {history.map((entry) => (
        <li key={entry.id}>
          <span className="history-action">{entry.action_type}</span>
          {entry.previous_verdict && entry.new_verdict && entry.previous_verdict !== entry.new_verdict && (
            <span className="history-verdict-change">
              {entry.previous_verdict} → {entry.new_verdict}
            </span>
          )}
          <span className="history-meta">{new Date(entry.created_at).toLocaleString()}</span>
          {entry.notes && <p className="history-notes">{entry.notes}</p>}
        </li>
      ))}
    </ul>
  );
}

export function FindingCard({ callId, finding, onJumpToAudio }: FindingCardProps) {
  const [notes, setNotes] = useState("");
  const [correctedVerdict, setCorrectedVerdict] = useState<"pass" | "fail" | "na">(
    finding.current_verdict
  );
  const [showHistory, setShowHistory] = useState(false);
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: (body: Parameters<typeof reviewFinding>[1]) => reviewFinding(finding.id, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["call", callId] });
      queryClient.invalidateQueries({ queryKey: ["finding-history", finding.id] });
    },
  });

  return (
    <div className={`finding-card verdict-${finding.current_verdict}`}>
      <div className="finding-header">
        <h4>{finding.criterion_text}</h4>
        {finding.ai_confidence !== null && (
          <span className="confidence">AI confidence: {Math.round(finding.ai_confidence * 100)}%</span>
        )}
      </div>

      <p className="explanation">{finding.ai_explanation}</p>

      <div className="verdicts">
        <span>AI verdict: <strong>{finding.ai_verdict}</strong></span>
        <span>Current: <strong>{finding.current_verdict}</strong></span>
        {finding.human_corrected && <span className="corrected-badge">Human corrected</span>}
      </div>

      {/* "which rule produced the result" / "which model or engine version was used" —
          section 8 requires this stays explainable, not just visible in the DB. */}
      <div className="finding-provenance">
        <span title="Which rule type evaluated this criterion">rule: {finding.rule_type}</span>
        <span title="Evaluator version that produced this result">engine: {finding.engine_version}</span>
      </div>

      <div className="evidence-list">
        {finding.evidence.map((ev) => (
          <EvidenceChip key={ev.id} evidence={ev} onJump={onJumpToAudio} />
        ))}
      </div>

      <div className="review-actions">
        <button
          disabled={mutation.isPending}
          onClick={() => mutation.mutate({ action: "confirm" })}
        >
          Confirm
        </button>

        <select
          value={correctedVerdict}
          onChange={(e) => setCorrectedVerdict(e.target.value as "pass" | "fail" | "na")}
        >
          <option value="pass">pass</option>
          <option value="fail">fail</option>
          <option value="na">n/a</option>
        </select>
        <button
          disabled={mutation.isPending}
          onClick={() =>
            mutation.mutate({ action: "correct", new_verdict: correctedVerdict, notes: notes || undefined })
          }
        >
          Correct
        </button>

        {finding.reviewed_by && (
          <button disabled={mutation.isPending} onClick={() => mutation.mutate({ action: "reopen" })}>
            Reopen
          </button>
        )}
      </div>

      <input
        placeholder="Reviewer notes (optional)"
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
      />

      <button className="history-toggle" onClick={() => setShowHistory((v) => !v)}>
        {showHistory ? "Hide history" : "Who changed this, and when?"}
      </button>
      {showHistory && <FindingHistory findingId={finding.id} />}
    </div>
  );
}
