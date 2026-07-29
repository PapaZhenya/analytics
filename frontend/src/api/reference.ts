import { apiClient } from "@/api/client";

export interface Project {
  id: string;
  name: string;
  description: string | null;
}

export interface Team {
  id: string;
  project_id: string;
  department_id: string | null;
  name: string;
}

export async function listProjects(): Promise<Project[]> {
  const response = await apiClient.get<Project[]>("/projects");
  return response.data;
}

export async function listTeams(projectId?: string): Promise<Team[]> {
  const response = await apiClient.get<Team[]>("/teams", { params: { project_id: projectId } });
  return response.data;
}
