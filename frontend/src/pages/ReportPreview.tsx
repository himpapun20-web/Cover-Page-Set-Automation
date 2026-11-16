import { useEffect, useState } from 'react';
import { ArrowLeft, Download, ExternalLink, Files, GitBranch, RefreshCw, Upload } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { api, type ProjectReportData } from '../lib/api';

type Props = { canGenerate: boolean; canUpload: boolean };
const shown = (value: unknown) => value === null || value === undefined || value === '' ? 'Not provided' : String(value);

export default function ReportPreview({ canGenerate, canUpload }: Props) {
  const { projectId } = useParams();
  const [summary, setSummary] = useState<ProjectReportData | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [iframeKey, setIframeKey] = useState(0);
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

  async function importReport(file?: File) {
    if (!projectId || !file) return;
    setImporting(true);
    setError('');
    setNotice('');
    try {
      const result = await api.uploadWincanReport(projectId, file);
      setFileName(file.name);
      setNotice(`Imported and saved ${result.count} pipe section${result.count === 1 ? '' : 's'} from ${result.page_count} PDF pages (${result.created} new, ${result.updated} updated). The HTML and PDF reports now use the imported data.`);
      setIframeKey((value) => value + 1);
      setRefreshKey((value) => value + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setImporting(false);
    }
  }

  function refreshReport() {
    setRefreshKey((key) => key + 1);
    setIframeKey((key) => key + 1);
  }

  if (!projectId) return <div className="alert alert-error">A project identifier is required.</div>;

  return <div className="page-stack report-preview-page">
    <section className="page-heading">
      <div><div className="eyebrow">PROJECT REPORT / WINCAN VX IMPORT</div><h1>Generate project report</h1><p>Upload a WinCan VX PDF to automatically extract and save its pipe rows into the HTML preview and PDF.</p></div>
      <div className="heading-actions"><Link className="button button-quiet" to="/"><ArrowLeft size={15} /> Dashboard</Link><button className="button button-quiet" onClick={refreshReport} disabled={loading}><RefreshCw size={15} /> Refresh report</button>{canGenerate ? <a className="button button-primary" href={pdfUrl}><Download size={15} /> Generate / download PDF</a> : <span className="status-pill">PDF generation requires a Project Manager</span>}</div>
    </section>
    {error && <div className="alert alert-error">{error}{error.includes('Sign in') && <a href="/api/auth/login"> Sign in</a>}</div>}
    {notice && <div className="alert alert-success">{notice}</div>}
    {loading ? <div className="empty-state">Loading project data…</div> : project && <>
      <section className="panel report-project-card">
        <div className="panel-heading"><div><div className="eyebrow">{shown(project.project_code)}</div><h2>{shown(project.project_name)}</h2><p>{shown(project.client_name)} · {shown(project.location)} · Survey dates: {shown(project.survey_start_date)} – {shown(project.survey_end_date)}</p></div><span className={`status-pill status-${String(project.report_status || '').toLowerCase()}`}>{shown(project.report_status).replaceAll('_', ' ')}</span></div>
        <div className="report-steps">
          <Link className="report-step" to="/projects"><span className="step-icon">Project</span><span><strong>Project details</strong><small>Location, survey dates and EUSR certificate number</small></span><b>{project.location && project.survey_start_date ? 'Entered' : 'Review'}</b></Link>
          <Link className="report-step" to="/pipe-sections"><GitBranch size={16} /><span><strong>Pipe sections</strong><small>Saved pipe condition data from WinCan</small></span><b>{summary?.pipe_section_count ?? 0}</b></Link>
          <div className="report-step report-step-static"><Files size={16} /><span><strong>Report output</strong><small>Cover, certificate and WinCan summary tables</small></span><b>Ready to generate</b></div>
        </div>
      </section>
      <section className="panel batch-panel">
        <div className="panel-heading"><div><div className="eyebrow">WINCAN VX / PDF IMPORT</div><h2>Upload and import report</h2><p>Pipe sections are extracted and saved automatically. Scanned PDFs are processed with OCR; no manual row entry or confirmation is needed.</p></div>
          {canUpload && <label className="button button-primary"><Upload size={15} /> {importing ? 'Extracting and saving…' : 'Select WinCan PDF'}<input type="file" accept="application/pdf,.pdf" hidden disabled={importing} onChange={(event) => { void importReport(event.target.files?.[0]); event.currentTarget.value = ''; }} /></label>}
        </div>
        {fileName && <p className="small">Last imported report: <strong>{fileName}</strong></p>}
        {importing && <div className="empty-state">Extracting WinCan data (including OCR where needed) and saving the pipe sections…</div>}
        {canUpload && !importing && <p className="muted">Uploading a report adds new pipe sections and updates matching pipe IDs in this project. The generated report reflects the saved data.</p>}
      </section>
      <section className="panel report-preview-panel"><div className="panel-heading"><div><div className="eyebrow">HTML PREVIEW / PROJECT-SPECIFIC</div><h2>Preview the generated report</h2></div><a className="button button-quiet button-small" href={htmlUrl} target="_blank" rel="noreferrer"><ExternalLink size={14} /> Open HTML</a></div><div className="report-frame"><iframe key={iframeKey} title="Project CCTV survey report HTML preview" src={htmlUrl} /></div></section>
      <p className="footnote">The PDF contains the designed cover and certificate pages followed by the imported WinCan summary tables. No videos are uploaded or analyzed.</p>
    </>}
  </div>;
}
