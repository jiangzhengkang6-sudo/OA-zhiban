export type MetricId = 'ticket_volume' | 'approval_outcomes' | 'work_task_progress'
export interface MetricDefinition { metric_id: MetricId; version: number; name: string; unit: string; definition: string; source: string; time_field: string }
export interface ReportMetric extends MetricDefinition { current: number; previous: number; change_percent: number | null;
  comparison_available: boolean; anomaly_candidate: boolean; status_counts: Record<string, number>; buckets: { day: string; value: number }[] }
export interface ReportPlan { metrics: MetricId[]; start: string; end: string; grain: 'day'; scope: 'own' | 'department' | 'tenant'; metric_version: 1 }
export interface ReportDraft { summary: string; metric_refs: MetricId[]; possible_causes: string[] }
export interface ReportSnapshot { version: number; plan: ReportPlan; queried_at: string; timezone: string; previous_start: string; previous_end: string;
  interval: string; metrics: ReportMetric[]; read_only: boolean; anomaly_rule: { version: number; definition: string } }
export interface ReportSummary { report_id: string; thread_id: string; subject: string; status: string; version: number;
  available_actions: string[]; created_at: string; updated_at: string }
export interface ReportRecord extends ReportSummary { plan: ReportPlan; plan_confirmation: Record<string, unknown> | null;
  snapshot: ReportSnapshot | null; draft: ReportDraft | null; publication: Record<string, unknown> | null;
  error: { code: string; trace_id: string; message: string } | null; external_writes: false }
export interface ReportVersion { version: number; draft: ReportDraft; snapshot: ReportSnapshot; edited_by: string | null; created_at: string }
export interface ReportCommand { idempotency_key: string; expected_version: number }
