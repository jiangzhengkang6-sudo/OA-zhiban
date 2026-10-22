export interface Named { id:string; name:string }
export interface Options { departments:Named[]; users:Named[]; roles:Named[] }
export interface Command { operation_id:string; expected_revision:number }
export interface Outcome<T> { result:T; replayed:boolean; current_revision?:number; allowed_actions?:string[] }
export interface LeaveFields { leave_type:string; start_date:string; end_date:string; reason:string; attachment_ids:string[] }
export interface Attachment { id?:string; attachment_id?:string; filename:string; scan_status?:string; status?:string }
export interface Leave {
  id:string; business_no:string; applicant_id:string; workflow_definition_id:string; revision:number; submission_version:number;
  state:string; fields:LeaveFields; allowed_actions:string[]; archived_at?:string|null; pause_reason?:string|null;
  attachments?:Attachment[]; versions?:{version:number; fields:LeaveFields; attachments:Attachment[]; differences:Record<string,{before:unknown;after:unknown}>}[];
  history?:{action:string;note?:string;reason_code?:string;created_at:string;corrections?:string[]}[]
}
export interface Selector { kind:'manager'|'users'|'role'; levels?:number; user_ids?:string[]; role_id?:string }
export interface WorkflowNode { id:string;kind:'approval'|'cc'|'branch'|'end';mode?:'single'|'all'|'any';selector?:Selector;next_id?:string;cases?:{field:string;op:string;value:unknown;next_id:string}[];default_next_id?:string }
export interface Definition {schema_version:1;scene:'leave'|'reimbursement';entry_id:string;form:{leave_types?:string[];reason_max_length:number;reimbursement_categories?:string[]};rules:{timeout_hours:number;required_attachments:string[];calendar:'inclusive_days'};nodes:WorkflowNode[]}
export interface Workflow {id:string;name:string;published_version:number;revision:number;department_id:string;code:string;definition:Definition;form?:Definition['form']}
export interface Approval {node_id:string;business_no:string;scene?:'leave'|'reimbursement';revision:number;submission_version:number;state:string;seat_state:string;decision_note?:string;due_at?:string;fields?:LeaveFields|ReimbursementFields;attachments?:Attachment[];allowed_actions?:string[];approval_notes?:{approval_note?:string;note?:string}[]}
export interface Balance {id:string;user_id:string;year:number;leave_type:string;total:number;used:number;reserved:number;available:number;revision:number}
export interface Seat {id:string;original_user_id:string;effective_user_id:string;effective_user_name?:string;state:string;substituted:boolean;escalated:boolean}
export interface Instance {instance_id:string;business_no:string;state:string;pause_reason:string|null;revision:number;route_revision:number;nodes:{id:string;ordinal:number;kind:string;mode:string;state:string;revision:number;seats:Seat[]}[]}
export interface Reconciliation {ok:boolean;checked:number;read_only:boolean;issues:{leave_id:string;code:string}[]}

export interface ReimbursementFields { purpose:string; expense_date:string; category:string; amount:string; currency:'CNY'; attachment_ids:string[] }
export interface Reimbursement { id:string; scene:'reimbursement'; business_no:string; applicant_id:string; department_id:string; workflow_definition_id:string; fields:ReimbursementFields; revision:number; submission_version:number; state:string; archived_at:string|null; allowed_actions:string[]; attachments?:Attachment[]; versions?:{version:number; fields:ReimbursementFields; amount_minor:number; currency:string; attachments:Attachment[]; differences:Record<string,unknown>}[]; history?:Record<string,unknown>[]; pause_reason?:string|null }
export interface FormalTicket { id:string; business_no:string; owner_id:string; department_id:string; revision:number; state:string; category:string; priority:string; impact:string; summary:string; queue:string|null; assignee_id:string|null; assignment_error:string|null; resolution_note:string|null; merged_requests?:Record<string,unknown>[]; feedback?:Record<string,unknown>[] }
export interface NotificationItem { id:string; title:string; created_at:string; read_at:string|null; source_kind:string; object_id:string|null; instance_id:string|null; resource:string|null; inbox_state:string; smtp_state:string; wecom_state?:string|null; delivered:boolean }
export interface NotificationDelivery { id:string; notification_id:string; recipient_id:string; channel:'smtp'|'wecom'; state:string; attempt_count:number; last_code:string|null; next_attempt_at:string|null; reviews:{note:string;reviewer_id:string;created_at:string}[] }
