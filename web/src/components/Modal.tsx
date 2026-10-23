import { useEffect, useId, useState, type ReactNode } from 'react';

interface ModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}

/**
 * Generic dialog with title, body and optional footer; closes on Escape or a click on the backdrop.
 * @param props.open - whether the dialog is shown
 * @param props.title - dialog heading
 * @param props.onClose - called when the user closes the dialog
 * @param props.footer - optional footer content (buttons)
 * @param props.wide - uses the wide layout
 * @returns the rendered dialog, or null when closed
 */
export function Modal({ open, title, onClose, children, footer, wide }: ModalProps) {
  const titleId = useId();
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${wide ? ' modal-wide' : ''}`} role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <div className="modal-head">
          <h2 id={titleId}>{title}</h2>
          <button className="icon-btn" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

interface CommentModalProps {
  open: boolean;
  title: string;
  onClose: () => void;
  /** Resolve to close the modal; reject to keep it open (error already shown). */
  onSubmit: (comment: string) => Promise<unknown>;
  confirmLabel?: string;
  /** When true (default) the comment must be non-empty (FR-C2). */
  required?: boolean;
  danger?: boolean;
  children?: ReactNode;
  placeholder?: string;
  /** Extra condition that must hold before submitting. */
  canSubmit?: boolean;
}

/**
 * Comment dialog: saving is impossible with an empty comment when required.
 * Clears the comment on open, submits with the button or Ctrl/Cmd+Enter and closes only when `onSubmit` resolves.
 * @param props.onSubmit - receives the trimmed comment; resolve to close, reject to keep the dialog open
 * @param props.required - comment must be non-empty (default true, FR-C2)
 * @param props.canSubmit - extra condition that must hold before submitting
 * @param props.confirmLabel - text of the confirm button (default "Save")
 * @param props.danger - shows the confirm button in the danger style
 * @param props.children - extra content above the comment field (e.g. a change summary)
 * @returns the rendered dialog
 */
export function CommentModal({
  open,
  title,
  onClose,
  onSubmit,
  confirmLabel = 'Save',
  required = true,
  danger,
  children,
  placeholder,
  canSubmit = true,
}: CommentModalProps) {
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const fieldId = useId();

  useEffect(() => {
    if (open) setComment('');
  }, [open]);

  const empty = comment.trim().length === 0;
  const disabled = busy || !canSubmit || (required && empty);

  /**
   * Submits the trimmed comment, closes on success and keeps the dialog open on failure (the error toast is already shown).
   * @returns a Promise that settles when the submit is finished
   */
  const submit = async () => {
    if (disabled) return;
    setBusy(true);
    try {
      await onSubmit(comment.trim());
      onClose();
    } catch {
      /* error toast already shown by the mutation */
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      title={title}
      onClose={busy ? () => undefined : onClose}
      footer={
        <>
          <button className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`} onClick={submit} disabled={disabled}>
            {busy ? 'Working…' : confirmLabel}
          </button>
        </>
      }
    >
      {children}
      <label className="field" htmlFor={fieldId}>
        <span>
          Comment {required ? <span className="req">(required)</span> : <span className="muted">(optional)</span>}
        </span>
        <textarea
          id={fieldId}
          rows={3}
          value={comment}
          autoFocus
          placeholder={placeholder ?? 'Why is this change being made?'}
          onChange={(e) => setComment(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) void submit();
          }}
        />
      </label>
      {required && empty && <p className="hint">A comment is required before saving.</p>}
    </Modal>
  );
}
