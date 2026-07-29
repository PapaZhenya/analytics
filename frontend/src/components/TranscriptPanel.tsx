import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { SpeakerOut, UtteranceOut } from "@/api/calls";
import { correctSpeakerRole } from "@/api/calls";

interface TranscriptPanelProps {
  callId: string;
  utterances: UtteranceOut[];
  speakers: SpeakerOut[];
  currentTime: number;
  onSeek: (seconds: number) => void;
}

const SPEAKER_COLORS = ["#3b82f6", "#f97316", "#10b981", "#a855f7", "#ef4444", "#eab308"];
const ROLE_OPTIONS = ["agent", "client", "other", "unknown"];

// Not a calibrated probability — see the backend's Speaker.role_confidence docstring.
// Below this, the review UI flags the assignment as uncertain rather than presenting
// it as settled fact (product requirement: never claim perfect speaker identification).
const LOW_CONFIDENCE_THRESHOLD = 0.5;

function speakerColor(speakerId: string, speakers: SpeakerOut[]): string {
  const index = speakers.findIndex((s) => s.id === speakerId);
  return SPEAKER_COLORS[index % SPEAKER_COLORS.length] ?? "#64748b";
}

function highlightMatch(text: string, query: string) {
  if (!query) return text;
  const parts = text.split(new RegExp(`(${escapeRegExp(query)})`, "ig"));
  return parts.map((part, i) =>
    part.toLowerCase() === query.toLowerCase() ? (
      <mark key={i}>{part}</mark>
    ) : (
      <span key={i}>{part}</span>
    )
  );
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function SpeakerRoleChip({ callId, speaker }: { callId: string; speaker: SpeakerOut }) {
  const [pendingRole, setPendingRole] = useState(speaker.role_code);
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: (newRoleCode: string) => correctSpeakerRole(callId, speaker.id, newRoleCode),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["call", callId] }),
  });

  const isUncertain = speaker.role_confidence !== null && speaker.role_confidence < LOW_CONFIDENCE_THRESHOLD;

  return (
    <div className="speaker-role-chip">
      <span style={{ color: speakerColor(speaker.id, [speaker]) }}>
        {speaker.display_name ?? speaker.role_code}
      </span>
      {isUncertain && !speaker.role_manually_corrected && (
        <span className="uncertain-badge" title="Low-confidence role assignment — please verify">
          ⚠ uncertain
        </span>
      )}
      {speaker.role_manually_corrected && (
        <span className="corrected-badge" title="Manually corrected by a reviewer">confirmed</span>
      )}
      <select value={pendingRole} onChange={(e) => setPendingRole(e.target.value)}>
        {ROLE_OPTIONS.map((role) => (
          <option key={role} value={role}>{role}</option>
        ))}
      </select>
      <button
        disabled={mutation.isPending || pendingRole === speaker.role_code}
        onClick={() => mutation.mutate(pendingRole)}
      >
        Fix role
      </button>
    </div>
  );
}

export function TranscriptPanel({ callId, utterances, speakers, currentTime, onSeek }: TranscriptPanelProps) {
  const [search, setSearch] = useState("");

  const activeUtteranceId = useMemo(() => {
    const active = utterances.find(
      (u) => currentTime >= u.start_time && currentTime < u.end_time
    );
    return active?.id;
  }, [utterances, currentTime]);

  const speakerByI = (id: string) => speakers.find((s) => s.id === id);

  return (
    <div className="transcript-panel">
      <div className="speaker-role-summary">
        {speakers.map((speaker) => (
          <SpeakerRoleChip key={speaker.id} callId={callId} speaker={speaker} />
        ))}
      </div>

      <input
        placeholder="Search transcript..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      <div className="transcript-segments">
        {utterances.map((utterance) => {
          const speaker = speakerByI(utterance.speaker_id);
          const matches = search && utterance.content.toLowerCase().includes(search.toLowerCase());
          return (
            <div
              key={utterance.id}
              className={`transcript-segment ${utterance.id === activeUtteranceId ? "active" : ""} ${
                matches ? "search-match" : ""
              }`}
              onClick={() => onSeek(utterance.start_time)}
            >
              <span
                className="speaker-label"
                style={{ color: speakerColor(utterance.speaker_id, speakers) }}
              >
                {speaker?.display_name ?? speaker?.role_code ?? "Unknown"}
              </span>
              <span className="timestamp">{formatTime(utterance.start_time)}</span>
              {utterance.is_corrected && <span className="corrected-badge" title="Manually corrected">edited</span>}
              <p>{highlightMatch(utterance.content, search)}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}
