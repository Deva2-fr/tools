export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T = unknown>(path: string, method = "GET", body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Requested-With": "deva2" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError(res.status, await errorText(res));
  if (res.status === 204) return undefined as T;
  return res.json();
}

async function errorText(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) return data.detail.map((d: { msg: string }) => d.msg).join(", ");
  } catch {
    /* pas de JSON */
  }
  return `Erreur ${res.status}`;
}

export async function apiUpload<T = unknown>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-Requested-With": "deva2" },
    body: form,
  });
  if (!res.ok) throw new ApiError(res.status, await errorText(res));
  return res.json();
}

/** Télécharge un fichier protégé (CSV, PDF…) en envoyant l'en-tête de sécurité. */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const res = await fetch(`/api${path}`, { credentials: "same-origin", headers: { "X-Requested-With": "deva2" } });
  if (!res.ok) throw new ApiError(res.status, await errorText(res));
  const a = document.createElement("a");
  a.href = URL.createObjectURL(await res.blob());
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

/** Ouvre un PDF protégé dans un nouvel onglet. */
export async function openPdf(path: string): Promise<void> {
  const res = await fetch(`/api${path}`, { credentials: "same-origin", headers: { "X-Requested-With": "deva2" } });
  if (!res.ok) throw new ApiError(res.status, await errorText(res));
  window.open(URL.createObjectURL(await res.blob()), "_blank", "noopener");
}

/** Envoie un formulaire (JSON ou FormData, pour joindre un fichier) et télécharge le PDF renvoyé. */
export async function postForPdf(path: string, body: unknown): Promise<{ id: number; filename: string; drive: string }> {
  const isForm = body instanceof FormData;
  const res = await fetch(`/api${path}`, {
    method: "POST",
    credentials: "same-origin",
    headers: isForm ? { "X-Requested-With": "deva2" } : { "Content-Type": "application/json", "X-Requested-With": "deva2" },
    body: isForm ? body : JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError(res.status, await errorText(res));
  const blob = await res.blob();
  const filename = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? "note-de-frais.pdf";
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
  return { id: Number(res.headers.get("X-Expense-Id")), filename, drive: decodeURIComponent(res.headers.get("X-Drive-Status") ?? "") };
}

// ---------- types ----------
export interface User { id: number; email: string; name: string; role: "admin" | "manager" | "member"; totp_enabled: boolean; tours_done?: boolean }
export const isManager = (u: User) => u.role === "admin" || u.role === "manager";
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Row = Record<string, any> & { id: number };
export interface Server { id: number; project_id: number; label: string; provider: string; hostname: string; ip: string; os: string; location: string; specs: string; access_info: string; notes: string }
export interface Tech { id: number; project_id: number; name: string; version: string; category: string; watch_cve: boolean; last_scanned_at: string | null }
export interface Project {
  id: number; name: string; url: string; description: string; environment: "prod" | "staging" | "dev";
  repo_url: string; monitoring_tools: string; notes: string; monitoring_enabled: boolean; public_status: boolean; check_interval_min: number;
  expected_status: number | null; status: "up" | "down" | "unknown"; last_checked_at: string | null;
  last_latency_ms: number | null; ssl_expires_at: string | null; missing_headers: string[];
  servers: Server[]; technologies: Tech[]; open_vulnerabilities: number;
}
export interface Check { ts: string; ok: boolean; status_code: number | null; latency_ms: number | null; error: string; ssl_days_left: number | null }
export interface Vuln { id: number; project_id: number; cve_id: string; cvss: number | null; summary: string; exploited: boolean; published_at: string | null; dismissed: boolean; tech_name: string; tech_version: string; project_name: string }
export interface Alert { id: number; project_id: number | null; kind: string; severity: "info" | "warning" | "critical"; title: string; message: string; acknowledged: boolean; delivery: string; created_at: string }
export interface Channel { id: number; name: string; type: string; min_severity: string; enabled: boolean; config_keys: string[] }
export interface Mail { id: number; mailbox_id: number | null; subject: string; sender_name: string; sender_email: string; preview: string; web_link: string; received_at: string; is_read: boolean; tag: string }
export interface Expense { id: number; expense_date: string; employee: string; reason: string; category: string; project: string; payment_method: string; amount_ttc: number; vat_rate: number; amount_ht: number; amount_vat: number; notes: string; has_pdf: boolean; drive_link: string; user_id: number | null; signature_id: number | null; president_signature_id: number | null; partner_signature_id: number | null; receipt_files: { id: number; name: string }[] }
export interface Tax { id: number; title: string; category: string; due_date: string; amount: number | null; recurrence: string; reminder_days: string; notes: string; status: "todo" | "paid"; days_left: number }
export interface Field { key: string; label: string; group: string; help: string; secret: boolean; multiline: boolean; is_set: boolean; value: string }
export interface DirectoryUser { id: number; name: string; email: string }
export interface SignatureRow { id: number; user_id: number; name: string; created_at: string }
export interface Signers { president: { id: number; name: string } | null; partner: { id: number; name: string } | null }
