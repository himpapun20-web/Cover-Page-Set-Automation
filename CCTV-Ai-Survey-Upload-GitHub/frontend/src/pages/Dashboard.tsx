import { useEffect, useState } from 'react';
import { ArrowUpRight, Files, GitBranch, RefreshCw } from 'lucide-react';
import { Link } from 'react-router-dom';
import { api, type DashboardData } from '../lib/api';

const readable = (value: string) => value.replaceAll('_', ' ').toLowerCase().replace(/\b\w/g, (char) => char.toUpperCase());

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  async function load() {
    setLoading(true); setError('');
    try { setData(await api.dashboard()); } catch (e) { setError((e as Error).message); } finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);
  return <div className="page-stack dashboard-page">
    <section className="page-heading"><div><div className="eyebrow">PROJECT CONTROL / SURVEYS</div><h1>Project overview</h1><p>Manage project details, import WinCan VX PDF reports and generate concise survey reports.</p></div><button className="button button-quiet" onClick={() => void load()}><RefreshCw size={15} /> Refresh</button></section>
    {error && <div className="alert alert-error">{error}{error.includes('Sign in') && <a href="/api/auth/login"> Sign in</a>}</div>}
    <section className="metric-row">
      <article className="metric-card"><span className="metric-label"><Files size={15} /> Projects</span><strong>{loading ? '—' : data?.totals.projects ?? 0}</strong><span className="metric-note">Projects on record</span></article>
      <article className="metric-card"><span className="metric-label"><GitBranch size={15} /> Pipe Sections</span><strong>{loading ? '—' : data?.totals.pipe_sections ?? 0}</strong><span className="metric-note">Sections across projects</span></article>
      <article className="metric-card"><span className="metric-label"><Files size={15} /> Reports generated</span><strong>{loading ? '—' : data?.projects.filter((project) => project.report_status === 'GENERATED' || project.report_status === 'FINALIZED').length ?? 0}</strong><span className="metric-note">Projects with generated reports</span></article>
    </section>
    <section className="panel"><div className="panel-heading"><div><div className="eyebrow">REGISTER / PROJECTS</div><h2>Projects</h2></div><Link className="button button-primary button-small" to="/projects">Manage projects <ArrowUpRight size={14} /></Link></div>
      {loading ? <div className="empty-state">Loading project data…</div> : !data?.projects.length ? <div className="empty-state">No project records yet.</div> : <div className="table-scroll"><table><thead><tr><th>Project</th><th>Client / Location</th><th>WinCan Sections</th><th>Project Status</th><th>Report Status</th><th></th></tr></thead><tbody>{data.projects.map((project) => <tr key={project.id}><td><strong>{project.project_name}</strong><span className="table-sub mono">{project.project_code}</span></td><td>{project.client_name || '—'}<span className="table-sub">{project.location || '—'}</span></td><td className="mono">{project.pipe_section_count}</td><td><span className={`status-pill status-${project.status.toLowerCase()}`}>{readable(project.status)}</span></td><td><span className={`status-pill status-${project.report_status.toLowerCase()}`}>{readable(project.report_status)}</span></td><td><Link className="button button-quiet button-small" title="Open this project's report workflow" to={`/report/${project.id}`}>Open report <ArrowUpRight size={14} /></Link></td></tr>)}</tbody></table></div>}
    </section>
    <section className="status-grid"><article className="panel status-panel"><div className="eyebrow">PIPE SECTIONS</div><h2>Imported section status</h2><div className="status-list">{Object.entries(data?.pipe_sections_by_status ?? {}).map(([key, count]) => <div key={key}><span><i className={`status-dot dot-${key.toLowerCase()}`} />{readable(key)}</span><strong>{count}</strong></div>)}{!Object.keys(data?.pipe_sections_by_status ?? {}).length && <p className="muted">No pipe sections</p>}</div></article><article className="panel status-panel"><div className="eyebrow">REPORTS</div><h2>Report status</h2><div className="status-list">{Object.entries((data?.projects ?? []).reduce<Record<string, number>>((counts, project) => { counts[project.report_status] = (counts[project.report_status] || 0) + 1; return counts; }, {})).map(([key, count]) => <div key={key}><span><i className={`status-dot dot-${key.toLowerCase()}`} />{readable(key)}</span><strong>{count}</strong></div>)}{!data?.projects.length && <p className="muted">No project reports</p>}</div></article></section>
    <p className="footnote">Pipe data and defect summaries come from reviewed WinCan VX report imports. The application does not analyze videos or detect defects.</p>
  </div>;
}
