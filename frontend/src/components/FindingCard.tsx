import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { FindingOut } from "@/api/calls";
import { reviewFinding } from "@/api/findings";
import { EvidenceChip } from "@/components/EvidenceChip";

interface FindingCardProps {
  callId: string;
  finding: FindingOut;
  onJumpToAudio: (seconds: number) => void;
}

export function FindingCard({ callId, finding, onJumpToAudio }: FindingCardProps) {
  const [notes, setNotes] = useState("");
  const [correctedVerdict, setCorrectedVerdict] = useState<"pass" | "fail" | "na">(
    finding.current_verdict
  );
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: (body: Parameters<typeof reviewFinding>[1]) => reviewFinding(finding.id, body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["call", callId] }),
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
    </div>
  );
}
