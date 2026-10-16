import type {Claim, ClaimInput, ClaimDetail, Document, Workflow, InsurerGuidance, HealthPreparation} from './types';
const API = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
export const authSession = {
  get: () => sessionStorage.getItem('claimweave_token'),
  set: (token:string) => sessionStorage.setItem('claimweave_token', token),
  clear: () => sessionStorage.removeItem('claimweave_token'),
};
async function request<T>(path:string, init?:RequestInit):Promise<T>{
  const headers = new Headers(init?.headers);
  if(authSession.get()) headers.set('Authorization', `Bearer ${authSession.get()}`);
  init = {...init, headers};
  let response:Response;
  try {response=await fetch(`${API}${path}`, init);} catch {throw new Error('Cannot connect to the API. Is FastAPI running?');}
  if(!response.ok){let message=`Request failed (${response.status})`;
    try {const body:unknown=await response.json(); if(body && typeof body==='object' && 'detail' in body){const d=(body as {detail:unknown}).detail;message=typeof d==='string'?d:Array.isArray(d)?d.map(item=>typeof item==='object'&&item!==null&&'msg' in item?String(item.msg).replace(/^Value error, /,''):'Invalid claim details').join('; '):JSON.stringify(d);}}catch{}
    throw new Error(message);
  }
  if(response.status===204)return undefined as T;
  return response.json() as Promise<T>;
}
export const api={
  planPreparation:(id:string)=>request<{result:HealthPreparation}>(`/api/v1/claims/${encodeURIComponent(id)}/preparation/plan`,{method:'POST'}),
  preparation:(id:string)=>request<{result:HealthPreparation}>(`/api/v1/claims/${encodeURIComponent(id)}/preparation`),
  analyzePreparation:(id:string)=>request<{result:HealthPreparation}>(`/api/v1/claims/${encodeURIComponent(id)}/preparation/analyze`,{method:'POST'}),
  updatePreparation:(id:string,data:Record<string,unknown>)=>request<{result:HealthPreparation}>(`/api/v1/claims/${encodeURIComponent(id)}/preparation`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}),
  reviewDocument:(id:string,documentId:string,data:Record<string,unknown>)=>request<{result:HealthPreparation}>(`/api/v1/claims/${encodeURIComponent(id)}/documents/${encodeURIComponent(documentId)}/review`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}),
  approvePreparation:(id:string,revision:number,approved:boolean)=>request<{result:HealthPreparation}>(`/api/v1/claims/${encodeURIComponent(id)}/preparation/approve`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_revision:revision,approved})}),
  binary:async(path:string)=>{const response=await fetch(`${API}${path}`,{headers:{Authorization:`Bearer ${authSession.get()||''}`}});if(!response.ok){let message='Could not download this file';try{message=(await response.json()).detail||message}catch{}throw new Error(message)}return response.blob()},
  register:(email:string,password:string)=>request<{access_token:string}>('/api/v1/auth/register',{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password})}),
  login:(email:string,password:string)=>request<{access_token:string}>('/api/v1/auth/login',{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password})}),
  me:()=>request<{id:string,email:string}>('/api/v1/auth/me'),
  claims:()=>request<Claim[]>('/api/v1/claims'),
  insurers:()=>request<InsurerGuidance[]>('/api/v1/health/insurers'),
  updateIntake:(id:string,data:ClaimInput)=>request<Claim>(`/api/v1/claims/${encodeURIComponent(id)}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}),
  deleteClaim:(id:string)=>request<void>(`/api/v1/claims/${encodeURIComponent(id)}`,{method:'DELETE'}),
  deleteDocument:(claimId:string,documentId:string)=>request<void>(`/api/v1/claims/${encodeURIComponent(claimId)}/documents/${encodeURIComponent(documentId)}`,{method:'DELETE'}),
  claim:(id:string)=>request<ClaimDetail>(`/api/v1/claims/${encodeURIComponent(id)}`),
  create:(data:ClaimInput)=>request<Claim>('/api/v1/claims',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}),
  upload:(id:string,file:File,kind:'policy'|'supporting',document_type:string)=>{const data=new FormData();data.append('file',file);data.append('kind',kind);data.append('document_type',document_type);return request<Document>(`/api/v1/claims/${encodeURIComponent(id)}/documents`,{method:'POST',body:data});},
  discover:(id:string)=>request<{supported_insurer:boolean;official_domains:string[];candidates:Array<{title:string;url:string;domain:string}>;message:string}>(`/api/v1/claims/${encodeURIComponent(id)}/policy/discover`),
  policySupport:(id:string)=>request<{supported_insurer:boolean;official_domains:string[]}>(`/api/v1/claims/${encodeURIComponent(id)}/policy/support`),
  confirmPolicy:(id:string,url:string)=>request<{status:string;source_url:string}>(`/api/v1/claims/${encodeURIComponent(id)}/policy/confirm`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url,confirmed_policy_match:true})}),
  start:(id:string)=>request<Workflow>(`/api/v1/claims/${encodeURIComponent(id)}/workflow/start`,{method:'POST'}),
  chat:(id:string,message:string,history:Array<{role:'user'|'assistant';content:string}>)=>request<{message:string}>(`/api/v1/claims/${encodeURIComponent(id)}/workflow/chat`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,history})}),
  workflow:(id:string)=>request<Workflow>(`/api/v1/claims/${encodeURIComponent(id)}/workflow`),
  review:(id:string,approved:boolean)=>request<Workflow>(`/api/v1/claims/${encodeURIComponent(id)}/workflow/review`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approved})}),
  export:(id:string)=>request<Record<string,unknown>>(`/api/v1/claims/${encodeURIComponent(id)}/workflow/export`),
};
