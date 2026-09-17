import { useState, type ReactNode } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { Check, Copy, X, AlertTriangle } from 'lucide-react';
import type { UseQueryResult } from '@tanstack/react-query';
import { ApiError } from './api';
import s from './ui.module.css';
export const date = (value: number | string | null | undefined) => value == null ? '—' : new Date(value).toISOString().replace('T', ' ').replace('.000Z', ' UTC');
export const duration = (ms: number | null | undefined) => ms == null ? '—' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
export function Badge({ state }: { state: string }) {
  const symbols: Record<string, string> = { succeeded: '✓', failed: '×', running: '▶', queued: '○', retry_wait: '↻', canceled: '−', lost: '⚠', timed_out: '◷', paused: 'Ⅱ', active: '●', stale: '⚠' };
  return <span className={s.badge} data-state={state}><span aria-hidden="true">{symbols[state] ?? '◇'}</span>{state.replaceAll('_', ' ')}</span>;
}
export function Heading({ title, eyebrow, children }: { title: string; eyebrow?: string; children?: ReactNode }) { return <header className={s.heading}><div><div className={s.eyebrow}>{eyebrow ?? 'LOCAL OPERATIONS'}</div><h1>{title}</h1></div>{children}</header>; }
export function Panel({ title, children }: { title?: string; children: ReactNode }) { return <section className={s.panel}>{title && <h2>{title}</h2>}{children}</section>; }
export function ErrorNotice({ error }: { error: Error }) { return <div className={s.error} role="alert"><AlertTriangle size={18}/><div>{error instanceof ApiError && error.status === 401 ? 'Access token rejected. Disconnect and enter your installation token again.' : error.message}{error instanceof ApiError && error.status === 409 && <p>The server rejected a conflicting operation. Current data has been refreshed; review it before trying again.</p>}{error instanceof ApiError && error.requestId && <small>Request {error.requestId}</small>}</div></div>; }
export function QueryState<T>({ query, children }: { query: UseQueryResult<T, Error>; children: (data: T) => ReactNode }) {
  if (query.data === undefined) return query.isError ? <><ErrorNotice error={query.error}/><button onClick={() => void query.refetch()}>Try again</button></> : <div className={s.loading} role="status">Loading local data…</div>;
  return <>{query.isError && <div className={s.stale}><strong>Stale cached data</strong> · Last successful update {date(query.dataUpdatedAt)}. Mutations are disabled.<ErrorNotice error={query.error}/><button onClick={() => void query.refetch()}>Reconnect</button></div>}<div className={s.freshness}>{query.isFetching ? 'Refreshing…' : 'Last updated'} {date(query.dataUpdatedAt)}</div>{children(query.data)}</>;
}
export function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) { const [message, setMessage] = useState(''); return <><button className={s.copy} onClick={() => { void navigator.clipboard.writeText(text).then(() => setMessage('Copied'), () => setMessage('Copy unavailable; select text manually.')); }}>{message === 'Copied' ? <Check size={16}/> : <Copy size={16}/>} {label}</button><span role="status" className={s.muted}>{message}</span></>; }
export function JsonView({ value }: { value: unknown }) { const text = JSON.stringify(value, null, 2) ?? 'null'; const capped = text.slice(0, 65536); return <div><div className={s.toolbar}><span className={s.muted}>{new TextEncoder().encode(text).length.toLocaleString()} bytes{text.length > 65536 ? ' · display capped at 65,536 characters' : ''}</span><CopyButton text={capped}/></div><pre>{capped}</pre></div>; }
export function Confirm({ label, title, children, disabled, pending, onConfirm }: { label: string; title: string; children: ReactNode; disabled?: boolean; pending?: boolean; onConfirm: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  return <Dialog.Root open={open} onOpenChange={v => { if (!pending) setOpen(v); }}><Dialog.Trigger asChild><button disabled={disabled}>{label}</button></Dialog.Trigger><Dialog.Portal><Dialog.Overlay className={s.overlay}/><Dialog.Content className={s.dialog}><Dialog.Title>{title}</Dialog.Title><Dialog.Description asChild><div className={s.muted}>{children}</div></Dialog.Description><div className={s.actions}><Dialog.Close asChild><button disabled={pending}>Keep unchanged</button></Dialog.Close><button className={s.primary} disabled={pending} onClick={() => { void onConfirm().then(() => setOpen(false)).catch(() => setOpen(false)); }}>{pending ? 'Working…' : `Confirm ${label.toLowerCase()}`}</button></div><Dialog.Close asChild><button className={s.close} aria-label="Close dialog" disabled={pending}><X size={18}/></button></Dialog.Close></Dialog.Content></Dialog.Portal></Dialog.Root>;
}
