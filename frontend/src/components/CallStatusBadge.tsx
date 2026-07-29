import type { CallStatus } from "@/api/calls";

const STATUS_LABELS: Record<CallStatus, string> = {
  uploaded: "Uploaded",
  queued: "Queued",
  preprocessing: "Preprocessing",
  diarizing: "Diarizing",
  transcribing: "Transcribing",
  aligning: "Aligning",
  assigning_speakers: "Assigning Speakers",
  analyzing: "Analyzing",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

const STATUS_COLORS: Record<CallStatus, string> = {
  uploaded: "#94a3b8",
  queued: "#94a3b8",
  preprocessing: "#3b82f6",
  diarizing: "#3b82f6",
  transcribing: "#3b82f6",
  aligning: "#3b82f6",
  assigning_speakers: "#3b82f6",
  analyzing: "#8b5cf6",
  completed: "#22c55e",
  failed: "#ef4444",
  cancelled: "#64748b",
};

export function CallStatusBadge({ status }: { status: CallStatus }) {
  return (
    <span
      className="status-badge"
      style={{
        backgroundColor: `${STATUS_COLORS[status]}22`,
        color: STATUS_COLORS[status],
        border: `1px solid ${STATUS_COLORS[status]}55`,
      }}
    >
      {STATUS_LABELS[status]}
    </span>
  );
}
