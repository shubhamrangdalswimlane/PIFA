import { getAccessToken } from '../auth/keycloak';
import { getPeriod } from '../period';
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
  PeriodInfo,
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

/**
 * Error thrown by every API call that fails: carries the HTTP status (0 = network error),
 * a readable message and, for business-rule (422) failures, the rule violations and Excel row errors.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly violations: Violation[];
  readonly errors: RowError[];

  /**
   * Creates an API error.
   * @param status - HTTP status code (0 when the API could not be reached)
   * @param message - plain-language error message shown to the user
   * @param violations - business-rule violations returned by the server (default none)
   * @param errors - per-row Excel file errors returned by the server (default none)
   */
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

/**
 * Builds the full API URL from a path and optional query parameters (empty / null values are dropped).
 * @param path - API path such as `/forecast/North`
 * @param query - optional query parameters
 * @returns the absolute API URL including the query string
 */
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

/**
 * Turns a failed HTTP response into an `ApiError`, reading FastAPI's `detail` (string, validation
 * list or `{message, violations, errors}` object) and falling back to a generic text per status code.
 * @param res - the non-OK fetch response
 * @returns a Promise resolving to the `ApiError` to throw
 */
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

/**
 * Low-level request: attaches the Keycloak bearer token and the selected month (`X-Period`),
 * sends JSON or multipart form data, and throws `ApiError` on network or HTTP failure.
 * @param method - HTTP method
 * @param path - API path
 * @param opts - query parameters, JSON body or form data
 * @returns a Promise resolving to the successful `Response`
 */
