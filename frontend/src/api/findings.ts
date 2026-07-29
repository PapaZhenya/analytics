import { apiClient } from "@/api/client";

export type ReviewActionType =
  | "confirm"
  | "reject"
  | "correct"
  | "add_evidence"
  | "remove_evidence"
  | "reopen";

export interface ReviewActionRequest {
  action: ReviewActionType;
  new_verdict?: "pass" | "fail" | "na";
  notes?: string;
  evidence?: {
    utterance_id?: string;
    start_time: number;
    end_time: number;
    quote_text: string;
    evidence_type: "violation" | "positive";
  };
  evidence_id?: string;
}

export interface ReviewActionResponse {
  finding_id: string;
  current_verdict: "pass" | "fail" | "na";
  human_corrected: boolean;
}

export async function reviewFinding(
  findingId: string,
  body: ReviewActionRequest
): Promise<ReviewActionResponse> {
  const response = await apiClient.post<ReviewActionResponse>(
    `/findings/${findingId}/review`,
    body
  );
  return response.data;
}
