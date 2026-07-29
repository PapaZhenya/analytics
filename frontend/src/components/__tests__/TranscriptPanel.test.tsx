import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { TranscriptPanel } from "@/components/TranscriptPanel";
import type { SpeakerOut, UtteranceOut } from "@/api/calls";

const speakers: SpeakerOut[] = [
  {
    id: "s1", diarization_label: "Speaker 0", role_code: "agent", display_name: "Agent",
    role_confidence: 0.85, role_manually_corrected: false,
  },
  {
    id: "s2", diarization_label: "Speaker 1", role_code: "client", display_name: "Client",
    role_confidence: 0.85, role_manually_corrected: false,
  },
];

const utterances: UtteranceOut[] = [
  {
    id: "u1", speaker_id: "s1", sequence: 0, start_time: 0, end_time: 5,
    content: "Thank you for calling.", original_content: "Thank you for calling.",
    is_corrected: false, sentiment: "Neutral", is_profane: false,
  },
  {
    id: "u2", speaker_id: "s2", sequence: 1, start_time: 5, end_time: 10,
    content: "I have a billing question.", original_content: "I have a billing question.",
    is_corrected: false, sentiment: "Neutral", is_profane: false,
  },
];

function renderWithQueryClient(ui: React.ReactElement) {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  );
}

describe("TranscriptPanel", () => {
  it("marks the segment matching currentTime as active", () => {
    renderWithQueryClient(
      <TranscriptPanel callId="call-1" utterances={utterances} speakers={speakers} currentTime={6} onSeek={vi.fn()} />
    );

    const secondSegment = screen.getByText("I have a billing question.").closest(".transcript-segment");
    const firstSegment = screen.getByText("Thank you for calling.").closest(".transcript-segment");

    expect(secondSegment).toHaveClass("active");
    expect(firstSegment).not.toHaveClass("active");
  });

  it("calls onSeek with the segment's start_time when clicked (evidence jump-to-audio behavior)", () => {
    const onSeek = vi.fn();
    renderWithQueryClient(
      <TranscriptPanel callId="call-1" utterances={utterances} speakers={speakers} currentTime={0} onSeek={onSeek} />
    );

    fireEvent.click(screen.getByText("I have a billing question."));

    expect(onSeek).toHaveBeenCalledWith(5);
  });

  it("highlights text matching the search query", () => {
    renderWithQueryClient(
      <TranscriptPanel callId="call-1" utterances={utterances} speakers={speakers} currentTime={0} onSeek={vi.fn()} />
    );

    fireEvent.change(screen.getByPlaceholderText("Search transcript..."), {
      target: { value: "billing" },
    });

    expect(screen.getByText("billing", { selector: "mark" })).toBeInTheDocument();
  });

  it("flags a low-confidence role assignment as uncertain rather than presenting it as fact", () => {
    const uncertainSpeakers: SpeakerOut[] = [
      { ...speakers[0], role_confidence: 0.3 },
      speakers[1],
    ];
    renderWithQueryClient(
      <TranscriptPanel callId="call-1" utterances={utterances} speakers={uncertainSpeakers} currentTime={0} onSeek={vi.fn()} />
    );

    expect(screen.getByText("⚠ uncertain")).toBeInTheDocument();
  });
});
