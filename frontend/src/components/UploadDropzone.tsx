import { useRef, useState } from "react";

interface UploadDropzoneProps {
  onFilesSelected: (files: File[]) => void;
  accept?: string;
}

export function UploadDropzone({ onFilesSelected, accept = ".mp3,.wav,.flac,.m4a,.ogg" }: UploadDropzoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setIsDragging(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) onFilesSelected(files);
  }

  return (
    <div
      className={`upload-dropzone ${isDragging ? "dragging" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
      onClick={() => inputRef.current?.click()}
      role="button"
      tabIndex={0}
    >
      <p>Drag and drop call recordings here, or click to browse.</p>
      <p className="hint">Supported: {accept}</p>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={accept}
        style={{ display: "none" }}
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length > 0) onFilesSelected(files);
          e.target.value = "";
        }}
      />
    </div>
  );
}
