import {useEffect, useRef, useState, type FormEvent} from 'react';
import {MessageCircle, Send, Sparkles, LoaderCircle, ArrowRight} from 'lucide-react';
import {api} from './api';
import type {ClaimDetail, Workflow} from './types';
import './chat.css';

type Message = {role: 'user' | 'assistant'; content: string};
const stages: Record<string, string> = {
  acquire: 'Reading your policy PDF', extract_policy: 'Finding requirements in your policy',
  verify: 'Checking the policy identity', classify: 'Understanding your claim',
  requirements: 'Preparing your document checklist', extract_documents: 'Reading supporting documents',
  check_documents: 'Checking which documents are missing', draft: 'Preparing your draft',
  validate: 'Validating the draft', review: 'Preparing your review', finalize: 'Preparing your export',
};
function summary(workflow: Workflow): string {
  const result = workflow.result;
  if (!result.validation && result.status !== 'policy_mismatch') return 'Analysis is not complete yet. Start or retry analysis to prepare your checklist.';
  if (result.status === 'policy_mismatch') return 'The policy identity does not match your claim details. Please check the policy name and insurer, replace the policy in Documents if needed, and retry analysis.';
  const check = result.document_check;
  const lines = [result.policy_verified ? 'I have checked your policy and prepared your checklist.' : 'Your provisional draft is ready. Attach a matching policy before approval and export.'];
  if (check?.missing.length) lines.push('Missing: ' + check.missing.join(', ') + '.');
  if (check?.needs_confirmation.length) lines.push('Please confirm: ' + check.needs_confirmation.join(', ') + '.');
  if (result.validation?.errors.length) lines.push(...result.validation.errors);
  if (workflow.workflow_status === 'awaiting_review') lines.push('Your draft is ready for your review. Open Review & export to inspect and approve it.');
  return lines.join('\n\n');
}

