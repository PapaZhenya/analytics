import { apiClient, API_BASE_URL } from "@/api/client";

export type CallStatus =
  | "uploaded"
  | "queued"
  | "preprocessing"
  | "diarizing"
  | "transcribing"
  | "aligning"
  | "assigning_speakers"
  | "analyzing"
  | "completed"
  | "failed"
  | "cancelled";

export interface CallListItem {
  id: string;
  original_filename: string;
  status: CallStatus;
  source: string;
  agent_id: string | null;
  project_id: string;
  detected_language: string | null;
  duration_seconds: number | null;
  uploaded_at: string;
  processed_at: string | null;
}

export interface CallListResponse {
  items: CallListItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface CallListFilters {
  project_id?: string;
  agent_id?: string;
  status?: CallStatus;
  language?: string;
  source?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  page_size?: number;
}

export interface ProcessingStep {
  step_name: string;
  sequence: number;
  status: "pending" | "running" | "succeeded" | "failed" | "skipped";
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
}

export interface CallStatusResponse {
  call_id: string;
  status: CallStatus;
  steps: ProcessingStep[];
  percent_complete: number;
}

export interface SpeakerOut {
  id: string;
  diarization_label: string;
  role_code: string;
  display_name: string | null;
  // Heuristic confidence tier, not a calibrated probability — see the backend's
  // Speaker.role_confidence docstring. null means role assignment hasn't run yet.
  role_confidence: number | null;
  role_manually_corrected: boolean;
}

export interface UtteranceOut {
  id: string;
  speaker_id: string;
  sequence: number;
  start_time: number;
  end_time: number;
  content: string;
  original_content: string;
  is_corrected: boolean;
  sentiment: "Neutral" | "Positive" | "Negative" | null;
  is_profane: boolean;
}

export interface EvidenceOut {
  id: string;
  utterance_id: string | null;
  start_time: number;
  end_time: number;
  quote_text: string;
  evidence_type: "violation" | "positive";
  added_by: string | null;
}

export interface FindingOut {
  id: string;
  criterion_id: string;
  criterion_code: string;
  criterion_text: string;
  ai_verdict: "pass" | "fail" | "na";
  ai_confidence: number | null;
  ai_explanation: string | null;
  current_verdict: "pass" | "fail" | "na";
  human_corrected: boolean;
  reviewed_by: string | null;
  notes: string | null;
  evidence: EvidenceOut[];
}

export interface QAEvaluationOut {
  id: string;
  scorecard_id: string;
  overall_score: number | null;
  max_score: number | null;
  status: string;
  findings: FindingOut[];
}

export interface CommentOut {
  id: string;
  utterance_id: string | null;
  user_id: string;
  body: string;
  parent_comment_id: string | null;
  created_at: string;
}

export interface CallDetail {
  id: string;
  original_filename: string;
  status: CallStatus;
  source: string;
  detected_language: string | null;
  duration_seconds: number | null;
  uploaded_at: string;
  processed_at: string | null;
  speakers: SpeakerOut[];
  utterances: UtteranceOut[];
  evaluations: QAEvaluationOut[];
  comments: CommentOut[];
  tags: string[];
}

export async function listCalls(filters: CallListFilters): Promise<CallListResponse> {
  const response = await apiClient.get<CallListResponse>("/calls", { params: filters });
  return response.data;
}

export async function getCallDetail(callId: string): Promise<CallDetail> {
  const response = await apiClient.get<CallDetail>(`/calls/${callId}`);
  return response.data;
}

export async function getCallStatus(callId: string): Promise<CallStatusResponse> {
  const response = await apiClient.get<CallStatusResponse>(`/calls/${callId}/status`);
  return response.data;
}

export function callAudioUrl(callId: string): string {
  return `${API_BASE_URL}/calls/${callId}/audio`;
}

export async function uploadCalls(
  projectId: string,
  files: File[],
  agentId?: string,
  onProgress?: (percent: number) => void
): Promise<CallListItem[]> {
  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));

  const response = await apiClient.post<CallListItem[]>("/calls", formData, {
    params: { project_id: projectId, agent_id: agentId },
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress: (event) => {
      if (onProgress && event.total) {
        onProgress(Math.round((event.loaded * 100) / event.total));
      }
    },
  });
  return response.data;
}

export async function reprocessCall(callId: string): Promise<void> {
  await apiClient.post(`/calls/${callId}/reprocess`);
}

export async function cancelCall(callId: string): Promise<void> {
  await apiClient.post(`/calls/${callId}/cancel`);
}

export async function correctUtterance(
  callId: string,
  utteranceId: string,
  body: { corrected_content?: string; corrected_speaker_id?: string; reason?: string }
): Promise<void> {
  await apiClient.post(`/calls/${callId}/utterances/${utteranceId}/correct`, body);
}

export async function correctSpeakerRole(
  callId: string,
  speakerId: string,
  newRoleCode: string,
  reason?: string
): Promise<void> {
  await apiClient.post(`/calls/${callId}/speakers/${speakerId}/correct-role`, {
    new_role_code: newRoleCode,
    reason,
  });
}

export async function listComments(callId: string): Promise<CommentOut[]> {
  const response = await apiClient.get<CommentOut[]>(`/calls/${callId}/comments`);
  return response.data;
}

export async function createComment(
  callId: string,
  body: { body: string; utterance_id?: string; parent_comment_id?: string }
): Promise<CommentOut> {
  const response = await apiClient.post<CommentOut>(`/calls/${callId}/comments`, body);
  return response.data;
}
