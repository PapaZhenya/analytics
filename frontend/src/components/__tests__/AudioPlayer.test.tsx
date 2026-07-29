import { createRef } from "react";
import { act, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AudioPlayer, type AudioPlayerHandle } from "@/components/AudioPlayer";

const mockInstance = {
  on: vi.fn(),
  destroy: vi.fn(),
  getDuration: vi.fn(() => 100),
  seekTo: vi.fn(),
  play: vi.fn(),
  playPause: vi.fn(),
  setPlaybackRate: vi.fn(),
};

vi.mock("wavesurfer.js", () => ({
  default: { create: vi.fn(() => mockInstance) },
}));

describe("AudioPlayer", () => {
  it("seeks the underlying wavesurfer instance and plays when seekTo is called via ref", () => {
    const ref = createRef<AudioPlayerHandle>();
    render(<AudioPlayer ref={ref} src="https://example.com/call.mp3" />);

    // Simulate wavesurfer having already fired "ready" so duration is known — the
    // component derives seek position as a fraction of duration. Wrapped in act()
    // because it triggers a React state update (setDuration) that must flush before
    // the imperative handle closes over the new value.
    const readyHandler = mockInstance.on.mock.calls.find(([event]) => event === "ready")?.[1];
    act(() => {
      readyHandler?.();
    });

    ref.current?.seekTo(50); // clicking a piece of evidence at t=50s

    expect(mockInstance.seekTo).toHaveBeenCalledWith(0.5);
    expect(mockInstance.play).toHaveBeenCalled();
  });

  it("does nothing if duration is not yet known (avoids seeking to NaN)", () => {
    mockInstance.getDuration.mockReturnValueOnce(0);
    const ref = createRef<AudioPlayerHandle>();
    render(<AudioPlayer ref={ref} src="https://example.com/call.mp3" />);

    mockInstance.seekTo.mockClear();
    ref.current?.seekTo(10);

    expect(mockInstance.seekTo).not.toHaveBeenCalled();
  });
});
