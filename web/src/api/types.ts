// Types mirror docs/API_CONTRACT.md section 1 (public API).

export const REGIONS = ['North', 'East', 'West', 'South'] as const;
export type Region = (typeof REGIONS)[number];

export const ROLES = ['SALES_MANAGER', 'REGIONAL_MANAGER', 'PLANNER', 'HEAD_OF_SALES', 'ADMIN'] as const;
export type Role = (typeof ROLES)[number];

export type StageNumber = 1 | 2 | 3 | 4 | 5 | 6;
export type StageKey =
  | 'FORECAST_INPUT'
  | 'REGIONAL_REVIEW'
  | 'PLANNING'
  | 'REGIONAL_CHANGE'
  | 'FINAL_APPROVAL'
  | 'PUBLISHED';

/** `{ "<productId>": qty }`; a missing product means 0. */
export type QtyMap = Record<string, number>;
export type RegionMap<T> = Partial<Record<Region, T>>;

export type ForecastStatus = 'draft' | 'submitted' | 'approved' | 'rejected';
export type AllocationStatus = 'draft' | 'approved' | 'published';

export interface Violation {
  ruleId: string;
  product: string | null;
  region: Region | null;
  message: string;
}

export interface RowError {
  row: number;
  message: string;
}

export interface Me {
  username: string;
  name: string;
  role: Role;
  region: Region | null;
  claims: Record<string, unknown>;
}

export interface RegionForecastStatus {
  v1: ForecastStatus | null;
  v2: ForecastStatus | null;
  /** Version number (V<n>) the Sales Manager / Regional Manager working copy currently holds. */
  v1Rev?: number | null;
  v2Rev?: number | null;
  /** Version the Sales Manager submitted; reviewers and planning see this one. */
  v1SubmittedRev?: number | null;
  /** Latest Regional Manager rejection while the forecast is rejected (shown to the Sales Manager). */
  rejection?: Rejection | null;
}

export interface Rejection {
  by: string;
  comment: string | null;
  at: string;
}

export type RevisionSource = 'edit' | 'upload' | 'submit' | 'restore';

/** One saved version of a region's forecast (every save creates the next V<n>). */
export interface ForecastRevision {
  revNo: number;
  label: string;
  /** 1 = Sales Manager, 2 = Regional Manager */
  stage: 1 | 2;
  source: RevisionSource;
  fileName: string | null;
  createdBy: string;
  role: Role | string;
  comment: string | null;
  changed: number;
  total: number;
  /** false = uploaded while the forecast was locked; kept in history, not in the working forecast. */
  applied: boolean;
  createdAt: string;
}

export interface ForecastRevisionDetail extends ForecastRevision {
  lines: QtyMap;
}

export interface SaveResult {
  updated: number;
  revision: number | null;
}

export interface Confirmation {
  by: string;
  at: string;
}

export interface PeriodInfo {
  period: string; // "2026-11"
  label: string; // "Nov 2026"
  cycleId: number;
  name: string;
  stage: StageNumber;
  stageKey: StageKey;
}

export interface Cycle {
  id: number;
  name: string;
  period: string;
  periodLabel: string;
  stage: StageNumber;
  stageKey: StageKey;
  forecast: RegionMap<RegionForecastStatus>;
  allocation: { v1: AllocationStatus | null; v2: AllocationStatus | null; final: AllocationStatus | null };
  confirmations: RegionMap<Confirmation | null>;
  nextActor: string;
}

export interface Product {
  id: number;
  name: string;
}

export interface ForecastResponse {
  regions: Region[];
  products: Product[];
  v1: RegionMap<QtyMap | null>;
  v2: RegionMap<QtyMap | null>;
  status: RegionMap<RegionForecastStatus>;
}

export interface QtyChange {
  productId: number;
  qty: number;
}

export interface AllocationChange {
  productId: number;
  region: Region;
  qty: number;
}

