export type HealthIntake = {
 patient_name:string|null;patient_dob:string|null;policyholder_name:string|null;relationship:'self'|'spouse'|'child'|'parent'|'other'|null;
 contact_email:string|null;contact_phone:string|null;policy_start_date:string|null;policy_end_date:string|null;policy_edition:string|null;tpa_name:string|null;
 claim_route:'reimbursement'|'cashless'|null;admission_type:'planned'|'emergency'|null;hospital_name:string|null;hospital_city:string|null;
 admission_date:string|null;discharge_date:string|null;treatment:string|null;intimation_status:'not_notified'|'notified'|'unknown'|null;
 intimation_number:string|null;intimation_date:string|null;intake_completed:boolean;
};
export type ClaimInput = {insurer:string;policy_name:string;policy_number:string|null;claim_description:string;health_intake?:HealthIntake|null};
export type Claim = ClaimInput & {id:string;status:string;policy_source_mode:string;policy_source_url:string|null;created_at:string;guidance_version:string|null;intake_missing:string[]};
export type GuidanceNote = {text:string;source_ids:string[]};
export type InsurerGuidance = {
 id:string;name:string;aliases:string[];version:string;last_checked:string;scope:string;
 sources:Array<{id:string;title:string;url:string}>;links:Array<{label:string;url:string}>;
 timelines:Array<GuidanceNote & {label:string;route:'all'|'cashless'|'reimbursement';admission_type?:'planned'|'emergency';conflict?:boolean}>;
 documents:Array<{name:string;source_ids:string[]}>;submission:GuidanceNote;cashless:GuidanceNote;
};
export type Document = {id:string;claim_id:string;kind:'policy'|'supporting';document_type:string;original_filename:string;size_bytes:number;uploaded_at:string};
export type ClaimDetail = Claim & {documents:Document[]};
export type Requirement = {requirement_id:string;name:string;category:string;canonical_document_type:string;mandatory:boolean;condition:string|null;reason:string;evidence_quote:string;source_reference:string;needs_user_confirmation?:boolean};
export type Check = {present:string[];missing:string[];needs_confirmation:string[]};
export type Workflow = {workflow_status:string;next_nodes:string[];interrupts:Array<{kind?:string;message?:string;form_draft?:Record<string,unknown>;validation?:{passed:boolean;errors:string[];warnings:string[]}}>;
result:{status?:string;policy_source_mode?:string;policy_source_url?:string|null;policy_verified?:boolean;policy_extraction?:Record<string,unknown>;claim_classification?:Record<string,unknown>;planned_requirements?:Requirement[];extracted_documents?:Array<{document_id:string;document_type:string;filename:string;fields:Record<string,string|null>;error?:string}>;document_check?:Check;form_draft?:Record<string,unknown>;validation?:{passed:boolean;errors:string[];warnings:string[]};package?:Record<string,unknown>;warnings?:string[]}};
