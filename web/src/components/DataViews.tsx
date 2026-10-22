import { useMemo, useState } from 'react';
import { useAllocation, useForecast, useInventory, useProducts } from '../api/hooks';
import { EditableGrid, type GridColumn } from './EditableGrid';
import { ExportButton } from './ExcelTools';
import { allocationVersionMap, AllocationGrid, ForecastRegionsGrid, type AllocVersion, type FcVersion } from './Matrices';
import { Empty, Loading, Panel, QueryError, Tabs, VersionSwitch } from './ui';
import { fmtTime } from '../lib/format';

type View = 'forecast' | 'inventory' | 'allocation';

/** Read-only forecast / inventory / allocation views (Head of Sales FR-H1, Admin FR-A4). */
export function DataViews({ withInventory = true }: { withInventory?: boolean }) {
  const [view, setView] = useState<View>('forecast');
  return (
    <>
      <Tabs<View>
        value={view}
        onChange={setView}
        tabs={[
          { value: 'forecast', label: 'Forecast' },
          ...(withInventory ? [{ value: 'inventory' as const, label: 'Inventory' }] : []),
          { value: 'allocation', label: 'Allocation' },
        ]}
      />
      {view === 'forecast' && <ForecastView />}
      {view === 'inventory' && <InventoryView />}
      {view === 'allocation' && <AllocationView />}
    </>
  );
}

function ForecastView() {
  const forecast = useForecast();
  const [v, setV] = useState<FcVersion>('v2');
  if (forecast.isLoading) return <Loading what="forecast" />;
  if (forecast.error) return <QueryError error={forecast.error} />;
  return (
    <Panel
      title="Forecast (read-only)"
      actions={
        <VersionSwitch<FcVersion>
          value={v}
          onChange={setV}
          options={[
            { value: 'v1', label: 'V1' },
            { value: 'v2', label: 'V2 vs V1' },
          ]}
        />
      }
    >
      <ForecastRegionsGrid forecast={forecast.data!} version={v} toolbar={<ExportButton kind="forecast" version={v === 'v1' ? '1' : '2'} />} />
    </Panel>
  );
}

function InventoryView() {
  const products = useProducts();
  const inventory = useInventory();
  const lines = inventory.data?.lines;
  const columns = useMemo<GridColumn[]>(() => [{ type: 'qty', key: 'qty', label: 'Available inventory', values: lines ?? {} }], [lines]);
  if (products.isLoading || inventory.isLoading) return <Loading what="inventory" />;
  if (inventory.error) return <QueryError error={inventory.error} />;
  if (products.error) return <QueryError error={products.error} />;
  const snap = inventory.data?.snapshot;
  return (
    <Panel
      title="Inventory (read-only)"
      subtitle={snap ? `Snapshot #${snap.id} · ${snap.sourceFile ?? 'manual'} · ${snap.uploadedBy} · ${fmtTime(snap.createdAt)}` : 'No snapshot yet.'}
    >
      <EditableGrid products={products.data ?? []} columns={columns} toolbar={<ExportButton kind="inventory" />} />
    </Panel>
  );
}

function AllocationView() {
  const products = useProducts();
  const allocation = useAllocation();
  const inventory = useInventory();
  const a = allocation.data;
  const [choice, setChoice] = useState<AllocVersion | null>(null);
  const v = choice ?? (a?.final ? 'final' : a?.v2 ? 'v2' : 'v1');
  if (products.isLoading || allocation.isLoading) return <Loading what="allocation" />;
  if (allocation.error) return <QueryError error={allocation.error} />;
  if (products.error) return <QueryError error={products.error} />;
  return (
    <Panel
      title="Allocation (read-only)"
      actions={
        <VersionSwitch<AllocVersion>
          value={v}
          onChange={setChoice}
          options={[
            { value: 'v1', label: 'V1', disabled: !a?.v1 },
            { value: 'v2', label: 'V2', disabled: !a?.v2 },
            { value: 'final', label: 'Final', disabled: !a?.final },
          ]}
        />
      }
    >
      {a && allocationVersionMap(a, v) ? (
        <AllocationGrid
          products={products.data ?? []}
          allocation={a}
          version={v}
          inventory={inventory.data?.lines ?? null}
          toolbar={<ExportButton kind="allocation" version={v === 'v1' ? '1' : v === 'v2' ? '2' : 'final'} />}
        />
      ) : (
        <Empty>No allocation for this version yet.</Empty>
      )}
    </Panel>
  );
}
