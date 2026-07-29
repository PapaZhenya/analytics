import { useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getCallDetail, getCallStatus, callAudioUrl } from "@/api/calls";
import { AudioPlayer, type AudioPlayerHandle } from "@/components/AudioPlayer";
import { TranscriptPanel } from "@/components/TranscriptPanel";
import { QAScorePanel } from "@/components/QAScorePanel";
import { FindingCard } from "@/components/FindingCard";
import { CommentThread } from "@/components/CommentThread";
import { CallStatusBadge } from "@/components/CallStatusBadge";

export function CallReviewPage() {
  const { callId } = useParams<{ callId: string }>();
  const [currentTime, setCurrentTime] = useState(0);
  const audioPlayerRef = useRef<AudioPlayerHandle>(null);

  const { data: call, isLoading } = useQuery({
    queryKey: ["call", callId],
    queryFn: () => getCallDetail(callId!),
    enabled: !!callId,
  });

  const { data: statusData } = useQuery({
    queryKey: ["call-status", callId],
    queryFn: () => getCallStatus(callId!),
    enabled: !!callId && call?.status !== "completed" && call?.status !== "failed",
    refetchInterval: 3000,
  });

  function handleSeek(seconds: number) {
    audioPlayerRef.current?.seekTo(seconds);
  }

  if (isLoading || !call) return <p>Loading call...</p>;

  const isStillProcessing = call.status !== "completed" && call.status !== "failed" && call.status !== "cancelled";

  return (
    <div className="call-review-page">
      <header>
        <h1>{call.original_filename}</h1>
        <CallStatusBadge status={call.status} />
        {call.tags.map((tag) => (
          <span key={tag} className="tag">{tag}</span>
        ))}
      </header>

      {isStillProcessing && statusData && (
        <div className="processing-banner">
          Processing: {statusData.percent_complete}% complete
          <progress value={statusData.percent_complete} max={100} />
        </div>
      )}

      {call.status === "failed" && (
        <div className="error-banner">
          This call failed to process.{" "}
          {statusData?.steps.find((s) => s.status === "failed")?.error_message}
        </div>
      )}

      {call.utterances.length > 0 && (
        <AudioPlayer ref={audioPlayerRef} src={callAudioUrl(call.id)} onTimeUpdate={setCurrentTime} />
      )}

      <div className="review-layout">
        <TranscriptPanel
          utterances={call.utterances}
          speakers={call.speakers}
          currentTime={currentTime}
          onSeek={handleSeek}
        />

        <aside className="review-sidebar">
          {call.evaluations.map((evaluation) => (
            <div key={evaluation.id}>
              <QAScorePanel evaluation={evaluation} />
              {evaluation.findings.map((finding) => (
                <FindingCard
                  key={finding.id}
                  callId={call.id}
                  finding={finding}
                  onJumpToAudio={handleSeek}
                />
              ))}
            </div>
          ))}

          <CommentThread callId={call.id} comments={call.comments} />
        </aside>
      </div>
    </div>
  );
}
