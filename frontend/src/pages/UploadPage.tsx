import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listProjects } from "@/api/reference";
import { uploadCalls } from "@/api/calls";
import { UploadDropzone } from "@/components/UploadDropzone";

interface PendingFile {
  file: File;
  progress: number;
  status: "pending" | "uploading" | "done" | "error";
  error?: string;
}

export function UploadPage() {
  const navigate = useNavigate();
  const { data: projects } = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const [projectId, setProjectId] = useState<string>("");
  const [pendingFiles, setPendingFiles] = useState<PendingFile[]>([]);

  function handleFilesSelected(files: File[]) {
    setPendingFiles((prev) => [
      ...prev,
      ...files.map((file) => ({ file, progress: 0, status: "pending" as const })),
    ]);
  }

  async function handleUploadAll() {
    if (!projectId) return;

    const filesToUpload = pendingFiles.filter((f) => f.status === "pending");
    if (filesToUpload.length === 0) return;

    setPendingFiles((prev) =>
      prev.map((f) => (f.status === "pending" ? { ...f, status: "uploading" } : f))
    );

    try {
      await uploadCalls(
        projectId,
        filesToUpload.map((f) => f.file),
        undefined,
        (percent) =>
          setPendingFiles((prev) =>
            prev.map((f) => (f.status === "uploading" ? { ...f, progress: percent } : f))
          )
      );
      setPendingFiles((prev) =>
        prev.map((f) => (f.status === "uploading" ? { ...f, status: "done", progress: 100 } : f))
      );
    } catch (err) {
      setPendingFiles((prev) =>
        prev.map((f) =>
          f.status === "uploading"
            ? { ...f, status: "error", error: "Upload failed" }
            : f
        )
      );
    }
  }

  return (
    <div className="upload-page">
      <h1>Upload Call Recordings</h1>

      <label>
        Project
        <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
          <option value="">Select a project...</option>
          {projects?.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </label>

      <UploadDropzone onFilesSelected={handleFilesSelected} />

      {pendingFiles.length > 0 && (
        <ul className="pending-files">
          {pendingFiles.map((pf, idx) => (
            <li key={idx}>
              <span>{pf.file.name}</span>
              <span>{pf.status === "error" ? pf.error : `${pf.progress}%`}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="actions">
        <button
          onClick={handleUploadAll}
          disabled={!projectId || pendingFiles.every((f) => f.status !== "pending")}
        >
          Upload
        </button>
        <button onClick={() => navigate("/calls")}>Done — go to calls</button>
      </div>
    </div>
  );
}