async function rawRequest(method: string, path: string, opts: RequestOptions = {}): Promise<Response> {
  const token = await getAccessToken();
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  const period = getPeriod();
  if (period) headers['X-Period'] = period; // month-year the request is about
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

/**
 * Sends a request and parses the JSON response body (204 / empty body gives `undefined`).
 * @param method - HTTP method
 * @param path - API path
 * @param opts - query parameters, JSON body or form data
 * @returns a Promise resolving to the parsed response of type `T`
 */
async function request<T>(method: string, path: string, opts?: RequestOptions): Promise<T> {
  const res = await rawRequest(method, path, opts);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

/**
 * GET helper.
 * @param path - API path
 * @param query - optional query parameters
 * @returns a Promise resolving to the parsed JSON response
 */
const get = <T>(path: string, query?: Query) => request<T>('GET', path, { query });
/**
 * POST helper; sends `{}` when no body is given.
 * @param path - API path
 * @param body - JSON body
 * @param query - optional query parameters
 * @returns a Promise resolving to the parsed JSON response
 */
const post = <T>(path: string, body?: unknown, query?: Query) => request<T>('POST', path, { body: body ?? {}, query });
/**
 * PUT helper.
 * @param path - API path
 * @param body - JSON body
 * @param query - optional query parameters
 * @returns a Promise resolving to the parsed JSON response
 */
const put = <T>(path: string, body: unknown, query?: Query) => request<T>('PUT', path, { body, query });

export interface Updated {
  updated: number;
}

/**
 * Typed client for every PIFA REST endpoint (see docs/API_CONTRACT.md). Each call sends the bearer
 * token and the selected month (`X-Period`) and throws `ApiError` on failure.
 */
export const api = {
  // Identity, cycle and month-year periods
  /**
   * Current user's identity, roles and region.
   * @returns a Promise resolving to `Me`
   */
  me: () => get<Me>('/me'),
  /**
   * Workflow state of the selected month (current stage, per-region forecast statuses, confirmations).
   * @returns a Promise resolving to `Cycle`
   */
  cycle: () => get<Cycle>('/cycle'),
  /**
   * Month-years that already have a planning cycle (for the header month picker).
   * @returns a Promise resolving to the list of `PeriodInfo`
   */
  periods: () => get<PeriodInfo[]>('/periods'),
  /**
   * Opens a new month-year planning cycle.
   * @param period - month-year as "YYYY-MM"
   * @returns a Promise resolving to the created `PeriodInfo`
   */
  createPeriod: (period: string) => post<PeriodInfo>('/periods', { period }),
  /**
   * Printer product list (rows of every grid).
   * @returns a Promise resolving to the list of `Product`
   */
  products: () => get<Product[]>('/products'),

  // Forecast
  /**
   * Forecast of the selected month for every region the caller may see (V1 / V2 quantities and statuses).
   * @returns a Promise resolving to `ForecastResponse`
   */
  forecast: () => get<ForecastResponse>('/forecast'),
  /**
   * Saves forecast cell edits for a region; every save that changes something creates the region's next version V<n>.
   * @param region - region whose forecast is edited
   * @param version - 1 = Sales Manager working forecast, 2 = Regional Manager revision
   * @param changes - changed product quantities
   * @param comment - required reason for the change
   * @returns a Promise resolving to `SaveResult` (lines updated and the new version number)
   */
  putForecast: (region: Region, version: 1 | 2, changes: QtyChange[], comment: string) =>
    put<SaveResult>(`/forecast/${region}`, { changes, comment }, { version }),
  /**
   * Version history (V1…Vn) of one region's forecast, newest first.
   * @param region - region whose versions are listed
   * @returns a Promise resolving to the list of `ForecastRevision`
   */
  revisions: (region: Region) => get<ForecastRevision[]>(`/forecast/${region}/revisions`),
  /**
   * One saved forecast version including its quantities.
   * @param region - region of the forecast
   * @param rev - version number (the n of V<n>)
   * @returns a Promise resolving to `ForecastRevisionDetail`
   */
  revision: (region: Region, rev: number) => get<ForecastRevisionDetail>(`/forecast/${region}/revisions/${rev}`),
  /**
   * Copies an older version into the caller's working copy as a new version.
   * @param region - region of the forecast
   * @param rev - version number to restore
   * @param comment - required reason
   * @returns a Promise resolving to `SaveResult`
   */
  restoreRevision: (region: Region, rev: number, comment: string) =>
    post<SaveResult>(`/forecast/${region}/revisions/${rev}/restore`, { comment }),
  /**
   * Downloads one region's forecast as it was at version V<rev>.
   * @param region - region of the forecast
   * @param rev - version number to export
   * @returns a Promise that resolves once the .xlsx file has been handed to the browser
   */
  exportRevision: async (region: Region, rev: number) => {
    const res = await rawRequest('GET', '/export/forecast', { query: { region, rev } });
    saveBlob(await res.blob(), `forecast_${region}_V${rev}.xlsx`);
  },
  /**
   * Sales Manager submits the region's forecast for Regional Manager review.
   * @param region - region being submitted
   * @param comment - optional comment
   * @returns a Promise resolving to the server response
   */
  submitForecast: (region: Region, comment?: string) => post<unknown>(`/forecast/${region}/submit`, { comment }),
  /**
   * Regional Manager approves the region's forecast.
   * @param region - region being approved
   * @param comment - optional comment
   * @returns a Promise resolving to the server response
   */
  approveForecast: (region: Region, comment?: string) => post<unknown>(`/forecast/${region}/approve`, { comment }),
  /**
   * Regional Manager sends the region's forecast back to the Sales Manager.
   * @param region - region being rejected
   * @param comment - required reason, shown to the Sales Manager
   * @returns a Promise resolving to the server response
   */
  rejectForecast: (region: Region, comment: string) => post<unknown>(`/forecast/${region}/reject`, { comment }),

  // Inventory
  /**
   * Latest available-inventory snapshot of the selected month.
   * @returns a Promise resolving to `InventoryResponse`
   */
  inventory: () => get<InventoryResponse>('/inventory'),
  /**
   * Planner saves inventory cell edits.
   * @param changes - changed product quantities
   * @param comment - required reason
   * @returns a Promise resolving to the number of lines updated
   */
  putInventory: (changes: QtyChange[], comment: string) => put<Updated>('/inventory', { changes, comment }),

  // Allocation
  /**
   * Allocation matrices (V1, V2, Final) and their statuses for the selected month.
   * @returns a Promise resolving to `AllocationResponse`
   */
  allocation: () => get<AllocationResponse>('/allocation'),
  /**
   * Planner runs automatic allocation (rule R-ALLOC-01) from forecast V`basis` and inventory, writing Allocation V1 (draft).
   * @param comment - required reason
   * @param basis - forecast version to allocate from (1 = submitted, 2 = Regional Manager revision)
   * @returns a Promise resolving to `AutoAllocateResult` (new V1 and any rule violations)
   */
  autoAllocate: (comment: string, basis: 1 | 2) => post<AutoAllocateResult>('/allocation/auto', { comment, basis }),
  /**
   * Planner saves edits to Allocation V1 cells (product x region).
   * @param changes - changed product/region quantities
   * @param comment - required reason
   * @returns a Promise resolving to the number of cells updated
   */
  putAllocationV1: (changes: AllocationChange[], comment: string) => put<Updated>('/allocation/v1', { changes, comment }),
  /**
   * Planner submits Allocation V1 (checked against inventory); it is copied to V2 and the cycle moves to stage 4.
   * @param comment - optional comment
   * @returns a Promise resolving to the server response
   */
  submitAllocation: (comment?: string) => post<unknown>('/allocation/submit', { comment }),
  /**
   * Regional Manager confirms their region's Allocation V2 (stage 5 once all regions confirm).
   * @param comment - optional comment
   * @returns a Promise resolving to the server response
   */
  confirmAllocation: (comment?: string) => post<unknown>('/allocation/confirm', { comment }),
  /**
   * Head of Sales approves and publishes V2 as the Final allocation (stage 6).
   * @param comment - optional comment
   * @returns a Promise resolving to the server response
   */
  approveAllocation: (comment?: string) => post<unknown>('/allocation/approve', { comment }),
  /**
   * Head of Sales rejects the allocation back to stage 4 (confirmations are cleared).
   * @param comment - required reason
   * @returns a Promise resolving to the server response
   */
  rejectAllocation: (comment: string) => post<unknown>('/allocation/reject', { comment }),

  // Transfers
  /**
   * Unit transfers between regions in the selected month.
   * @returns a Promise resolving to the list of `Transfer`
   */
  transfers: () => get<Transfer[]>('/transfers'),
  /**
   * Regional Manager moves units of a product from one region to another in Allocation V2.
   * @param t - product, source and target region, quantity and required comment
   * @returns a Promise resolving to the created `Transfer`
   */
  createTransfer: (t: { productId: number; fromRegion: Region; toRegion: Region; qty: number; comment: string }) =>
    post<Transfer>('/transfers', t),
  /**
   * Requester undoes their own pending transfer (stage 4).
   * @param id - transfer id
   * @param comment - reason
   * @returns a Promise resolving to the updated `Transfer`
   */
  undoTransfer: (id: number, comment: string) => post<Transfer>(`/transfers/${id}/undo`, { comment }),
  /**
   * Head of Sales approves one pending transfer.
   * @param id - transfer id
   * @param comment - optional comment
   * @returns a Promise resolving to the updated `Transfer`
   */
  approveTransfer: (id: number, comment?: string) => post<Transfer>(`/transfers/${id}/approve`, { comment }),
  /**
   * Head of Sales rejects one transfer; its units move back in Allocation V2.
   * @param id - transfer id
   * @param comment - required reason
   * @returns a Promise resolving to the updated `Transfer`
   */
  rejectTransfer: (id: number, comment: string) => post<Transfer>(`/transfers/${id}/reject`, { comment }),
  /**
   * Head of Sales approves every pending transfer at once.
   * @param comment - optional comment
   * @returns a Promise resolving to the number of transfers approved
   */
  approveAllTransfers: (comment?: string) => post<{ approved: number }>('/transfers/approve-all', { comment }),

  // Summary / audit
  /**
   * Totals for the Head of Sales KPIs (forecast, inventory, allocation per region).
   * @returns a Promise resolving to `Summary`
   */
  summary: () => get<Summary>('/summary'),
  /**
   * Audit trail entries matching the filters.
   * @param q - role / entity / region / text / month filters and row limit
   * @returns a Promise resolving to the list of `AuditEntry`
   */
  audit: (q: AuditQuery) => get<AuditEntry[]>('/audit', { ...q }),

  // Files
  /**
   * Uploaded Excel files and their processing status.
   * @returns a Promise resolving to the list of `FileRecord`
   */
  files: () => get<FileRecord[]>('/files'),
  /**
   * Uploads an Excel file (forecast, inventory or allocation) with a comment as multipart form data.
   * @param kind - which file type is uploaded
   * @param file - the .xlsx file
   * @param comment - required reason
   * @param query - forecast uploads: target region and version
   * @returns a Promise resolving to `UploadResult` (rows applied, new version, months touched)
   */
  uploadFile: (kind: FileKind, file: File, comment: string, query?: { region?: Region; version?: 1 | 2 }) => {
    const form = new FormData();
    form.append('file', file);
    form.append('comment', comment);
    return request<UploadResult>('POST', `/files/${kind}`, {
      form,
      query,
    });
  },
  /**
   * Downloads `/export/{kind}` with the bearer token and saves it as a file.
   * @param kind - what to export (forecast, inventory, allocation or audit)
   * @param version - which version to export ('1', '2' or 'final')
   * @param extra - extra query parameters (e.g. audit month)
   * @returns a Promise that resolves once the file has been handed to the browser
   */
  exportFile: async (kind: ExportKind, version?: ExportVersion, extra?: Query) => {
    const res = await rawRequest('GET', `/export/${kind}`, { query: { version, ...extra } });
    const blob = await res.blob();
    const cd = res.headers.get('Content-Disposition') ?? '';
    const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
    const fallback = `${kind}${version ? `_${version === 'final' ? 'final' : `v${version}`}` : ''}.xlsx`;
    saveBlob(blob, match ? decodeURIComponent(match[1]) : fallback);
  },

  // Admin
  /**
   * Admin: list of users with their roles and regions.
   * @returns a Promise resolving to the list of `AdminUser`
   */
  adminUsers: () => get<AdminUser[]>('/admin/users'),
  /**
   * Admin: moves the workflow one stage forward or resets the cycle to stage 1.
   * @param action - 'advance' or 'reset'
   * @param comment - required reason
   * @returns a Promise resolving to the updated `Cycle`
   */
  adminStage: (action: 'advance' | 'reset', comment: string) => post<Cycle>('/admin/stage', { action, comment }),
  /**
   * Admin: health of the API, database, Keycloak, rules engine and file services.
   * @returns a Promise resolving to `HealthReport`
   */
  health: () => get<HealthReport>('/admin/health'),
  /**
   * Catalogue of business rules (ids and descriptions).
   * @returns a Promise resolving to the list of `RuleInfo`
   */
  rulesCatalogue: () => get<RuleInfo[]>('/rules/catalogue'),
  /**
   * Current configurable rule settings (e.g. sharing mode).
   * @returns a Promise resolving to `RuleConfig`
   */
  ruleConfig: () => get<RuleConfig>('/config/rules'),
  /**
   * Admin: saves new rule settings.
   * @param cfg - the new rule configuration
   * @param comment - required reason
   * @returns a Promise resolving to the saved `RuleConfig`
   */
  putRuleConfig: (cfg: RuleConfig, comment: string) => put<RuleConfig>('/admin/rule-config', { ...cfg, comment }),
};

/**
 * Makes the browser download a Blob as a file (temporary object URL + hidden link click).
 * @param blob - file contents
 * @param filename - name the file is saved under
 * @returns nothing
 */
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
