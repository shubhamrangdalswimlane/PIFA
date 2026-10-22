import type { ReactNode } from 'react';
import type { Region } from '../api/types';
import { REGION_CLASS } from '../lib/format';

export interface SwitchOption<T extends string> {
  value: T;
  label: string;
  disabled?: boolean;
  title?: string;
}

/** Segmented control used for V1 / V2 / Final switches (FR-C1). */
export function VersionSwitch<T extends string>({
  value,
  options,
  onChange,
  label = 'Version',
}: {
  value: T;
  options: SwitchOption<T>[];
  onChange: (v: T) => void;
  label?: string;
}) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      <span className="segmented-label">{label}</span>
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={value === o.value}
          className={value === o.value ? 'active' : ''}
          disabled={o.disabled}
          title={o.title}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({
  value,
  tabs,
  onChange,
}: {
  value: T;
  tabs: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.value}
          role="tab"
          aria-selected={value === t.value}
          className={value === t.value ? 'active' : ''}
          onClick={() => onChange(t.value)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function StatusChip({ status }: { status: string | null | undefined }) {
  const s = status ?? 'none';
  return <span className={`chip chip-${s}`}>{status ?? '—'}</span>;
}

export function RegionTag({ region, own }: { region: Region; own?: boolean }) {
  return (
    <span className={`region-tag ${REGION_CLASS[region]}${own ? ' own' : ''}`}>
      <span className="dot" />
      {region}
      {own && <span className="own-label">yours</span>}
    </span>
  );
}

export function Panel({
  title,
  actions,
  children,
  subtitle,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  subtitle?: ReactNode;
}) {
  return (
    <section className="panel">
      {(title || actions) && (
        <header className="panel-head">
          <div>
            {title && <h2>{title}</h2>}
            {subtitle && <p className="muted small">{subtitle}</p>}
          </div>
          {actions && <div className="panel-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Banner({ kind, children }: { kind: 'info' | 'warn' | 'danger' | 'success'; children: ReactNode }) {
  return <div className={`banner banner-${kind}`}>{children}</div>;
}

export function Loading({ what = 'data' }: { what?: string }) {
  return <div className="empty">Loading {what}…</div>;
}

export function QueryError({ error }: { error: unknown }) {
  return <Banner kind="danger">Could not load: {error instanceof Error ? error.message : String(error)}</Banner>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
