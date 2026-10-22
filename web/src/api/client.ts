import { getAccessToken } from '../auth/keycloak';
import type {
  AdminUser,
  AllocationChange,
  AllocationResponse,
  AuditEntry,
  AuditQuery,
  AutoAllocateResult,
  Cycle,
  ExportKind,
  ExportVersion,
  FileKind,
  FileRecord,
  ForecastResponse,
  ForecastRevision,
  ForecastRevisionDetail,
  SaveResult,
  UploadResult,
  HealthReport,
  InventoryResponse,
  Me,
  Product,
  QtyChange,
  Region,
  RowError,
  RuleConfig,
  RuleInfo,
  Summary,
  Transfer,
  Violation,
} from './types';

const API_BASE = (import.meta.env.VITE_API_BASE || '/api').replace(/\/$/, '');

export class ApiError extends Error {
  readonly status: number;
  readonly violations: Violation[];
  readonly errors: RowError[];

  constructor(status: number, message: string, violations: Violation[] = [], errors: RowError[] = []) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.violations = violations;
    this.errors = errors;
  }
}

const STATUS_TEXT: Record<number, string> = {
  401: 'Your session is not valid. Please sign in again.',
  403: 'You are not allowed to do this (role or region).',
  409: 'Not allowed at the current stage or status.',
  422: 'Validation failed.',
  503: 'A dependency (rules or file service) is unavailable.',
};

type Query = Record<string, string | number | undefined | null>;

function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams();
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== '') params.set(k, String(v));
    }
  }
  const qs = params.toString();
  return `${API_BASE}${path}${qs ? `?${qs}` : ''}`;
}

async function toApiError(res: Response): Promise<ApiError> {
  let message = STATUS_TEXT[res.status] ?? `Request failed (${res.status})`;
  let violations: Violation[] = [];
  let errors: RowError[] = [];
  try {
    const body = (await res.json()) as { detail?: unknown };
    const detail = body?.detail;
    if (typeof detail === 'string') {
      message = detail;
    } else if (Array.isArray(detail)) {
      // FastAPI request-validation errors: [{loc, msg, type}]
      message = detail.map((d: { msg?: string; loc?: unknown[] }) => `${(d.loc ?? []).join('.')}: ${d.msg ?? ''}`).join('; ');
    } else if (detail && typeof detail === 'object') {
      const d = detail as { message?: string; violations?: Violation[]; errors?: RowError[] };
      if (d.message) message = d.message;
      violations = Array.isArray(d.violations) ? d.violations : [];
      errors = Array.isArray(d.errors) ? d.errors : [];
    }
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, message, violations, errors);
}

interface RequestOptions {
  query?: Query;
  body?: unknown;
  form?: FormData;
}

async function rawRequest(method: string, path: string, opts: RequestOptions = {}): Promise<Response> {
  const token = await getAccessToken();
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  let body: BodyInit | undefined;
  if (opts.form) {
    body = opts.form;
  } else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), { method, headers, body });
  } catch {
    throw new ApiError(0, 'Network error: the API could not be reached.');
  }
  if (!res.ok) throw await toApiError(res);
  return res;
}

