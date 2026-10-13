import {ExternalLink,ShieldCheck,TriangleAlert} from 'lucide-react';
import type {HealthIntake,InsurerGuidance as Guidance} from './types';

export default function InsurerGuidance({guidance,intake,savedVersion}:{guidance:Guidance|undefined;intake?:HealthIntake|null;savedVersion?:string|null}){
 if(!guidance)return <div className="panel guidance-panel"><div className="form-body"><h2>Insurer guidance</h2><p>Select an insurer to see official forms, document guidance and notification instructions.</p></div></div>;
 const sourceLinks=(ids:string[])=> <div className="guidance-sources">{ids.map(id=>{const source=guidance.sources.find(s=>s.id===id);return source?<a key={id} href={source.url} target="_blank" rel="noopener noreferrer">{source.title} <ExternalLink size={11}/></a>:null})}</div>;
 const timelines=guidance.timelines.filter(t=>(!intake?.claim_route||t.route==='all'||t.route===intake.claim_route)&&(!intake?.admission_type||!t.admission_type||t.admission_type===intake.admission_type));
 const stale=Date.now()-new Date(guidance.last_checked+'T00:00:00+05:30').getTime()>90*86400000;
 return <section className="panel guidance-panel" aria-label={`${guidance.name} guidance`}><div className="panel-head"><div><h2><ShieldCheck size={18}/> {guidance.name} guidance</h2><p>Official sources checked {guidance.last_checked.split('-').reverse().join('/')}</p></div></div><div className="form-body">
 <p className="guidance-scope">{guidance.scope}</p>
 {stale&&<p className="guidance-warning"><TriangleAlert size={16}/> Sources were checked over 90 days ago. Recheck the official pages before using this guidance.</p>}
 {savedVersion&&savedVersion!==guidance.version&&<p className="guidance-warning">Guidance has changed since this intake was saved. Review the current instructions below.</p>}
 <h3>Notification and submission timing</h3>
 {timelines.length?timelines.map(t=><div key={t.label} className={`guidance-note ${t.conflict?'guidance-conflict':''}`}><strong>{t.label}</strong>{!intake?.claim_route&&t.route!=='all'&&<small>{t.route==='cashless'?'Cashless':'Reimbursement'}</small>}<p>{t.text}</p>{sourceLinks(t.source_ids)}</div>):<p>Confirm notification timing directly with your insurer or TPA.</p>}
 {intake?.claim_route==='cashless'?<><h3>Coordinate with your hospital</h3><p>{guidance.cashless.text}</p>{sourceLinks(guidance.cashless.source_ids)}<p className="helper">ClaimWeave does not request cashless authorization. Your hospital and insurer handle it.</p></>:<><h3>Documents to prepare for reimbursement</h3><ul className="guidance-documents">{guidance.documents.map(d=><li key={d.name}>{d.name}{sourceLinks(d.source_ids)}</li>)}</ul><h3>Where to submit</h3><p>{guidance.submission.text}</p>{sourceLinks(guidance.submission.source_ids)}</>}
 <div className="guidance-links">{guidance.links.map(link=><a key={link.url} className="btn secondary" href={link.url} target="_blank" rel="noopener noreferrer">{link.label}<ExternalLink size={14}/></a>)}</div>
 <small className="muted">Guidance version {guidance.version}. Check your actual policy schedule, wording and endorsements; this guidance does not verify coverage.</small>
 </div></section>
}
