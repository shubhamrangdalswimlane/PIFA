import { useMemo, useState } from 'react';
import { api } from '../api/client';
import { useApiMutation } from '../api/hooks';
import type { ExportKind, ExportVersion, FileKind, Product, Region } from '../api/types';
import { FILE_COLUMNS, parseWorkbook, valueKeys, type CurrentValues, type ParseResult } from '../lib/excel';
import { deltaClass, fmtDelta, fmtQty } from '../lib/format';
import { CommentModal } from './Modal';
import { useToast } from './Toast';

interface UploadProps {
  kind: FileKind;
  products: Product[];
  current: CurrentValues;
  region?: Region;
  version?: 1 | 2;
  disabled?: boolean;
  disabledReason?: string;
  label?: string;
  /** Allow several files; they are applied one after another (forecast: each file becomes its own version). */
  multiple?: boolean;
  /** Extra explanation shown in the dialog (e.g. what happens to an upload at the current stage). */
  note?: string;
}

interface QueuedFile {
  file: File;
  parsed: ParseResult | null;
  error: string | null;
}

/** Excel upload: parse in browser, before/after preview, required comment, then POST (FR-C3). */
export function UploadButton({ kind, products, current, region, version, disabled, disabledReason, label, multiple, note }: UploadProps) {
  const [open, setOpen] = useState(false);
  const [queue, setQueue] = useState<QueuedFile[]>([]);
  const [active, setActive] = useState(0);
  const [onlyChanged, setOnlyChanged] = useState(true);
  const toast = useToast();

  const upload = useApiMutation(
    ({ f, comment }: { f: File; comment: string }) =>
      api.uploadFile(kind, f, comment, kind === 'forecast' ? { region, version } : undefined),
    (r, v) => `${v.f.name}: ${r.message ?? `${r.status}, ${r.applied} row${r.applied === 1 ? '' : 's'} changed`}`,
  );

  const reset = () => {
    setQueue([]);
    setActive(0);
  };

  const parseOne = async (f: File): Promise<QueuedFile> => {
    if (!/\.xlsx$/i.test(f.name)) return { file: f, parsed: null, error: 'Only .xlsx files are accepted.' };
    try {
      return { file: f, parsed: await parseWorkbook(kind, f, products), error: null };
    } catch (e) {
      return { file: f, parsed: null, error: `Could not read the workbook: ${e instanceof Error ? e.message : String(e)}` };
    }
  };

  const onPick = async (files: FileList | null) => {
    reset();
    if (!files?.length) return;
    setQueue(await Promise.all(Array.from(files).map(parseOne)));
  };

  const selected = queue[active];
  const parsed = selected?.parsed ?? null;
  const parseError = selected?.error ?? null;

  const keys = useMemo(() => valueKeys(kind), [kind]);
  const preview = useMemo(() => {
    if (!parsed) return null;
    const rows = parsed.rows.map((r) => {
      const before = r.productId !== null ? current[String(r.productId)] : undefined;
      const changed = r.productId === null || keys.some((k) => (before?.[k] ?? 0) !== r.values[k]);
      return { ...r, before, changed };
    });
    return {
      rows,
      changed: rows.filter((r) => r.changed && r.productId !== null).length,
      unknown: rows.filter((r) => r.productId === null).length,
      invalid: rows.filter((r) => r.invalid.length > 0).length,
    };
  }, [parsed, current, keys]);

  const fileProblem = (q: QueuedFile) =>
    q.error ??
    (!q.parsed
      ? 'Not read'
      : q.parsed.missingColumns.length
        ? `Missing ${q.parsed.missingColumns.join(', ')}`
        : q.parsed.rows.length === 0
          ? 'No data rows'
          : q.parsed.rows.some((r) => r.invalid.length > 0)
            ? 'Invalid values'
            : null);
  const blocking = queue.length === 0 || queue.some((q) => fileProblem(q) !== null);

  return (
    <>
      <button
        className="btn"
        disabled={disabled}
        title={disabled ? disabledReason : `Upload ${kind} .xlsx`}
        onClick={() => {
          reset();
          setOpen(true);
        }}
      >
        ⇪ {label ?? 'Upload'}
      </button>
      <CommentModal
        open={open}
        title={`Upload ${kind}${region ? ` — ${region}` : ''}`}
        confirmLabel={queue.length > 1 ? `Upload ${queue.length} files in order` : 'Upload and apply'}
        canSubmit={!blocking}
        onClose={() => setOpen(false)}
        onSubmit={async (comment) => {
          if (!queue.length) throw new Error('No file');
          // Apply in order; each forecast file becomes its own version. Applied files leave the queue,
          // so after a failure the dialog stays open with only the remaining files.
          for (const q of [...queue]) {
            setActive(0);
            await upload.mutateAsync({ f: q.file, comment: queue.length > 1 ? `${comment} (${q.file.name})` : comment });
            setQueue((cur) => cur.filter((x) => x !== q));
          }
        }}
      >
        <p className="muted small">
          Expected columns: <code>{FILE_COLUMNS[kind].join(', ')}</code>
          {kind === 'forecast' && <> (or <code>Quantity</code>)</>}. Whole numbers ≥ 0.
          {kind === 'forecast' && ' Each file is saved as a new forecast version.'}
        </p>
        {note && <p className="hint">{note}</p>}
        <input
          type="file"
          multiple={multiple}
          accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={(e) => void onPick(e.target.files).catch(toast.error)}
        />
        {queue.length > 1 && (
          <>
            <ul className="upload-queue">
              {queue.map((q, i) => {
                const problem = fileProblem(q);
                return (
                  <li key={`${q.file.name}-${i}`} className={i === active ? 'active' : undefined}>
                    <span className="version-badge">#{i + 1}</span>
                    <span className="strong">{q.file.name}</span>
                    {problem ? <span className="chip chip-rejected">{problem}</span> : <span className="chip chip-approved">ready</span>}
                    <button className="btn btn-sm" onClick={() => setActive(i)} disabled={i === active}>
                      Preview
                    </button>
                  </li>
                );
              })}
            </ul>
            <p className="muted small">
              Files are applied top to bottom; a later file overrides an earlier one for the same product. The preview compares each file
              with the forecast as it is now.
            </p>
          </>
        )}
        {parseError && <p className="hint danger">{parseError}</p>}
        {parsed && parsed.missingColumns.length > 0 && (
          <p className="hint danger">Missing column(s): {parsed.missingColumns.join(', ')}</p>
        )}
        {preview && parsed && parsed.missingColumns.length === 0 && (
          <>
            <div className="preview-stats">
              <span>{preview.rows.length} rows</span>
              <span className="chip chip-draft">{preview.changed} changed</span>
              {preview.unknown > 0 && (
                <span className="chip chip-rejected">
                  {preview.unknown} {kind === 'inventory' ? 'new (will be created)' : 'unknown product(s)'}
                </span>
              )}
              {preview.invalid > 0 && <span className="chip chip-rejected">{preview.invalid} invalid</span>}
              {parsed.duplicates.length > 0 && <span className="chip chip-rejected">{parsed.duplicates.length} duplicate(s)</span>}
              <label className="check">
                <input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} />
                Only changed / flagged
              </label>
            </div>
            <div className="grid-wrap preview-wrap">
              <table className="grid mini">
                <thead>
                  <tr>
                    <th>Row</th>
                    <th className="col-product">Product</th>
                    {keys.map((k) => (
                      <th key={k} className="num" colSpan={3}>
                        {k === 'qty' ? 'Quantity' : k}: before → after (Δ)
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.rows
                    .filter((r) => !onlyChanged || r.changed || r.invalid.length > 0)
                    .slice(0, 500)
                    .map((r) => (
                      <tr
                        key={r.row}
                        className={r.invalid.length || r.productId === null ? 'row-danger' : r.changed ? 'row-changed' : undefined}
                      >
                        <td className="muted">{r.row}</td>
                        <td className="col-product">
                          {r.name}
                          {r.productId === null && (
                            <span className="flag">{kind === 'inventory' ? ' new' : ' unknown'}</span>
                          )}
                          {r.invalid.length > 0 && <span className="flag"> invalid {r.invalid.join(', ')}</span>}
                        </td>
                        {keys.map((k) => {
                          const b = r.before?.[k] ?? (r.productId === null ? null : 0);
                          const a = r.values[k];
                          const d = a !== null && b !== null ? a - b : null;
                          return [
                            <td key={`${k}b`} className="num muted">
                              {fmtQty(b)}
                            </td>,
                            <td key={`${k}a`} className="num strong">
                              {fmtQty(a)}
                            </td>,
                            <td key={`${k}d`} className={`num ${deltaClass(d)}`}>
                              {fmtDelta(d)}
                            </td>,
                          ];
                        })}
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
            <p className="muted small">The file is validated again by the server; rejected rows are listed if it fails.</p>
          </>
        )}
      </CommentModal>
    </>
  );
}

export function ExportButton({
  kind,
  version,
  label,
}: {
  kind: ExportKind;
  version?: ExportVersion;
  label?: string;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  return (
    <button
      className="btn"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await api.exportFile(kind, version);
        } catch (e) {
          toast.error(e);
        } finally {
          setBusy(false);
        }
      }}
    >
      {busy ? 'Exporting…' : (label ?? `⇩ Export${version ? ` ${version === 'final' ? 'Final' : `V${version}`}` : ''}`)}
    </button>
  );
}
