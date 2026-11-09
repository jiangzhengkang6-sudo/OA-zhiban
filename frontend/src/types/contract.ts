export interface ContractEvidence { paragraph: number; page?: number | null; start: number; end: number; quote: string }
export interface ContractRisk { risk_id: string; name?: string; title?: string; severity: string; missing: boolean; suggestion: string; source?: string; evidence: ContractEvidence }
export interface ContractDraft { summary: string; analysis_engine: string; rule_version: string; risks: ContractRisk[]; observations: { paragraph: number; quote: string; suggestion: string }[] }
export interface ContractSummary { contract_id: string; title: string; status: string; version: number; reviewer_id: string }
export interface ContractResponse extends ContractSummary {
  reviewer_name?: string;
  thread_id: string; owner_id: string; available_actions: string[]; source_id: string; source_hash: string;
  source_text: string; paragraphs: ContractEvidence[]; scan_status: string; node_trace: string[]; draft: ContractDraft | null;
  confirmation: { actor_id: string; version: number; action: string; comment: string; dispositions: RiskDecision[] } | null;
  error: { message: string; trace_id: string } | null;
}
export interface RiskDecision { risk_id: string; action: 'accepted' | 'mitigated' | 'needs_revision'; comment: string }
export interface ContractVersion { version: number; draft: ContractDraft; edited_by?: string | null; created_at: string }
export interface ContractPayload { title: string; reviewer_id: string; text: string; idempotency_key: string }
export interface ContractCommand { action: string; expected_version: number; idempotency_key: string; summary?: string; comment?: string; dispositions?: RiskDecision[] }
