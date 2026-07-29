import type { CallDetail } from "@/api/calls";

/** Surfaces uploaded-file identity, processing metadata, and model versions — section
 * 8 requires these stay "explainable", not just stored in the database. Collapsed by
 * default since it's forensic detail, not the primary review workflow. */
export function CallInfoPanel({ call }: { call: CallDetail }) {
  return (
    <details className="call-info-panel">
      <summary>Call details &amp; processing metadata</summary>
      <dl>
        <dt>File checksum (SHA-256)</dt>
        <dd title={call.checksum}>{call.checksum.slice(0, 16)}...</dd>

        <dt>Channels</dt>
        <dd>
          {call.channel_count ?? "not yet inspected"}
          {call.is_separate_channel_recording === true && " (likely separate per-speaker channels)"}
          {call.is_separate_channel_recording === false && call.channel_count === 2 && " (mixed stereo)"}
        </dd>

        <dt>Model versions used</dt>
        <dd>
          {Object.keys(call.model_versions).length === 0 ? (
            "not yet recorded"
          ) : (
            <ul className="model-versions-list">
              {Object.entries(call.model_versions).map(([stage, version]) => (
                <li key={stage}>
                  <strong>{stage}:</strong> {version}
                </li>
              ))}
            </ul>
          )}
        </dd>
      </dl>
    </details>
  );
}
