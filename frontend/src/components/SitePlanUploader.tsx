import { useEffect, useState } from 'react';
import { Download, Map, Upload } from 'lucide-react';
import { api, type Row } from '../lib/api';

type Props = { projectId: string; canUpload: boolean; onUploaded: () => void };

export default function SitePlanUploader({ projectId, canUpload, onUploaded }: Props) {
  const [items, setItems] = useState<Row[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  async function load() {
    try { setItems((await api.projectSitePlans(projectId)).items); }
    catch (e) { setError((e as Error).message); }
  }
  useEffect(() => { void load(); }, [projectId]);
  async function upload(file?: File) {
    if (!file) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const saved = await api.uploadSitePlan(projectId, file);
      setItems((previous) => [...previous, saved]);
      setNotice('Site Layout Plan saved. Refresh the HTML preview to include it in Appendix I.');
      onUploaded();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="panel site-plan-panel"><div className="panel-heading"><div><div className="eyebrow">APPENDIX I / SITE PLAN EVIDENCE</div><h2>Site Layout Plan</h2><p>Upload a genuine site drawing image to place it in Appendix I. Supported formats: PNG, JPEG or WebP; maximum 25 MiB.</p></div>{canUpload && <label className="button button-quiet"><Upload size={15} /> {busy ? 'Uploading…' : 'Upload plan image'}<input type="file" accept="image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp" hidden disabled={busy} onChange={(event) => { void upload(event.target.files?.[0]); event.currentTarget.value = ''; }} /></label>}</div>
    {error && <div className="alert alert-error">{error}</div>}{notice && <div className="alert alert-success">{notice}</div>}
    {items.length ? <div className="site-plan-list">{items.map((item) => <div className="site-plan-item" key={String(item.id)}><Map size={16} /><span><strong>{String(item.file_name)}</strong><small>{String(item.width_px || '—')} × {String(item.height_px || '—')} px · {String(item.file_size_bytes || 0)} bytes</small></span><a className="icon-link" href={`/api/assets/${String(item.id)}/download`} target="_blank" rel="noreferrer" title="Download site plan"><Download size={15} /></a></div>)}</div> : <div className="batch-format">No actual Site Layout Plan is stored. Appendix I will identify that the drawing was not provided; no synthetic plan will be substituted.</div>}
  </section>;
}