export interface InventorySnapshot {
  id: number;
  sourceFile: string | null;
  uploadedBy: string;
  createdAt: string;
}

export interface InventoryResponse {
  snapshot: InventorySnapshot | null;
  lines: QtyMap;
}

export type AllocationMatrix = RegionMap<QtyMap>;

export interface AllocationResponse {
  regions: Region[];
  v1: AllocationMatrix | null;
  v2: AllocationMatrix | null;
  final: AllocationMatrix | null;
  status: { v1: AllocationStatus | null; v2: AllocationStatus | null; final: AllocationStatus | null };
}

export interface AutoAllocateResult {
  v1: AllocationMatrix;
  violations: Violation[];
}

export type TransferStatus = 'pending' | 'undone' | 'approved' | 'rejected';

export interface Transfer {
  id: number;
  productId: number;
  product: string;
  fromRegion: Region;
  toRegion: Region;
  qty: number;
  comment: string;
  requestedBy: string;
  requestedRegion: Region;
  status: TransferStatus;
  createdAt: string;
  /** Head of Sales decision (approve / reject), when made. */
  decidedBy?: string | null;
  decidedAt?: string | null;
  decisionComment?: string | null;
}

export interface RegionSummary {
  forecastV1: number;
  forecastV2: number;
  allocationV1: number;
  allocationV2: number;
  final: number | null;
}

export interface Summary {
  forecastV1: number;
  forecastV2: number;
  inventory: number;
  allocated: number;
  transfersPending: number;
  byRegion: RegionMap<RegionSummary>;
}

export const AUDIT_ENTITIES = ['forecast', 'inventory', 'allocation', 'transfer', 'approval', 'workflow', 'file'] as const;
export type AuditEntity = (typeof AUDIT_ENTITIES)[number];

export interface AuditEntry {
  id: number;
  ts: string;
  username: string;
  role: Role | string;
  region: Region | null;
  entity: AuditEntity | string;
  version: string | null;
  productId: number | null;
  product: string | null;
  beforeQty: number | null;
  afterQty: number | null;
  comment: string | null;
  status: string | null;
  /** Month-year the change belongs to ("2026-11" / "Nov 2026"). */
  period: string | null;
  periodLabel: string | null;
}

export interface AuditQuery {
  /** Omitted = selected month, "all" = every month, "2026-11" = that month. */
  month?: string;
  role?: string;
  entity?: string;
  region?: string;
  q?: string;
  limit?: number;
}

export type FileKind = 'forecast' | 'inventory' | 'allocation';
export type ExportKind = FileKind | 'audit';
export type ExportVersion = '1' | '2' | 'final';

export interface UploadResult {
  fileId: number;
  status: string;
  path: string;
  applied: number;
  revision?: number | null;
  /** One entry per month-year the file touched (a Month column can span several). */
  periods?: { period: string; label: string; applied: number; revision: number | null; message: string }[];
  /** Product names from the file that were added to the product list. */
  newProducts?: string[];
  /** Plain-language outcome, e.g. kept as a history-only version while the forecast is locked. */
  message?: string | null;
}

export interface FileRecord {
  id: number;
  path: string;
  kind: string;
  status: string;
  message: string | null;
  uploadedBy: string;
  receivedAt: string;
}

export interface AdminUser {
  username: string;
  name: string;
  email: string;
  role: Role | string | null;
  region: Region | string | null;
  enabled: boolean;
}

export interface Health {
  ok: boolean;
  detail: string;
}

export type HealthReport = Record<'api' | 'database' | 'keycloak' | 'rules' | 'files' | 'sftp', Health>;

export interface RuleInfo {
  id: string;
  package: string;
  description: string;
}

export type SharingMode = 'UNMET_DEMAND' | 'PROPORTIONAL';

export interface RuleConfig {
  baselinePct: number;
  sharing: SharingMode;
}

export interface AllocationLogic {
  engine: string;
  drl: string;
  config: RuleConfig;
}
