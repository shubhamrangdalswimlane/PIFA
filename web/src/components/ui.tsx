import type { ReactNode } from 'react';
import type { Region } from '../api/types';
import { REGION_CLASS } from '../lib/format';

export interface SwitchOption<T extends string> {
  value: T;
  label: string;
  disabled?: boolean;
  title?: string;
}

/**
 * Segmented control used for V1 / V2 / Final switches (FR-C1).
 * @param props.value - currently selected option
 * @param props.options - options (value, label, optional disabled / tooltip)
 * @param props.onChange - called with the chosen value
 * @param props.label - caption shown before the buttons (default "Version")
 * @returns the rendered control
 */
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

/**
 * Simple tab bar.
 * @param props.value - active tab
 * @param props.tabs - tab values and labels
 * @param props.onChange - called with the chosen tab
 * @returns the rendered tab bar
 */
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

/**
 * Coloured chip showing a status (draft, submitted, approved, pending …).
 * @param props.status - status text; missing shows "—"
 * @returns the rendered chip
 */
export function StatusChip({ status }: { status: string | null | undefined }) {
  const s = status ?? 'none';
  return <span className={`chip chip-${s}`}>{status ?? '—'}</span>;
}

/**
 * Region name with its colour dot; can mark the user's own region.
 * @param props.region - region to show
 * @param props.own - adds a "yours" label
 * @returns the rendered tag
 */
export function RegionTag({ region, own }: { region: Region; own?: boolean }) {
  return (
    <span className={`region-tag ${REGION_CLASS[region]}${own ? ' own' : ''}`}>
      <span className="dot" />
      {region}
      {own && <span className="own-label">yours</span>}
    </span>
  );
}

/**
 * Card section with optional title, subtitle and action buttons in the header.
 * @param props.title - heading
 * @param props.subtitle - small text under the heading
 * @param props.actions - buttons shown on the right of the header
 * @param props.children - panel content
 * @returns the rendered panel
 */
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

/**
 * Coloured message strip.
 * @param props.kind - info, warn, danger or success
 * @param props.children - message content
 * @returns the rendered banner
 */
export function Banner({ kind, children }: { kind: 'info' | 'warn' | 'danger' | 'success'; children: ReactNode }) {
  return <div className={`banner banner-${kind}`}>{children}</div>;
}

/**
 * Placeholder shown while data loads ("Loading forecast…").
 * @param props.what - what is loading (default "data")
 * @returns the rendered placeholder
 */
export function Loading({ what = 'data' }: { what?: string }) {
  return <div className="empty">Loading {what}…</div>;
}

/**
 * Danger banner for a failed data load.
 * @param props.error - the error to show
 * @returns the rendered banner
 */
export function QueryError({ error }: { error: unknown }) {
  return <Banner kind="danger">Could not load: {error instanceof Error ? error.message : String(error)}</Banner>;
}

/**
 * Muted placeholder for an empty list or table.
 * @param props.children - message
 * @returns the rendered placeholder
 */
export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
