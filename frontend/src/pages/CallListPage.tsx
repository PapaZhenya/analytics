import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listCalls, type CallListFilters, type CallStatus } from "@/api/calls";
import { listProjects } from "@/api/reference";
import { CallStatusBadge } from "@/components/CallStatusBadge";

const STATUS_OPTIONS: CallStatus[] = [
  "uploaded", "queued", "preprocessing", "diarizing", "transcribing", "aligning",
  "assigning_speakers", "analyzing", "completed", "failed", "cancelled",
];

export function CallListPage() {
  const [filters, setFilters] = useState<CallListFilters>({ page: 1, page_size: 25 });
  const [search, setSearch] = useState("");

  const { data: projects } = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const { data, isLoading } = useQuery({
    queryKey: ["calls", filters],
    queryFn: () => listCalls(filters),
    refetchInterval: 5000, // cheap way to keep statuses fresh while calls are processing
  });

  const filteredItems = search
    ? data?.items.filter((c) => c.original_filename.toLowerCase().includes(search.toLowerCase()))
    : data?.items;

  return (
    <div className="call-list-page">
      <header>
        <h1>Calls</h1>
        <Link to="/upload" className="button">Upload Calls</Link>
      </header>

      <div className="filters">
        <input
          placeholder="Search by filename..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          value={filters.project_id ?? ""}
          onChange={(e) =>
            setFilters((f) => ({ ...f, project_id: e.target.value || undefined, page: 1 }))
          }
        >
          <option value="">All projects</option>
          {projects?.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        <select
          value={filters.status ?? ""}
          onChange={(e) =>
            setFilters((f) => ({ ...f, status: (e.target.value || undefined) as CallStatus | undefined, page: 1 }))
          }
        >
          <option value="">All statuses</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <input
          type="date"
          value={filters.date_from?.slice(0, 10) ?? ""}
          onChange={(e) =>
            setFilters((f) => ({ ...f, date_from: e.target.value || undefined, page: 1 }))
          }
        />
        <input
          type="date"
          value={filters.date_to?.slice(0, 10) ?? ""}
          onChange={(e) =>
            setFilters((f) => ({ ...f, date_to: e.target.value || undefined, page: 1 }))
          }
        />
      </div>

      {isLoading && <p>Loading...</p>}

      {!isLoading && (
        <table className="call-list-table">
          <thead>
            <tr>
              <th>Filename</th>
              <th>Status</th>
              <th>Language</th>
              <th>Source</th>
              <th>Duration</th>
              <th>Uploaded</th>
              <th>Processed</th>
            </tr>
          </thead>
          <tbody>
            {filteredItems?.map((call) => (
              <tr key={call.id}>
                <td>
                  <Link to={`/calls/${call.id}`}>{call.original_filename}</Link>
                </td>
                <td><CallStatusBadge status={call.status} /></td>
                <td>{call.detected_language ?? "—"}</td>
                <td>{call.source}</td>
                <td>{call.duration_seconds ? `${Math.round(call.duration_seconds)}s` : "—"}</td>
                <td>{new Date(call.uploaded_at).toLocaleString()}</td>
                <td>{call.processed_at ? new Date(call.processed_at).toLocaleString() : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {data && (
        <div className="pagination">
          <button
            disabled={(filters.page ?? 1) <= 1}
            onClick={() => setFilters((f) => ({ ...f, page: (f.page ?? 1) - 1 }))}
          >
            Previous
          </button>
          <span>
            Page {data.page} of {Math.max(1, Math.ceil(data.total / data.page_size))} ({data.total} total)
          </span>
          <button
            disabled={(filters.page ?? 1) * (filters.page_size ?? 25) >= data.total}
            onClick={() => setFilters((f) => ({ ...f, page: (f.page ?? 1) + 1 }))}
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