async function request<T>(method: string, path: string, opts?: RequestOptions): Promise<T> {
  const res = await rawRequest(method, path, opts);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

const get = <T>(path: string, query?: Query) => request<T>('GET', path, { query });
const post = <T>(path: string, body?: unknown, query?: Query) => request<T>('POST', path, { body: body ?? {}, query });
const put = <T>(path: string, body: unknown, query?: Query) => request<T>('PUT', path, { body, query });

export interface Updated {
  updated: number;
}

export const api = {
  // Identity and cycle
  me: () => get<Me>('/me'),
  cycle: () => get<Cycle>('/cycle'),
  products: () => get<Product[]>('/products'),

  // Forecast
  forecast: () => get<ForecastResponse>('/forecast'),
  putForecast: (region: Region, version: 1 | 2, changes: QtyChange[], comment: string) =>
    put<SaveResult>(`/forecast/${region}`, { changes, comment }, { version }),
  revisions: (region: Region) => get<ForecastRevision[]>(`/forecast/${region}/revisions`),
  revision: (region: Region, rev: number) => get<ForecastRevisionDetail>(`/forecast/${region}/revisions/${rev}`),
  restoreRevision: (region: Region, rev: number, comment: string) =>
    post<SaveResult>(`/forecast/${region}/revisions/${rev}/restore`, { comment }),
  /** Downloads one region's forecast as it was at version V<rev>. */
  exportRevision: async (region: Region, rev: number) => {
    const res = await rawRequest('GET', '/export/forecast', { query: { region, rev } });
    saveBlob(await res.blob(), `forecast_${region}_V${rev}.xlsx`);
  },
  submitForecast: (region: Region, comment?: string) => post<unknown>(`/forecast/${region}/submit`, { comment }),
  approveForecast: (region: Region, comment?: string) => post<unknown>(`/forecast/${region}/approve`, { comment }),
  rejectForecast: (region: Region, comment: string) => post<unknown>(`/forecast/${region}/reject`, { comment }),

  // Inventory
  inventory: () => get<InventoryResponse>('/inventory'),
  putInventory: (changes: QtyChange[], comment: string) => put<Updated>('/inventory', { changes, comment }),

  // Allocation
  allocation: () => get<AllocationResponse>('/allocation'),
  autoAllocate: (comment: string, basis: 1 | 2) => post<AutoAllocateResult>('/allocation/auto', { comment, basis }),
  putAllocationV1: (changes: AllocationChange[], comment: string) => put<Updated>('/allocation/v1', { changes, comment }),
  submitAllocation: (comment?: string) => post<unknown>('/allocation/submit', { comment }),
  confirmAllocation: (comment?: string) => post<unknown>('/allocation/confirm', { comment }),
  approveAllocation: (comment?: string) => post<unknown>('/allocation/approve', { comment }),
  rejectAllocation: (comment: string) => post<unknown>('/allocation/reject', { comment }),

  // Transfers
  transfers: () => get<Transfer[]>('/transfers'),
  createTransfer: (t: { productId: number; fromRegion: Region; toRegion: Region; qty: number; comment: string }) =>
    post<Transfer>('/transfers', t),
  undoTransfer: (id: number, comment: string) => post<Transfer>(`/transfers/${id}/undo`, { comment }),
  approveTransfer: (id: number, comment?: string) => post<Transfer>(`/transfers/${id}/approve`, { comment }),
  rejectTransfer: (id: number, comment: string) => post<Transfer>(`/transfers/${id}/reject`, { comment }),
  approveAllTransfers: (comment?: string) => post<{ approved: number }>('/transfers/approve-all', { comment }),

  // Summary / audit
  summary: () => get<Summary>('/summary'),
  audit: (q: AuditQuery) => get<AuditEntry[]>('/audit', { ...q }),

  // Files
  files: () => get<FileRecord[]>('/files'),
  uploadFile: (kind: FileKind, file: File, comment: string, query?: { region?: Region; version?: 1 | 2 }) => {
    const form = new FormData();
    form.append('file', file);
    form.append('comment', comment);
    return request<UploadResult>('POST', `/files/${kind}`, {
      form,
      query,
    });
  },
  /** Downloads `/export/{kind}` with the bearer token and saves it as a file. */
  exportFile: async (kind: ExportKind, version?: ExportVersion) => {
    const res = await rawRequest('GET', `/export/${kind}`, { query: { version } });
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') ?? '';
    const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
    const fallback = `${kind}${version ? `_${version === 'final' ? 'final' : `v${version}`}` : ''}.xlsx`;
    saveBlob(blob, match ? decodeURIComponent(match[1]) : fallback);
  },

  // Admin
  adminUsers: () => get<AdminUser[]>('/admin/users'),
  adminStage: (action: 'advance' | 'reset', comment: string) => post<Cycle>('/admin/stage', { action, comment }),
  health: () => get<HealthReport>('/admin/health'),
  rulesCatalogue: () => get<RuleInfo[]>('/rules/catalogue'),
  ruleConfig: () => get<RuleConfig>('/config/rules'),
  putRuleConfig: (cfg: RuleConfig, comment: string) => put<RuleConfig>('/admin/rule-config', { ...cfg, comment }),
};

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
