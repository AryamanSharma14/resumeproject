import { useState, type FormEvent } from 'react';
import { NavLink, Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import { Activity, Layers, List, Server, Plus, LogOut } from 'lucide-react';
import { queryClient, request, setToken } from './api';
import { ErrorNotice } from './ui';
import { Jobs } from './Jobs';
import { JobDetail } from './JobDetail';
import { Submit } from './Submit';
import { Queues, Workers, System } from './Operations';
import s from './ui.module.css';
export function App() {
  const [authenticated, setAuthenticated] = useState(false);
  const [secret, setSecret] = useState('');
  const [error, setError] = useState<Error | null>(null);
  const [pending, setPending] = useState(false);
  const navigate = useNavigate();
  async function connect(event: FormEvent) {
    event.preventDefault(); if (pending) return; setPending(true); setError(null); setToken(secret.trim());
    try { await request('/handlers'); setAuthenticated(true); setSecret(''); } catch (e) { setToken(''); setError(e as Error); } finally { setPending(false); }
  }
  if (!authenticated) return <main className={s.login}><div className={s.brand}>relay <span>LOCAL</span></div><div className={s.eyebrow}>DURABLE JOB OPERATIONS</div><h1>Connect to your installation.</h1><p>Inspect execution, retries and recovery. Your jobs stay on this machine.</p><form onSubmit={e => void connect(e)}><label>Installation access token<input autoFocus type="password" autoComplete="off" spellCheck={false} value={secret} onChange={e => setSecret(e.target.value)} required/></label><p className={s.muted}>Use the token created by <code>relay init</code>. Held in memory only; refreshing this page disconnects you.</p>{error && <ErrorNotice error={error}/>}<button className={s.primary} disabled={pending || !secret.trim()}>{pending ? 'Connecting…' : 'Connect to Relay'}</button></form><footer>Single host. Trusted built-in handlers. At-least-once execution.</footer></main>;
  return <div className={s.shell}><a className={s.skip} href="#main">Skip to content</a><aside className={s.sidebar}><NavLink className={s.brand} to="/jobs">relay <span>LOCAL</span></NavLink><div className={s.eyebrow}>CONTROL PLANE</div><nav aria-label="Main navigation">{[["/jobs", 'Jobs', List], ['/queues', 'Queues', Layers], ['/workers', 'Workers', Server], ['/system', 'System', Activity]].map(([to, label, Icon]) => { const I = Icon as typeof List; return <NavLink key={String(to)} to={String(to)}><I size={18}/>{String(label)}</NavLink>; })}</nav><div className={s.sidebarFoot}><span>Local installation</span><small>No cloud connection</small><button onClick={() => { void queryClient.cancelQueries(); queryClient.clear(); setToken(''); setAuthenticated(false); }}><LogOut size={16}/> Disconnect</button></div></aside><div className={s.workspace}><div className={s.topbar}><span><span className={s.dot}/>Authenticated · local API</span><button className={s.primary} onClick={() => navigate('/jobs/new')}><Plus size={16}/> Submit job</button></div><main id="main" tabIndex={-1} className={s.main}><Routes><Route path="/jobs" element={<Jobs/>}/><Route path="/jobs/new" element={<Submit/>}/><Route path="/jobs/:id" element={<JobDetail/>}/><Route path="/queues" element={<Queues/>}/><Route path="/queues/:name" element={<Queues/>}/><Route path="/workers" element={<Workers/>}/><Route path="/workers/:id" element={<Workers/>}/><Route path="/system" element={<System/>}/><Route path="/" element={<Navigate replace to="/jobs"/>}/><Route path="*" element={<><h1>Page not found</h1><NavLink to="/jobs">Return to jobs</NavLink></>}/></Routes></main><footer className={s.footer}>RELAY / SINGLE-HOST OPERATIONS<span>At-least-once execution · UTC timestamps</span></footer></div></div>;
}
