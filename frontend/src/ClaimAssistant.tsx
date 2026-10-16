import {useEffect,useRef,useState,type FormEvent} from 'react';
import {LoaderCircle,MessageCircle,Send} from 'lucide-react';
import {api} from './api';
import type {ClaimDetail} from './types';
import './chat.css';

type Message={role:'user'|'assistant';content:string};
export default function ClaimAssistant({claim,disabled=false}:{claim:ClaimDetail;disabled?:boolean}){
 const key=`claimweave-chat-${claim.id}`;
 const[messages,setMessages]=useState<Message[]>(()=>{try{const saved=JSON.parse(sessionStorage.getItem(key)||'null');if(Array.isArray(saved)&&saved.every(m=>['user','assistant'].includes(m.role)&&typeof m.content==='string'))return saved.slice(-20)}catch{}return []});
 const[input,setInput]=useState('');const[asking,setAsking]=useState(false);const[error,setError]=useState('');
 const end=useRef<HTMLDivElement>(null);
 useEffect(()=>{try{sessionStorage.setItem(key,JSON.stringify(messages.slice(-20)))}catch{}},[key,messages]);
 useEffect(()=>{if(messages.length)end.current?.scrollIntoView({behavior:'smooth',block:'nearest'})},[messages,asking]);
 const ask=async(text:string)=>{if(!text.trim()||asking||disabled)return;const history=messages.slice(-10).map(m=>({...m,content:m.content.slice(0,4000)}));setMessages(current=>[...current,{role:'user',content:text}]);setInput('');setError('');setAsking(true);try{const result=await api.chat(claim.id,text,history);setMessages(current=>[...current,{role:'assistant',content:result.message}])}catch(e){setError((e as Error).message);setInput(text)}finally{setAsking(false)}};
 const submit=(event:FormEvent)=>{event.preventDefault();void ask(input.trim())};
 return <section className="panel agent-chat journey-chat" aria-label="Ask your claim assistant">
  <div className="panel-head"><div><h2><MessageCircle size={18}/> Your claim assistant</h2><p>Ask a question while you gather and upload documents.</p></div></div>
  <div className="chat-thread" role="log" aria-live="polite" aria-relevant="additions">
   <div className="chat-message assistant"><small>ClaimWeave</small><p>I’m helping you prepare a claim for {claim.health_intake?.patient_name||'the patient'} at {claim.health_intake?.hospital_name||'your hospital'}. Your checklist is beside this chat. Ask me what a document means, what to check, or what to do if something is unavailable.</p></div>
   {messages.map((message,index)=><div key={index} className={`chat-message ${message.role}`}><small>{message.role==='user'?'You':'ClaimWeave'}</small><p>{message.content}</p></div>)}
   {asking&&<p role="status"><LoaderCircle size={16} className="spin"/> Thinking…</p>}<div ref={end}/>
  </div>
  {!messages.length&&<div className="chat-actions">{['What documents do I need?','How can I avoid document-related rejection?','What if a document is missing?'].map(question=><button className="btn secondary" key={question} disabled={asking||disabled} onClick={()=>void ask(question)}>{question}</button>)}</div>}
  {error&&<p role="alert" className="alert error">{error} Your question is below so you can retry.</p>}
  <form className="chat-composer" onSubmit={submit}><label className="chat-input-label" htmlFor={`question-${claim.id}`}>Ask about your claim</label><div><input id={`question-${claim.id}`} value={input} maxLength={4000} onChange={e=>setInput(e.target.value)} disabled={asking||disabled} placeholder="For example: My hospital bill includes the receipt…"/><button type="submit" className="btn primary" aria-label="Send question" disabled={!input.trim()||asking||disabled}><Send size={17}/></button></div><small>Guidance helps you prepare. Your insurer decides coverage and may request more information.</small></form>
 </section>
}
