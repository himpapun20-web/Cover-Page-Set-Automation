import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Copy, KeyRound, Pencil, Plus, RefreshCw, Search, Trash2, UserPlus, X } from 'lucide-react';
import { api, type Row } from '../lib/api';
import { resourceConfigs, type Field } from '../lib/resources';

type Props = { resource: string; role: string; authMode?: string };
const formatValue = (value: unknown, kind?: string) => {
  if (value === null || value === undefined || value === '') return '—';
  if (kind === 'status') return String(value).replaceAll('_', ' ');
  if (kind === 'date') return String(value).slice(0, 10);
  if (typeof value === 'boolean') return value ? 'Enabled' : 'Disabled';
  if (typeof value === 'object') return JSON.stringify(value);
  const text = String(value);
  return text.length > 45 ? `${text.slice(0, 16)}…${text.slice(-12)}` : text;
};

export default function ResourcePage({ resource, role, authMode }: Props) {
  const config = resourceConfigs[resource];
  const canWrite = role === 'ADMIN' || (['PROJECT_MANAGER', 'OPERATOR'].includes(role) && resource !== 'companies' && resource !== 'users');
  const [rows, setRows] = useState<Row[]>([]);
  const [lookups, setLookups] = useState<Record<string, Row[]>>({});
  const [editing, setEditing] = useState<Row | null | 'new'>(null);
  const [passwordUser, setPasswordUser] = useState<Row | null>(null);
  const [invitation, setInvitation] = useState<{ code: string; expires_at: string } | null>(null);
  const [copiedInvitation, setCopiedInvitation] = useState(false);
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [form, setForm] = useState<Record<string, string>>({});
  const [passwordForm, setPasswordForm] = useState({ password: '', confirm: '' });

  async function load() {
    if (!config) return;
    setBusy(true); setError('');
    try {
      const result = await api.list(config.path);
      setRows(result.items);
      const refs = [...new Set(config.fields.map((field) => field.ref).filter((value): value is string => Boolean(value)))];
      const lookupResult = await Promise.all(refs.map(async (path) => [path, (await api.list(path)).items] as const));
      setLookups(Object.fromEntries(lookupResult));
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  useEffect(() => { void load(); }, [resource]);
  const filtered = useMemo(() => rows.filter((row) => config?.columns.some((column) => String(row[column.key] ?? '').toLowerCase().includes(query.toLowerCase()))), [rows, query, config]);
  function closePasswordDialog() {
    setPasswordUser(null);
    setPasswordForm({ password: '', confirm: '' });
    setError('');
  }

  function openForm(row: Row | null) {
    if (!config) return;
    setEditing(row ?? 'new');
    const initial: Record<string, string> = {};
    for (const field of config.fields) {
      const current = row?.[field.name];
      initial[field.name] = current === null || current === undefined ? '' : String(current);
    }
    setForm(initial); setError(''); setNotice('');
  }
  function optionsFor(field: Field) {
    if (field.options) return field.options.map((value) => ({ value, label: field.name === 'is_active' ? (value === 'true' ? 'Enabled' : 'Disabled') : value.replaceAll('_', ' ') }));
    return (lookups[field.ref || ''] || []).map((item) => {
      const label = item.project_name || item.company_name || item.full_name || item.pipe_id || item.file_name || item.id;
      const suffix = item.project_code ? ` · ${item.project_code}` : item.section_reference ? ` · ${item.section_reference}` : '';
      return { value: String(item.id), label: `${label}${suffix}` };
    });
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!config || !editing) return; setBusy(true); setError('');
    const payload: Record<string, unknown> = {};
    for (const field of config.fields) {
      const raw = form[field.name] ?? '';
      if (raw === '') { if (field.required) { setError(`${field.label} is required.`); setBusy(false); return; } payload[field.name] = null; continue; }
      if (field.kind === 'number') payload[field.name] = Number(raw);
      else if (field.name === 'is_active') payload[field.name] = raw === 'true';
      else payload[field.name] = raw;
    }
    try {
      if (editing === 'new') await api.create(config.path, payload);
      else await api.update(config.path, editing.id, payload);
      setEditing(null); setNotice('Saved. The project report will use the latest saved data.'); await load();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function remove(row: Row) {
    if (!config || !window.confirm(`Delete “${String(row[config.columns[0].key] ?? row.id)}”? Related records may prevent deletion.`)) return;
    setError('');
    try { await api.remove(config.path, row.id); setNotice('Record deleted.'); await load(); } catch (e) { setError((e as Error).message); }
  }
  async function savePassword(event: FormEvent) {
    event.preventDefault();
    if (!passwordUser) return;
    if (passwordForm.password.length < 12 || passwordForm.password.length > 128) {
      setError('Use a password between 12 and 128 characters.');
      return;
    }
    if (passwordForm.password !== passwordForm.confirm) {
      setError('The passwords do not match.');
      return;
    }
    setBusy(true); setError('');
    try {
      await api.setUserPassword(passwordUser.id, passwordForm.password);
      setPasswordUser(null); setPasswordForm({ password: '', confirm: '' });
      setNotice(`Password set for ${String(passwordUser.email)}. Share it with the user through a separate secure channel.`);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function createInvitation() {
    setBusy(true); setError(''); setNotice('');
    try {
      setInvitation(await api.createSignupInvitation());
      setCopiedInvitation(false);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function copyInvitation() {
    if (!invitation) return;
    try {
      await navigator.clipboard.writeText(invitation.code);
      setCopiedInvitation(true);
    } catch (e) {
      setError((e as Error).message || 'Could not copy the invitation code. Select and copy it manually.');
    }
  }
  if (!config) return <div className="alert alert-error">This data type is not available.</div>;
  return <div className="page-stack">
    <section className="page-heading"><div><div className="eyebrow">RECORD MANAGEMENT / {config.path.toUpperCase()}</div><h1>{config.title}</h1><p>{config.description}</p></div><div className="heading-actions"><button className="button button-quiet" onClick={() => void load()}><RefreshCw size={15} /> Refresh</button>{resource === 'users' && role === 'ADMIN' && authMode === 'password' && <button className="button button-quiet" onClick={() => void createInvitation()} disabled={busy}><UserPlus size={15} /> Create invite</button>}{canWrite && <button className="button button-primary" onClick={() => openForm(null)}><Plus size={16} /> Add {config.singular}</button>}</div></section>
    {error && <div className="alert alert-error">{error}</div>}{notice && <div className="alert alert-success">{notice}</div>}
    <section className="panel"><div className="toolbar"><span className="record-count">{rows.length} records</span><label className="search-box"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search records" /></label></div>
      {busy && !rows.length ? <div className="empty-state">Loading records…</div> : !filtered.length ? <div className="empty-state">{query ? 'No records match this search.' : 'No records yet.'}</div> : <div className="table-scroll"><table><thead><tr>{config.columns.map((column) => <th key={column.key}>{column.label}</th>)}{canWrite && <th className="actions-cell">Actions</th>}</tr></thead><tbody>{filtered.map((row) => <tr key={row.id}>{config.columns.map((column) => <td key={column.key}>{column.kind === 'status' ? <span className={`status-pill status-${String(row[column.key] ?? '').toLowerCase()}`}>{formatValue(row[column.key], column.kind)}</span> : <span className={column.key.includes('id') || column.key.includes('reference') || column.key.includes('code') ? 'mono' : ''}>{formatValue(row[column.key], column.kind)}</span>}</td>)}{canWrite && <td className="actions-cell">{resource === 'users' && row.role !== 'AI_SERVICE' && <button className="icon-button" title="Set password" aria-label={`Set password for ${String(row.email)}`} onClick={() => { setPasswordUser(row); setPasswordForm({ password: '', confirm: '' }); setError(''); }}><KeyRound size={15} /></button>}<button className="icon-button" title="Edit" aria-label="Edit" onClick={() => openForm(row)}><Pencil size={15} /></button><button className="icon-button danger" title="Delete" aria-label="Delete" onClick={() => void remove(row)}><Trash2 size={15} /></button></td>}</tr>)}</tbody></table></div>}
    </section><p className="footnote">Lists are limited to 200 rows; pagination is not yet available. This trial app currently supports one company per deployment.</p>
    {editing && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setEditing(null); }}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><header className="modal-header"><div><div className="eyebrow">{editing === 'new' ? 'NEW RECORD' : 'EDIT RECORD'}</div><h2 id="modal-title">{editing === 'new' ? `Add ${config.singular}` : `Edit ${config.singular}`}</h2></div><button className="icon-button" aria-label="Close" onClick={() => setEditing(null)}><X size={18} /></button></header>{error && <div className="alert alert-error">{error}</div>}<form onSubmit={(event) => void submit(event)}><div className="form-grid">{config.fields.map((field) => <div className={`form-field ${field.kind === 'textarea' ? 'form-wide' : ''}`} key={field.name}><label htmlFor={`field-${field.name}`}>{field.label}{field.required && <b> *</b>}</label>{field.kind === 'textarea' ? <textarea id={`field-${field.name}`} required={field.required} value={form[field.name] || ''} rows={3} onChange={(event) => setForm({ ...form, [field.name]: event.target.value })} /> : field.kind === 'select' ? <select id={`field-${field.name}`} required={field.required} value={form[field.name] || ''} onChange={(event) => setForm({ ...form, [field.name]: event.target.value })}><option value="">Select an option</option>{optionsFor(field).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select> : <input id={`field-${field.name}`} required={field.required} type={field.kind || 'text'} step={field.kind === 'number' ? 'any' : undefined} value={form[field.name] || ''} onChange={(event) => setForm({ ...form, [field.name]: event.target.value })} />}
    </div>)}</div><footer className="modal-footer"><span className="muted">* Required fields</span><div><button type="button" className="button button-quiet" onClick={() => setEditing(null)}>Cancel</button><button type="submit" className="button button-primary" disabled={busy}>{busy ? 'Saving…' : 'Save record'}</button></div></footer></form></section></div>}
    {passwordUser && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closePasswordDialog(); }}><section className="modal password-modal" role="dialog" aria-modal="true" aria-labelledby="password-modal-title"><header className="modal-header"><div><div className="eyebrow">ACCOUNT ACCESS</div><h2 id="password-modal-title">Set password</h2></div><button className="icon-button" aria-label="Close" onClick={closePasswordDialog}><X size={18} /></button></header>{error && <div className="alert alert-error">{error}</div>}<form onSubmit={(event) => void savePassword(event)}><p className="muted">Set a password for <strong>{String(passwordUser.email)}</strong>. Share it with them through a separate secure channel.</p><div className="form-grid"><div className="form-field form-wide"><label htmlFor="user-password">Password</label><input id="user-password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required value={passwordForm.password} onChange={(event) => setPasswordForm((previous) => ({ ...previous, password: event.target.value }))} /></div><div className="form-field form-wide"><label htmlFor="user-password-confirm">Confirm password</label><input id="user-password-confirm" type="password" autoComplete="new-password" minLength={12} maxLength={128} required value={passwordForm.confirm} onChange={(event) => setPasswordForm((previous) => ({ ...previous, confirm: event.target.value }))} /></div></div><footer className="modal-footer"><span className="muted">Minimum 12 characters</span><div><button type="button" className="button button-quiet" onClick={closePasswordDialog}>Cancel</button><button type="submit" className="button button-primary" disabled={busy}>{busy ? 'Setting…' : 'Set password'}</button></div></footer></form></section></div>}
    {invitation && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setInvitation(null); }}><section className="modal password-modal" role="dialog" aria-modal="true" aria-labelledby="invitation-modal-title"><header className="modal-header"><div><div className="eyebrow">WORKSPACE ACCESS</div><h2 id="invitation-modal-title">Invitation created</h2></div><button className="icon-button" aria-label="Close" onClick={() => setInvitation(null)}><X size={18} /></button></header><div className="invite-content"><p className="muted">Share this one-time code with the new member. It expires {new Date(invitation.expires_at).toLocaleString()} and is shown only once.</p><label className="invite-code-label" htmlFor="invite-code">Invitation code</label><input className="invite-code-input" id="invite-code" readOnly value={invitation.code} onFocus={(event) => event.currentTarget.select()} /><button className="button button-primary" onClick={() => void copyInvitation()}><Copy size={15} />{copiedInvitation ? 'Copied' : 'Copy code'}</button></div></section></div>}
  </div>;
}
