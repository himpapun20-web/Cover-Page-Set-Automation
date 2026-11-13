export type Session = { authenticated: boolean; auth_mode?: string; login_url?: string; user?: { id: string; name: string; email: string; role: string } };
export type Row = Record<string, unknown> & { id: string; created_at?: string; updated_at?: string };
export type ListResult = { items: Row[]; limit: number; offset: number };
export type ProjectReportData = { project: Row; company_name: string; pipe_section_count: number };
export type DashboardData = {
  totals: { projects: number; pipe_sections: number };
  pipe_sections_by_status: Record<string, number>;
  projects: Array<{ id: string; project_code: string; project_name: string; client_name?: string; location?: string; status: string; report_status: string; pipe_section_count: number; report_date?: string }>;
};
export type WinCanPipeRow = {
  pipe_id: string;
  section_reference: string | null;
  start_manhole: string | null;
  finish_manhole: string | null;
  function_description: string | null;
  survey_length_m: string;
  pipe_size_mm: string | null;
  pipe_material_code: string | null;
  condition_grade: string | null;
  defects_summary: string | null;
  site_environment: string | null;
  remarks: string | null;
  recommendation: string | null;
};
export type WinCanPreview = { page_count: number; rows: WinCanPipeRow[]; text_preview: string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  const response = await fetch(path, { credentials: 'include', ...init, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    const message = Array.isArray(payload.detail) ? payload.detail.map((item: { msg?: string }) => item.msg).join('; ') : payload.detail;
    throw new Error(String(message || `HTTP ${response.status}`));
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  session: () => request<Session>('/api/auth/session'),
  passwordLogin: (email: string, password: string) => request<void>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  passwordSignup: (invite_code: string, full_name: string, email: string, password: string) => request<void>('/api/auth/signup', { method: 'POST', body: JSON.stringify({ invite_code, full_name, email, password }) }),
  createSignupInvitation: () => request<{ code: string; expires_at: string }>('/api/auth/invitations', { method: 'POST', body: JSON.stringify({}) }),
  setUserPassword: (userId: string, password: string) => request<void>(`/api/auth/users/${userId}/password`, { method: 'PUT', body: JSON.stringify({ password }) }),
  dashboard: () => request<DashboardData>('/api/dashboard'),
  list: (resource: string) => request<ListResult>(`/api/${resource}?limit=200`),
  reportData: (projectId: string) => request<ProjectReportData>(`/api/projects/${projectId}/report-data`),
  projectSitePlans: (projectId: string) => request<{ items: Row[] }>(`/api/projects/${projectId}/site-plans`),
  uploadSitePlan: (projectId: string, file: File) => {
    const body = new FormData();
    body.append('file', file);
    return request<Row>(`/api/projects/${projectId}/site-plans`, { method: 'POST', body });
  },
  previewWincanReport: (projectId: string, file: File) => {
    const body = new FormData();
    body.append('file', file);
    return request<WinCanPreview>(`/api/projects/${projectId}/wincan-report/preview`, { method: 'POST', body });
  },
  applyWincanReport: (projectId: string, rows: WinCanPipeRow[]) => request<{ count: number; created: number; updated: number }>(`/api/projects/${projectId}/wincan-report`, { method: 'POST', body: JSON.stringify({ rows }) }),
  create: (resource: string, data: Record<string, unknown>) => request<Row>(`/api/${resource}`, { method: 'POST', body: JSON.stringify(data) }),
  update: (resource: string, id: string, data: Record<string, unknown>) => request<Row>(`/api/${resource}/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  remove: (resource: string, id: string) => request<void>(`/api/${resource}/${id}`, { method: 'DELETE' }),
};
