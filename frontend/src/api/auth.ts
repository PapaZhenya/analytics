import { apiClient } from "@/api/client";
import type { CurrentUser } from "@/auth/useAuthStore";

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const response = await apiClient.post<TokenResponse>("/auth/login", { email, password });
  return response.data;
}

export async function fetchCurrentUser(): Promise<CurrentUser> {
  const response = await apiClient.get<CurrentUser>("/auth/me");
  return response.data;
}

export async function logout(): Promise<void> {
  await apiClient.post("/auth/logout");
}

export async function refresh(): Promise<TokenResponse> {
  const response = await apiClient.post<TokenResponse>("/auth/refresh");
  return response.data;
}
