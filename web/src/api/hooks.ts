import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './client';
import type { AuditQuery, Region } from './types';
import { useToast } from '../components/Toast';

/**
 * React Query cache keys for every API resource (functions build keys that depend on arguments).
 */
export const qk = {
  me: ['me'] as const,
  cycle: ['cycle'] as const,
  periods: ['periods'] as const,
  products: ['products'] as const,
  forecast: ['forecast'] as const,
  /**
   * @param region - region whose version list is cached
   * @returns the cache key of that region's forecast versions
   */
  revisions: (region: Region) => ['forecast', 'revisions', region] as const,
  /**
   * @param region - region of the forecast
   * @param rev - version number
   * @returns the cache key of one saved forecast version
   */
  revision: (region: Region, rev: number) => ['forecast-revision', region, rev] as const,
  inventory: ['inventory'] as const,
  allocation: ['allocation'] as const,
  transfers: ['transfers'] as const,
  summary: ['summary'] as const,
  /**
   * @param q - audit filters
   * @returns the cache key of the audit list for those filters
   */
  audit: (q: AuditQuery) => ['audit', q] as const,
  files: ['files'] as const,
  adminUsers: ['admin', 'users'] as const,
  health: ['admin', 'health'] as const,
  rules: ['rules', 'catalogue'] as const,
  ruleConfig: ['rules', 'config'] as const,
  allocationLogic: ['rules', 'allocation'] as const,
};

/**
 * Current user's identity (cached 5 minutes).
 * @returns a React Query result with `Me`
 */
export const useMe = () => useQuery({ queryKey: qk.me, queryFn: api.me, staleTime: 5 * 60_000 });
/**
 * Month-years that have a planning cycle (header month picker).
 * @returns a React Query result with the list of periods
 */
export const usePeriods = () => useQuery({ queryKey: qk.periods, queryFn: api.periods, staleTime: 30_000 });
/**
 * Workflow stage and statuses of the selected month, polled every 30 s.
 * @returns a React Query result with `Cycle`
 */
export const useCycle = () => useQuery({ queryKey: qk.cycle, queryFn: api.cycle, refetchInterval: 30_000 });
/**
 * Printer product list.
 * @returns a React Query result with the products
 */
export const useProducts = () => useQuery({ queryKey: qk.products, queryFn: api.products });
/**
 * Forecast of the selected month for the regions the user may see.
 * @returns a React Query result with `ForecastResponse`
 */
export const useForecast = () => useQuery({ queryKey: qk.forecast, queryFn: api.forecast });
/**
 * Version history (V1…Vn) of a region's forecast.
 * @param region - region whose versions are loaded
 * @param enabled - set false to skip loading
 * @returns a React Query result with the list of versions, newest first
 */
export const useRevisions = (region: Region, enabled = true) =>
  useQuery({ queryKey: qk.revisions(region), queryFn: () => api.revisions(region), enabled });

/**
 * Number the next save of this region's forecast will get (versions are numbered per region).
 * @param region - region of the forecast, or null when none is chosen (then 1 is returned)
 * @returns the next version number n of V<n>
 */
export function useNextRevision(region: Region | null): number {
  const revisions = useRevisions(region ?? 'North', region !== null);
  return (revisions.data?.[0]?.revNo ?? 0) + 1;
}
/**
 * One saved forecast version with its quantities; cached forever because saved versions never change.
 * @param region - region of the forecast
 * @param rev - version number, or null to load nothing
 * @returns a React Query result with `ForecastRevisionDetail`
 */
export const useRevision = (region: Region, rev: number | null) =>
  useQuery({
    queryKey: qk.revision(region, rev ?? 0),
    queryFn: () => api.revision(region, rev!),
    enabled: rev !== null,
    staleTime: Infinity, // saved versions never change
  });
/**
 * Latest inventory snapshot of the selected month.
 * @param enabled - set false to skip loading
 * @returns a React Query result with `InventoryResponse`
 */
export const useInventory = (enabled = true) => useQuery({ queryKey: qk.inventory, queryFn: api.inventory, enabled });
/**
 * Allocation V1 / V2 / Final of the selected month.
 * @returns a React Query result with `AllocationResponse`
 */
export const useAllocation = () => useQuery({ queryKey: qk.allocation, queryFn: api.allocation });
/**
 * Region-to-region transfers of the selected month.
 * @param enabled - set false to skip loading
 * @returns a React Query result with the list of transfers
 */
export const useTransfers = (enabled = true) => useQuery({ queryKey: qk.transfers, queryFn: api.transfers, enabled });
/**
 * Head of Sales KPI totals.
 * @returns a React Query result with `Summary`
 */
export const useSummary = () => useQuery({ queryKey: qk.summary, queryFn: api.summary });
/**
 * Audit trail entries for the given filters.
 * @param q - audit filters
 * @returns a React Query result with the audit entries
 */
export const useAudit = (q: AuditQuery) => useQuery({ queryKey: qk.audit(q), queryFn: () => api.audit(q) });
/**
 * Uploaded Excel files.
 * @returns a React Query result with the file records
 */
export const useFiles = () => useQuery({ queryKey: qk.files, queryFn: api.files });
/**
 * Admin: users with roles and regions.
 * @returns a React Query result with the user list
 */
export const useAdminUsers = () => useQuery({ queryKey: qk.adminUsers, queryFn: api.adminUsers });
/**
 * Admin: service health report (never treated as fresh).
 * @returns a React Query result with `HealthReport`
 */
export const useHealth = () => useQuery({ queryKey: qk.health, queryFn: api.health, staleTime: 0 });
/**
 * Business rule catalogue (cached 10 minutes).
 * @returns a React Query result with the rule list
 */
export const useRulesCatalogue = () => useQuery({ queryKey: qk.rules, queryFn: api.rulesCatalogue, staleTime: 10 * 60_000 });
/**
 * Current rule configuration.
 * @returns a React Query result with `RuleConfig`
 */
/**
 * Allocation logic (Drools rule text, settings, worked example).
 * @returns a React Query result with `AllocationLogic`
 */
export const useAllocationLogic = () => useQuery({ queryKey: qk.allocationLogic, queryFn: api.allocationLogic });
/**
 * Current rule configuration.
 * @returns a React Query result with `RuleConfig`
 */
export const useRuleConfig = () => useQuery({ queryKey: qk.ruleConfig, queryFn: api.ruleConfig });

/**
 * Wraps a write call: shows a success toast, surfaces API errors (incl.
 * violations / row errors) in a toast, and refetches the cycle plus every
 * business query afterwards so stage and data stay consistent.
 * @param fn - the API call to run with the mutation variables
 * @param successMessage - toast text, or a function building it from the result and variables
 * @returns a React Query mutation (use `mutate` / `mutateAsync`)
 */
export function useApiMutation<TVars, TResult = unknown>(
  fn: (vars: TVars) => Promise<TResult>,
  successMessage: string | ((result: TResult, vars: TVars) => string),
) {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation<TResult, Error, TVars>({
    mutationFn: fn,
    onSuccess: (result, vars) => {
      toast.success(typeof successMessage === 'function' ? successMessage(result, vars) : successMessage);
    },
    onError: (err) => toast.error(err),
    onSettled: () => qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'me' }),
  });
}
