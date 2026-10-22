import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './client';
import type { AuditQuery, Region } from './types';
import { useToast } from '../components/Toast';

export const qk = {
  me: ['me'] as const,
  cycle: ['cycle'] as const,
  products: ['products'] as const,
  forecast: ['forecast'] as const,
  revisions: (region: Region) => ['forecast', 'revisions', region] as const,
  revision: (region: Region, rev: number) => ['forecast-revision', region, rev] as const,
  inventory: ['inventory'] as const,
  allocation: ['allocation'] as const,
  transfers: ['transfers'] as const,
  summary: ['summary'] as const,
  audit: (q: AuditQuery) => ['audit', q] as const,
  files: ['files'] as const,
  adminUsers: ['admin', 'users'] as const,
  health: ['admin', 'health'] as const,
  rules: ['rules', 'catalogue'] as const,
  ruleConfig: ['rules', 'config'] as const,
};

export const useMe = () => useQuery({ queryKey: qk.me, queryFn: api.me, staleTime: 5 * 60_000 });
export const useCycle = () => useQuery({ queryKey: qk.cycle, queryFn: api.cycle, refetchInterval: 30_000 });
export const useProducts = () => useQuery({ queryKey: qk.products, queryFn: api.products });
export const useForecast = () => useQuery({ queryKey: qk.forecast, queryFn: api.forecast });
export const useRevisions = (region: Region, enabled = true) =>
  useQuery({ queryKey: qk.revisions(region), queryFn: () => api.revisions(region), enabled });

/** Number the next save of this region's forecast will get (versions are numbered per region). */
export function useNextRevision(region: Region | null): number {
  const revisions = useRevisions(region ?? 'North', region !== null);
  return (revisions.data?.[0]?.revNo ?? 0) + 1;
}
export const useRevision = (region: Region, rev: number | null) =>
  useQuery({
    queryKey: qk.revision(region, rev ?? 0),
    queryFn: () => api.revision(region, rev!),
    enabled: rev !== null,
    staleTime: Infinity, // saved versions never change
  });
export const useInventory = (enabled = true) => useQuery({ queryKey: qk.inventory, queryFn: api.inventory, enabled });
export const useAllocation = () => useQuery({ queryKey: qk.allocation, queryFn: api.allocation });
export const useTransfers = (enabled = true) => useQuery({ queryKey: qk.transfers, queryFn: api.transfers, enabled });
export const useSummary = () => useQuery({ queryKey: qk.summary, queryFn: api.summary });
export const useAudit = (q: AuditQuery) => useQuery({ queryKey: qk.audit(q), queryFn: () => api.audit(q) });
export const useFiles = () => useQuery({ queryKey: qk.files, queryFn: api.files });
export const useAdminUsers = () => useQuery({ queryKey: qk.adminUsers, queryFn: api.adminUsers });
export const useHealth = () => useQuery({ queryKey: qk.health, queryFn: api.health, staleTime: 0 });
export const useRulesCatalogue = () => useQuery({ queryKey: qk.rules, queryFn: api.rulesCatalogue, staleTime: 10 * 60_000 });
export const useRuleConfig = () => useQuery({ queryKey: qk.ruleConfig, queryFn: api.ruleConfig });

/**
 * Wraps a write call: shows a success toast, surfaces API errors (incl.
 * violations / row errors) in a toast, and refetches the cycle plus every
 * business query afterwards so stage and data stay consistent.
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
