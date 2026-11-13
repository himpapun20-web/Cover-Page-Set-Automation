import { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, CheckCircle2, Download, ExternalLink, Files, GitBranch, Plus, RefreshCw, Trash2, Upload } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { api, type ProjectReportData, type WinCanPipeRow } from '../lib/api';
import SitePlanUploader from '../components/SitePlanUploader';

type Props = { canGenerate: boolean; canUpload: boolean };
const shown = (value: unknown) => value === null || value === undefined || value === '' ? 'Not provided' : String(value);
const emptyRow = (): WinCanPipeRow => ({
  pipe_id: '',
  section_reference: '',
  start_manhole: '',
  finish_manhole: '',
  function_description: '',
  survey_length_m: '',
  pipe_size_mm: '',
  pipe_material_code: '',
  condition_grade: '',
  defects_summary: '',
  site_environment: '',
  remarks: '',
  recommendation: '',
});

export default function ReportPreview({ canGenerate, canUpload }: Props) {
  const { projectId } = useParams();
  const [summary, setSummary] = useState<ProjectReportData | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [reading, setReading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [iframeKey, setIframeKey] = useState(0);
  const [rows, setRows] = useState<WinCanPipeRow[]>([]);
  const [textPreview, setTextPreview] = useState('');
  const [fileName, setFileName] = useState('');

  async function loadSummary() {
    if (!projectId) return;
    setLoading(true);
    setError('');
    try { setSummary(await api.reportData(projectId)); }
    catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }
  useEffect(() => { void loadSummary(); }, [projectId, refreshKey]);

  const project = summary?.project;
  const htmlUrl = projectId ? `/api/projects/${projectId}/report.html?refresh=${iframeKey}` : '';
  const pdfUrl = projectId ? `/api/projects/${projectId}/report.pdf` : '';
  const ready = useMemo(() => rows.length > 0 && rows.every((row) => row.pipe_id.trim() && row.survey_length_m !== '' && Number.isFinite(Number(row.survey_length_m)) && Number(row.survey_length_m) >= 0), [rows]);

  async function readReport(file?: File) {
    if (!projectId || !file) return;
    setReading(true);
    setRows([]);
    setTextPreview('');
    setError('');
    setNotice('');
    try {
      const result = await api.previewWincanReport(projectId, file);
      setRows(result.rows);
      setTextPreview(result.text_preview);
      setFileName(file.name);
      setNotice(result.rows.length
        ? `Read ${result.page_count} PDF pages and found ${result.rows.length} pipe section${result.rows.length === 1 ? '' : 's'}. Review the imported values before saving.`
        : `Read ${result.page_count} PDF pages, but no pipe rows could be confidently mapped. Add or correct rows below before saving.`);
    } catch (e) { setError((e as Error).message); }
    finally { setReading(false); }
  }

  function updateRow(index: number, key: keyof WinCanPipeRow, value: string) {
    setRows((current) => current.map((row, rowIndex) => {
      if (rowIndex !== index) return row;
      if (key === 'pipe_id') return { ...row, pipe_id: value };
      if (key === 'survey_length_m') return { ...row, survey_length_m: value };
      return { ...row, [key]: value || null };
    }));
  }

  function removeRow(index: number) {
    setRows((current) => current.filter((_, rowIndex) => rowIndex !== index));
  }

  async function saveReport() {
    if (!projectId || !ready) return;
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const result = await api.applyWincanReport(projectId, rows);
      setNotice(`Saved ${result.count} WinCan pipe section${result.count === 1 ? '' : 's'} (${result.created} new, ${result.updated} updated).`);
      setRows([]);
      setTextPreview('');
      setFileName('');
      setRefreshKey((value) => value + 1);
      setIframeKey((value) => value + 1);
    } catch (e) { setError((e as Error).message); }
    finally { setSaving(false); }
  }

  function refreshReport() {
    setRefreshKey((key) => key + 1);
    setIframeKey((key) => key + 1);
  }

  if (!projectId) return <div className="alert alert-error">A project identifier is required.</div>;

  return <div className="page-stack report-preview-page">
    <section className="page-heading">
      <div><div className="eyebrow">PROJECT REPORT / WINCAN VX IMPORT</div><h1>Generate project report</h1><p>Import a WinCan VX PDF, review its pipe condition data and generate the requested summary report pages.</p></div>
      <div className="heading-actions"><Link className="button button-quiet" to="/"><ArrowLeft size={15} /> Dashboard</Link><button className="button button-quiet" onClick={refreshReport} disabled={loading}><RefreshCw size={15} /> Refresh report</button>{canGenerate ? <a className="button button-primary" href={pdfUrl}><Download size={15} /> Generate / download PDF</a> : <span className="status-pill">PDF generation requires a Project Manager</span>}</div>
    </section>
    {error && <div className="alert alert-error">{error}</div>}{notice && <div className="alert alert-success">{notice}</div>}
    {loading ? <div className="empty-state">Loading project data…</div> : project && <>
      <section className="panel report-project-card">
        <div className="panel-heading"><div><div className="eyebrow">{shown(project.project_code)}</div><h2>{shown(project.project_name)}</h2><p>{shown(project.client_name)} · {shown(project.location)} · Survey dates: {shown(project.survey_start_date)} – {shown(project.survey_end_date)}</p></div><span className={`status-pill status-${String(project.report_status || '').toLowerCase()}`}>{shown(project.report_status).replaceAll('_', ' ')}</span></div>
        <div className="report-steps">
          <Link className="report-step" to="/projects"><span className="step-icon">Project</span><span><strong>Project details</strong><small>Location, survey dates and EUSR certificate number</small></span><b>{project.location && project.survey_start_date ? 'Entered' : 'Review'}</b></Link>
          <Link className="report-step" to="/pipe-sections"><GitBranch size={16} /><span><strong>Pipe sections</strong><small>Condition, environment and recommendations from WinCan</small></span><b>{summary?.pipe_section_count ?? 0}</b></Link>
          <div className="report-step report-step-static"><Files size={16} /><span><strong>Report output</strong><small>Cover, summary, recommendation and conclusion pages</small></span><b><CheckCircle2 size={15} /> Ready to generate</b></div>
        </div>
      </section>
      <section className="panel batch-panel">
        <div className="panel-heading"><div><div className="eyebrow">WINCAN VX / PDF IMPORT</div><h2>Upload and read report</h2><p>Select the WinCan VX PDF export. Extracted values are editable and are not saved until you confirm them.</p></div>
          {canUpload && <label className="button button-primary"><Upload size={15} /> {reading ? 'Reading PDF…' : 'Select WinCan PDF'}<input type="file" accept="application/pdf,.pdf" hidden disabled={reading || saving} onChange={(event) => { void readReport(event.target.files?.[0]); event.currentTarget.value = ''; }} /></label>}
        </div>
        {fileName && <p className="small">Selected report: <strong>{fileName}</strong></p>}
        {reading && <div className="empty-state">Extracting selectable text and pipe summaries from the PDF…</div>}
        {canUpload && !reading && <div className="batch-actions"><span className="muted">Scanned PDFs without selectable text require OCR before import. You can add missing pipe rows manually below.</span><button className="button button-quiet" type="button" onClick={() => setRows((current) => [...current, emptyRow()])}><Plus size={15} /> Add pipe row</button></div>}
        {!!rows.length && <>
          <div className="batch-summary">{rows.length} pipe section{rows.length === 1 ? '' : 's'} found. Verify pipe IDs, lengths, condition details and recommendations before saving.</div>
          <div className="table-scroll batch-table-wrap"><table className="batch-table">
            <thead><tr><th>Pipe ID</th><th>Section ref.</th><th>Start MH</th><th>To MH</th><th>Function</th><th>Length (m)</th><th>Size (mm)</th><th>Material</th><th>Grade</th><th>Defects / condition</th><th>Remarks</th><th>Recommendation</th><th>Remove</th></tr></thead>
            <tbody>{rows.map((row, index) => <tr key={`${row.pipe_id}-${index}`}>
              <td><input aria-label="Pipe ID" disabled={saving} value={row.pipe_id} onChange={(event) => updateRow(index, 'pipe_id', event.target.value)} /></td>
              <td><input aria-label="Section reference" disabled={saving} value={row.section_reference || ''} onChange={(event) => updateRow(index, 'section_reference', event.target.value)} /></td>
              <td><input aria-label="Start manhole" disabled={saving} value={row.start_manhole || ''} onChange={(event) => updateRow(index, 'start_manhole', event.target.value)} /></td>
              <td><input aria-label="Finish manhole" disabled={saving} value={row.finish_manhole || ''} onChange={(event) => updateRow(index, 'finish_manhole', event.target.value)} /></td>
              <td><input aria-label="Function" disabled={saving} value={row.function_description || ''} onChange={(event) => updateRow(index, 'function_description', event.target.value)} /></td>
              <td><input aria-label="Length in metres" disabled={saving} type="number" min="0" step="any" value={row.survey_length_m} onChange={(event) => updateRow(index, 'survey_length_m', event.target.value)} /></td>
              <td><input aria-label="Pipe size in millimetres" disabled={saving} type="number" min="1" step="any" value={row.pipe_size_mm || ''} onChange={(event) => updateRow(index, 'pipe_size_mm', event.target.value)} /></td>
              <td><input aria-label="Material code" disabled={saving} value={row.pipe_material_code || ''} onChange={(event) => updateRow(index, 'pipe_material_code', event.target.value)} /></td>
              <td><input aria-label="Condition grade" disabled={saving} type="number" min="0" max="5" step="0.1" value={row.condition_grade || ''} onChange={(event) => updateRow(index, 'condition_grade', event.target.value)} /></td>
              <td><textarea aria-label="Defects and condition" disabled={saving} rows={2} value={row.defects_summary || ''} onChange={(event) => updateRow(index, 'defects_summary', event.target.value)} /></td>
              <td><textarea aria-label="Remarks" disabled={saving} rows={2} value={row.remarks || row.site_environment || ''} onChange={(event) => updateRow(index, 'remarks', event.target.value)} /></td>
              <td><textarea aria-label="Recommendation" disabled={saving} rows={2} value={row.recommendation || ''} onChange={(event) => updateRow(index, 'recommendation', event.target.value)} /></td>
              <td><button type="button" className="icon-button batch-remove-button" disabled={saving} aria-label={`Remove ${row.pipe_id || 'pipe row'}`} title="Remove row" onClick={() => removeRow(index)}><Trash2 size={15} /></button></td>
            </tr>)}</tbody>
          </table></div>
          <div className="batch-actions"><span className="muted">{!ready ? 'Each row needs a pipe ID and a non-negative length.' : 'Saving updates matching pipe IDs and creates new project pipe sections.'}</span><button className="button button-primary" disabled={!ready || saving} onClick={() => void saveReport()}><Upload size={15} /> {saving ? 'Saving…' : `Save ${rows.length} pipe sections`}</button></div>
        </>}
        {textPreview && <details className="wincan-text-preview"><summary>Show extracted PDF text for review</summary><pre>{textPreview}</pre></details>}
      </section>
      <SitePlanUploader projectId={projectId} canUpload={canUpload} onUploaded={() => { setRefreshKey((key) => key + 1); setIframeKey((key) => key + 1); }} />
      <section className="panel report-preview-panel"><div className="panel-heading"><div><div className="eyebrow">HTML PREVIEW / PROJECT-SPECIFIC</div><h2>Preview the generated report</h2></div><a className="button button-quiet button-small" href={htmlUrl} target="_blank" rel="noreferrer"><ExternalLink size={14} /> Open HTML</a></div><div className="report-frame"><iframe key={iframeKey} title="Project CCTV survey report HTML preview" src={htmlUrl} /></div></section>
      <p className="footnote">The generated PDF includes only the cover pages, imported pipe summaries, recommendations, conclusion and appendices page. No videos are uploaded or analyzed.</p>
    </>}
  </div>;
}
