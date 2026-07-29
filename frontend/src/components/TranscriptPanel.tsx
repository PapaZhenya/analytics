import { useMemo, useState } from "react";
import type { SpeakerOut, UtteranceOut } from "@/api/calls";

interface TranscriptPanelProps {
  utterances: UtteranceOut[];
  speakers: SpeakerOut[];
  currentTime: number;
  onSeek: (seconds: number) => void;
}

const SPEAKER_COLORS = ["#3b82f6", "#f97316", "#10b981", "#a855f7", "#ef4444", "#eab308"];

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

export function TranscriptPanel({ utterances, speakers, currentTime, onSeek }: TranscriptPanelProps) {
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
