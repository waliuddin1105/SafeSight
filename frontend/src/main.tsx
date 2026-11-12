import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {ShieldCheck, Radio, Upload, ArrowUpRight, Check, X, Camera, Activity} from 'lucide-react';
import './style.css';

type Row = Record<string, any>;
const labels: Row = {body_state:'Body state',phone_usage:'Phone usage',cigarette_smoking:'Smoking',entrance_guard:'Entrance check',fire_smoke:'Fire & smoke'};
let csrf = '';
async function api(path: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers);
  if (options.body && typeof options.body === 'string') headers.set('Content-Type','application/json');
  if (options.method && options.method !== 'GET') headers.set('X-CSRF-Token',csrf);
  const response = await fetch('/api/v1'+path,{...options,headers,credentials:'same-origin'});
  const data = await response.json();
  if (!response.ok) throw Object.assign(new Error(data.error?.message || 'Request failed'),{status:response.status});
  return data;
}
function App() {
  const [user,setUser]=useState<Row|null>(null), [loading,setLoading]=useState(true), [error,setError]=useState('');
  const [sources,setSources]=useState<Row[]>([]), [locations,setLocations]=useState<Row[]>([]), [models,setModels]=useState<Row>({});
  const [incidents,setIncidents]=useState<Row[]>([]), [total,setTotal]=useState(0), [page,setPage]=useState(1), [selected,setSelected]=useState<Row|null>(null);
  const [filter,setFilter]=useState({type:'',location:'',status:'',from:'',to:''}), [sourceId,setSourceId]=useState('');
  const [live,setLive]=useState(false), [job,setJob]=useState<Row|null>(null), [busy,setBusy]=useState(false), [notes,setNotes]=useState('');
  const video=useRef<HTMLVideoElement>(null), stream=useRef<MediaStream|null>(null), running=useRef(false), captureGeneration=useRef(0);
  const [workerAlive,setWorkerAlive]=useState(false);
  const date=(value:string|null)=>value ? new Date(value).toLocaleString('en-GB',{timeZone:'Asia/Karachi',dateStyle:'medium',timeStyle:'short'}) : 'Capture time unknown';
  const run=async(action:()=>Promise<void>)=>{setError('');try{await action()}catch(e){setError((e as Error).message)}};
  useEffect(()=>{api('/auth/me').then(d=>{csrf=d.csrf_token;setUser(d.user)}).catch(e=>setError(e.message)).finally(()=>setLoading(false));return()=>{running.current=false;stream.current?.getTracks().forEach(t=>t.stop())}},[]);
  async function refresh(){
    const params=new URLSearchParams({page:String(page)});
    Object.entries(filter).forEach(([k,v])=>{if(v)params.set(k,k==='from'||k==='to'?new Date(v).toISOString():v)});
    const [s,l,m,i]=await Promise.all([api('/sources'),api('/locations'),api('/models'),api('/incidents?'+params)]);
    setSources(s.items);setLocations(l.items);setModels(m.items);setWorkerAlive(m.worker_alive);setIncidents(i.items);setTotal(i.total);
    if(job && !['completed','failed'].includes(job.state))setJob(await api('/jobs/'+job.id));
  }
  useEffect(()=>{if(!user)return;let active=true;const poll=()=>refresh().catch(e=>{if(active)setError(e.message)});poll();const timer=setInterval(poll,2000);return()=>{active=false;clearInterval(timer)}},[user,page,filter,job?.id,job?.state]);
  async function login(event:React.FormEvent<HTMLFormElement>){event.preventDefault();const form=new FormData(event.currentTarget);await run(async()=>{const d=await api('/auth/login',{method:'POST',body:JSON.stringify(Object.fromEntries(form))});csrf=d.csrf_token;setUser(d.user)})}
  async function stop(){running.current=false;captureGeneration.current++;stream.current?.getTracks().forEach(t=>t.stop());stream.current=null;if(video.current)video.current.srcObject=null;setLive(false);if(sourceId)await api('/sources/'+sourceId+'/stop',{method:'POST'})}
  async function start(){
    if(!sourceId)throw new Error('Select a camera source first');
    const source=sources.find(s=>s.id===sourceId);
    if(source?.kind!=='browser'){await api('/sources/'+sourceId+'/start',{method:'POST'});setLive(true);return}
    const media=await navigator.mediaDevices.getUserMedia({video:{width:{ideal:1280},height:{ideal:720}},audio:false});
    try{await api('/sources/'+sourceId+'/start',{method:'POST'})}catch(e){media.getTracks().forEach(t=>t.stop());throw e}
    stream.current=media;running.current=true;setLive(true);
    const generation=++captureGeneration.current;
    if(video.current){video.current.srcObject=media;await video.current.play()}
    const canvas=document.createElement('canvas');let sequence=0;
    const capture=async()=>{
      if(!running.current || generation!==captureGeneration.current)return;
      try{if(video.current?.videoWidth){canvas.width=video.current.videoWidth;canvas.height=video.current.videoHeight;canvas.getContext('2d')!.drawImage(video.current,0,0);const blob=await new Promise<Blob|null>(resolve=>canvas.toBlob(resolve,'image/jpeg',.8));if(blob)await api('/sources/'+sourceId+'/frames',{method:'POST',headers:{'Content-Type':'image/jpeg','X-Sequence':String(sequence++),'X-Capture-Ms':String(performance.now())},body:blob})}}
      catch(e){setError((e as Error).message);if([401,403,409].includes((e as Error & {status:number}).status)){running.current=false;captureGeneration.current++;stream.current?.getTracks().forEach(t=>t.stop());stream.current=null;setLive(false)}}
      if(running.current && generation===captureGeneration.current)setTimeout(capture,200);
    };capture();
  }
  async function upload(event:React.FormEvent<HTMLFormElement>){event.preventDefault();setBusy(true);const form=new FormData(event.currentTarget);await run(async()=>setJob(await api('/uploads',{method:'POST',body:form})));setBusy(false)}
  async function review(decision:string){if(!selected)return;await run(async()=>{await api('/incidents/'+selected.id+'/review',{method:'POST',body:JSON.stringify({decision,notes})});setSelected(await api('/incidents/'+selected.id));await refresh()})}
  if(loading)return <div className="signin"><ShieldCheck size={44}/><p>Connecting to SafeSight…</p></div>;
  if(!user)return <main className="signin"><div className="brand"><ShieldCheck/>SafeSight<span>OPERATIONS</span></div><h1>A clearer view<br/>of workplace safety.</h1><p>Sign in to monitor sources and review incidents.</p><form onSubmit={login}><label>Username<input name="username" autoComplete="username" required/></label><label>Password<input name="password" type="password" autoComplete="current-password" required/></label><button>Sign in <ArrowUpRight size={18}/></button></form>{error&&<p role="alert" className="error">{error}</p>}</main>;
  return <div className="shell"><aside><div className="brand"><ShieldCheck/>SafeSight</div><small>SAFETY OPERATIONS / 01</small><a href="#incidents" className="nav">Incident desk <ArrowUpRight size={16}/></a><a href="#capture" className="nav">Source control <Radio size={16}/></a><div className="aside-bottom"><p>Human judgment.<br/>Supported by sight.</p><small>{user.username} · {user.role}</small><button className="ghost" onClick={()=>run(async()=>{if(live)await stop();await api('/auth/logout',{method:'POST'});setUser(null);const d=await api('/auth/me');csrf=d.csrf_token})}>Sign out</button></div></aside>
  <main><header><span><i/> SAFESIGHT / MONITOR & REVIEW</span><span>Karachi · UTC+05:00</span></header><section className="intro"><div><p className="eyebrow">YOUR SAFETY DESK</p><h1>See what needs<br/><em>your attention.</em></h1></div><div className="count"><strong>{total.toString().padStart(2,'0')}</strong><span>incidents matching<br/>your filters</span></div></section>
  {error&&<div className="error" role="alert">{error}<button aria-label="Dismiss error" onClick={()=>setError('')}><X size={16}/></button></div>}
  {!workerAlive&&<p className="error" role="status">Inference worker is offline. Captured frames cannot be analyzed until it reconnects.</p>}
  {workerAlive&&models.fusion&&!models.fusion.ready&&<p className="muted">Smoke-source fusion awaits joint validation. Unresolved smoke remains reviewable.</p>}
  <section className="health" aria-label="Model readiness">{Object.keys(labels).map(slug=><div key={slug}><span className={'dot '+(models[slug]?.ready?'ok':'')}/><span>{labels[slug]}<small>{models[slug]?.ready?(models[slug]?.evaluation_only?'Evaluation only':'Ready'):'Unavailable'}</small></span></div>)}</section>
  <section id="incidents"><div className="section-head"><h2>Incident register</h2><span>Evidence first. Review with context.</span></div><div className="filters">{(['type','location','status'] as const).map(k=><label key={k}>{k}<select aria-label={k+' filter'} value={filter[k]} onChange={e=>{setPage(1);setFilter({...filter,[k]:e.target.value})}}><option value="">All {k==='type'?'behaviors':k==='location'?'locations':'statuses'}</option>{(k==='type'?Object.entries(labels):k==='location'?locations.map(l=>[l.id,l.name]):['pending','confirmed','dismissed'].map(s=>[s,s])).map(([v,n])=><option key={v} value={v}>{n}</option>)}</select></label>)}{(['from','to'] as const).map(k=><label key={k}>{k}<input type="datetime-local" value={filter[k]} onChange={e=>{setPage(1);setFilter({...filter,[k]:e.target.value})}}/></label>)}</div>
  <div className="table-wrap"><table><thead><tr><th>Behavior / evidence</th><th>Recorded</th><th>Location</th><th>Confidence</th><th>Review</th><th/></tr></thead><tbody>{incidents.map(item=><tr key={item.id}><td><b>{labels[item.slug]}</b><small>{item.subtype.replaceAll('_',' ')}{item.uncertain?' · uncertain':''}{item.evaluation_only?' · evaluation':''}</small></td><td>{date(item.start_at)}<small>Video +{item.start_offset.toFixed(1)}s</small></td><td>{locations.find(l=>l.id===item.location_id)?.name || "Unknown location"}</td><td>{Math.round(item.score*100)}%</td><td><span className={'badge '+item.review_status}>{item.review_status}</span></td><td><button className="ghost" onClick={()=>run(async()=>{setSelected(await api('/incidents/'+item.id));setNotes('')})}>Review <ArrowUpRight size={16}/></button></td></tr>)}</tbody></table>{!incidents.length&&<div className="empty"><ShieldCheck size={32}/><h3>No incidents in this view</h3><p>Adjust the filters or connect a source. Model availability is shown above.</p></div>}</div><div className="pagination"><button className="ghost" disabled={page===1} onClick={()=>setPage(page-1)}>Previous</button><span>Page {page}</span><button className="ghost" disabled={page*25>=total} onClick={()=>setPage(page+1)}>Next</button></div></section>
  <section className="capture-grid" id="capture"><article><div className="section-head"><h2><Camera size={20}/> Live source</h2><span>{live?'CAPTURING':'STANDBY'}</span></div><video ref={video} muted playsInline aria-label="Local camera preview"/><select aria-label="Live source" disabled={live} value={sourceId} onChange={e=>setSourceId(e.target.value)}><option value="">Select camera source</option>{sources.filter(s=>s.kind!=='upload').map(s=><option value={s.id} key={s.id}>{s.name}</option>)}</select><button onClick={()=>run(live?stop:start)}>{live?'Stop capture':'Start capture'} <Radio size={17}/></button><p className="muted">Camera permission is requested when you start. Audio is disabled.</p>{sources.filter(s=>s.active).map(s=><p key={s.id} className="muted">{s.name}: {s.health?.status} · {s.health?.dropped_frames||0} dropped frames</p>)}</article>
  <article><div className="section-head"><h2><Upload size={20}/> Recorded footage</h2></div><form onSubmit={upload}><label>Upload source<select name="source_id" required><option value="">Select source</option>{sources.filter(s=>s.kind==='upload').map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label><label>Video recording<input name="file" type="file" accept="video/*,.mkv" required/></label><button disabled={busy}>{busy?'Uploading…':'Queue recording'} <ArrowUpRight size={17}/></button></form>{job&&<div className="job"><Activity size={18}/><span>{job.state} · {Math.max(0,job.cursor).toFixed(1)} / {job.duration.toFixed(1)} seconds{job.error&&<small>{job.error}</small>}</span></div>}</article></section>
  {user.role==='admin'&&<section className="setup"><h2>Workspace setup</h2><form onSubmit={e=>{e.preventDefault();const form=new FormData(e.currentTarget);run(async()=>{await api('/locations',{method:'POST',body:JSON.stringify({name:form.get('name')})});await refresh()})}}><label>New location<input name="name" required maxLength={120}/></label><button>Add location</button></form><form onSubmit={e=>{e.preventDefault();const form=new FormData(e.currentTarget);run(async()=>{await api('/sources',{method:'POST',body:JSON.stringify(Object.fromEntries(form))});await refresh()})}}><label>Source name<input name="name" required maxLength={120}/></label><label>Location<select name="location_id" required>{locations.map(l=><option key={l.id} value={l.id}>{l.name}</option>)}</select></label><label>Input<select name="kind"><option value="browser">Browser camera</option><option value="upload">Recording upload</option><option value="usb">Server USB camera</option></select></label><button>Add source</button></form></section>}
  <footer>SAFESIGHT <span>AI observations require human review.</span></footer></main>
  {selected&&<div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-label="Incident review"><button className="close ghost" autoFocus onClick={()=>setSelected(null)} aria-label="Close review"><X/></button><p className="eyebrow">INCIDENT EVIDENCE</p><h2>{labels[selected.slug]}</h2><p>{date(selected.start_at)} · {selected.review_status}</p>{selected.evaluation_only&&<p className="error">Evaluation artifact: this result is not qualified for production.</p>}{!selected.evidence.length&&<p className="muted">Evidence is unavailable for this incident.</p>}{selected.evidence.map((e:Row)=><div key={e.id}>{e.state==='ready'?(e.kind==='frame'?<img src={e.url} alt="Incident evidence frame"/>:<video controls src={e.url}/>):<p>Evidence {e.state}{e.error?': '+e.error:''}</p>}</div>)}<label>Review notes<textarea value={notes} onChange={e=>setNotes(e.target.value)} maxLength={4000}/></label><div className="actions"><button onClick={()=>review('confirmed')}><Check size={18}/> Confirm</button><button className="ghost" onClick={()=>review('dismissed')}><X size={18}/> Dismiss</button></div><small>{selected.reviews.length} recorded reviews</small></section></div>}</div>;
}
createRoot(document.getElementById('root')!).render(<App/>);
