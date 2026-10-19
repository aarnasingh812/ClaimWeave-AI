import {useEffect,useRef,useState} from 'react';
import {X} from 'lucide-react';
import {api} from './api';
import type {Document} from './types';

export default function DocumentPreview({claimId,document,onClose}:{claimId:string;document:Document;onClose:()=>void}){
 const dialog=useRef<HTMLDialogElement>(null);const[url,setUrl]=useState('');const[error,setError]=useState('');
 useEffect(()=>{dialog.current?.showModal();return()=>dialog.current?.close()},[]);
 useEffect(()=>{let active=true;let objectUrl='';void api.binary(`/api/v1/claims/${encodeURIComponent(claimId)}/documents/${encodeURIComponent(document.id)}/preview?page=1`).then(blob=>{objectUrl=URL.createObjectURL(blob);if(active)setUrl(objectUrl);else URL.revokeObjectURL(objectUrl)}).catch(e=>{if(active)setError((e as Error).message)});return()=>{active=false;if(objectUrl)URL.revokeObjectURL(objectUrl)}},[claimId,document.id]);
 return <dialog className="document-preview-dialog" ref={dialog} aria-labelledby="preview-title" onCancel={onClose}><div className="panel-head"><div><h2 id="preview-title">{document.original_filename}</h2><p>First page preview. Review all pages after analysis in Prepare claim.</p></div><button type="button" className="btn ghost" autoFocus aria-label="Close document preview" onClick={onClose}><X size={18}/></button></div>{error?<p className="alert error" role="alert">{error}</p>:url?<img src={url} alt="Uploaded document first page"/>:<p role="status">Loading document preview…</p>}</dialog>
}
