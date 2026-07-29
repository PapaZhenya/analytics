import type { EvidenceOut } from "@/api/calls";

interface EvidenceChipProps {
  evidence: EvidenceOut;
  onJump: (seconds: number) => void;
  onRemove?: (evidenceId: string) => void;
}

export function EvidenceChip({ evidence, onJump, onRemove }: EvidenceChipProps) {
  return (
    <div className={`evidence-chip evidence-${evidence.evidence_type}`}>
      <button className="jump-to-audio" onClick={() => onJump(evidence.start_time)}>
        ▶ {formatTime(evidence.start_time)}
      </button>
      <span className="quote">&ldquo;{evidence.quote_text}&rdquo;</span>
      {onRemove && (
        <button className="remove-evidence" onClick={() => onRemove(evidence.id)} title="Remove evidence">
          ×
        </button>
      )}
    </div>
  );
}

function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}
