import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";

export interface AudioPlayerHandle {
  seekTo: (seconds: number) => void;
}

interface AudioPlayerProps {
  src: string;
  onTimeUpdate?: (seconds: number) => void;
}

const PLAYBACK_RATES = [0.5, 0.75, 1, 1.25, 1.5, 2];

export const AudioPlayer = forwardRef<AudioPlayerHandle, AudioPlayerProps>(
  ({ src, onTimeUpdate }, ref) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const wavesurferRef = useRef<WaveSurfer | null>(null);
    const [isPlaying, setIsPlaying] = useState(false);
    const [currentTime, setCurrentTime] = useState(0);
    const [duration, setDuration] = useState(0);
    const [playbackRate, setPlaybackRate] = useState(1);

    useEffect(() => {
      if (!containerRef.current) return;

      const wavesurfer = WaveSurfer.create({
        container: containerRef.current,
        waveColor: "#94a3b8",
        progressColor: "#3b82f6",
        height: 80,
        url: src,
      });
      wavesurferRef.current = wavesurfer;

      wavesurfer.on("ready", () => setDuration(wavesurfer.getDuration()));
      wavesurfer.on("play", () => setIsPlaying(true));
      wavesurfer.on("pause", () => setIsPlaying(false));
      wavesurfer.on("timeupdate", (time) => {
        setCurrentTime(time);
        onTimeUpdate?.(time);
      });

      return () => wavesurfer.destroy();
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [src]);

    useImperativeHandle(ref, () => ({
      seekTo: (seconds: number) => {
        const wavesurfer = wavesurferRef.current;
        if (!wavesurfer || duration === 0) return;
        wavesurfer.seekTo(Math.min(seconds / duration, 1));
        wavesurfer.play();
      },
    }));

    return (
      <div className="audio-player">
        <div ref={containerRef} />
        <div className="controls">
          <button onClick={() => wavesurferRef.current?.playPause()}>
            {isPlaying ? "Pause" : "Play"}
          </button>
          <span className="time">
            {formatTime(currentTime)} / {formatTime(duration)}
          </span>
          <label>
            Speed
            <select
              value={playbackRate}
              onChange={(e) => {
                const rate = Number(e.target.value);
                setPlaybackRate(rate);
                wavesurferRef.current?.setPlaybackRate(rate);
              }}
            >
              {PLAYBACK_RATES.map((rate) => (
                <option key={rate} value={rate}>{rate}x</option>
              ))}
            </select>
          </label>
        </div>
      </div>
    );
  }
);

AudioPlayer.displayName = "AudioPlayer";

function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}