export default function AgentChat({claim, workflow, onWorkflow, onDocuments, onChecklist, onReview}: {
  claim: ClaimDetail; workflow: Workflow | null; onWorkflow: (value: Workflow) => Promise<void>;
  onDocuments: () => void; onChecklist: () => void; onReview: () => void;
}) {
  const [messages, setMessages] = useState<Message[]>([{role: 'assistant', content:
    `Hi, I’m your ClaimWeave assistant. I’ll help you prepare your ${claim.policy_name} claim. You have ${claim.documents.length} document(s) attached. Start analysis when you’re ready, or ask me about the preparation process.`}]);
  const [input, setInput] = useState('');
  const [working, setWorking] = useState(false);
  const [asking, setAsking] = useState(false);
  const [progress, setProgress] = useState('Starting your analysis');
  const end = useRef<HTMLDivElement>(null);
  const mounted = useRef(true);
  useEffect(() => {mounted.current = true; return () => {mounted.current = false;};}, []);
  const running = working || claim.status === 'running';
  const intakeReady = !claim.health_intake || (claim.health_intake.intake_completed && !claim.intake_missing?.length);
  const cashless = claim.health_intake?.claim_route === 'cashless';
  const canStart = !['running','reviewing'].includes(claim.status) && intakeReady && !cashless;
  useEffect(() => {
    setMessages(previous => previous.length === 1 ? [{role: 'assistant', content:
      `Hi, I’m your ClaimWeave assistant. I’ll help you prepare your ${claim.policy_name} claim. You have ${claim.documents.length} document(s) attached. Start analysis when you’re ready, or ask me about the preparation process.`}] : previous);
  }, [claim.policy_name, claim.documents.length]);
  useEffect(() => {end.current?.scrollIntoView({behavior: 'smooth', block: 'nearest'});}, [messages, progress, asking]);
  useEffect(() => {
    if (!running) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        let value: Workflow = {workflow_status: 'running', next_nodes: [], interrupts: [], result: {}};
        try {value = await api.workflow(claim.id);} catch { /* Check the claim even without a checkpoint. */ }
        if (cancelled) return;
        const node = value.next_nodes[0];
        if (node && stages[node]) setProgress(stages[node]);
        const current = await api.claim(claim.id);
        if (cancelled) return;
        if (!working && current.status !== 'running') {
          await onWorkflow(value);
          if (!cancelled) setMessages(previous => [...previous, {role: 'assistant', content: current.status === 'workflow_error' ? 'Analysis could not finish. You can retry or update your documents.' : summary(value)}]);
          return;
        }
      } catch { /* The first checkpoint may not exist yet. */ }
      if (!cancelled) timer = setTimeout(poll, 4000);
    };
    void poll();
    return () => {cancelled = true; clearTimeout(timer);};
  }, [running, working, claim.id]);

  const start = async (request = 'Please analyze my claim and uploaded documents.') => {
    if (running || asking || !canStart) return;
    setMessages(previous => [...previous, {role: 'user', content: request}]);
    setWorking(true); setProgress('Starting your analysis');
    try {
      const value = await api.start(claim.id);
      if (!mounted.current) return;
      await onWorkflow(value);
      setMessages(previous => [...previous, {role: 'assistant', content: summary(value)}]);
    } catch (error) {
      if (!mounted.current) return;
      setMessages(previous => [...previous, {role: 'assistant', content: `${(error as Error).message} You can retry analysis or check your documents.`}]);
      // Refresh the claim status even when no checkpoint was created.
      try {await onWorkflow(await api.workflow(claim.id));} catch {await onWorkflow({workflow_status: 'error', next_nodes: [], interrupts: [], result: {}});}
    } finally {setWorking(false);}
  };
  const ask = async (event: FormEvent) => {
    event.preventDefault();
    const text = input.trim();
    if (!text || asking || running) return;
    if (canStart && /^(please\s+)?(start|run|retry|analy[sz]e)\b.*\b(analysis|agent|claim|documents|pdfs)\b[.!?]?$/i.test(text)) {
      setInput('');
      await start(text);
      return;
    }
    const history = messages.slice(-10).map(message => ({...message, content: message.content.slice(0, 4000)}));
    setMessages(previous => [...previous, {role: 'user', content: text}]);
    setInput(''); setAsking(true);
    try {
      const answer = await api.chat(claim.id, text, history);
      setMessages(previous => [...previous, {role: 'assistant', content: answer.message}]);
    } catch (error) {setMessages(previous => [...previous, {role: 'assistant', content: (error as Error).message}]);}
    finally {setAsking(false);}
  };
  return <section className="panel agent-chat" aria-label="Claim assistant">
    <div className="panel-head"><div><h2><MessageCircle size={19}/> ClaimWeave assistant</h2><p>Step 3 · Analyze your documents and discuss the results.</p></div></div>
    {!intakeReady&&<p className="helper" style={{padding:'0 24px'}}>Complete and confirm your health claim details from Overview before starting analysis.</p>}
    {cashless&&<p className="helper" style={{padding:'0 24px'}}>Cashless authorization is handled by your hospital and insurer. Open Insurer guidance for official instructions.</p>}
    <div className="chat-thread" role="log" aria-live="polite" aria-relevant="additions">
      {messages.map((message, index) => <div key={index} className={`chat-message ${message.role}`}><small>{message.role === 'user' ? 'You' : 'ClaimWeave'}</small><p>{message.content}</p></div>)}
      {workflow && !running && messages.length === 1 && <div className="chat-message assistant"><small>Current analysis</small><p>{workflow.result.package ? 'Your approved package is ready to download from Review & export.' : summary(workflow)}</p></div>}
      {(running || asking) && <div className="chat-message assistant chat-progress"><LoaderCircle size={17} className="spin"/><span>{running ? progress + '…' : 'Thinking…'}</span></div>}
      <div ref={end}/>
    </div>
    <div className="chat-actions">
      {canStart && <button className="btn primary" disabled={running || asking} onClick={() => void start()}><Sparkles size={16}/>{claim.status === 'workflow_error' || claim.status === 'policy_mismatch' ? 'Retry analysis' : 'Start analysis'}</button>}
      <button className="btn secondary" onClick={onDocuments}>Documents</button>
      {workflow && <button className="btn secondary" onClick={onChecklist}>View checklist</button>}
      {workflow?.result.form_draft && <button className="btn secondary" onClick={onReview}>Review draft <ArrowRight size={15}/></button>}
    </div>
    <form className="chat-composer" onSubmit={event => void ask(event)}>
      <label className="chat-input-label" htmlFor={`chat-${claim.id}`}>Ask about your claim</label>
      <div><input id={`chat-${claim.id}`} value={input} maxLength={4000} onChange={event => setInput(event.target.value)} placeholder="Ask about missing documents, policy requirements, or next steps…" disabled={running || asking}/><button className="btn primary" type="submit" aria-label="Send message" disabled={!input.trim() || running || asking}><Send size={18}/></button></div>
      <small>{running ? 'You can ask follow-up questions when analysis finishes.' : 'Answers use your claim details and available analysis. Verify them against your original documents.'}</small>
    </form>
  </section>;
}
