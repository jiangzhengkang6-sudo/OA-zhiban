import client from './client'
import type { MetricDefinition, ReportCommand, ReportDraft, ReportPlan, ReportRecord, ReportSummary, ReportVersion } from '@/types/report'
export const reportApi = {
  metrics(): Promise<MetricDefinition[]> { return client.get('/reports/metrics') },
  list(params = {}): Promise<{ items: ReportSummary[]; total: number; page: number; page_size: number }> { return client.get('/reports', { params }) },
  get(id: string): Promise<ReportRecord> { return client.get(`/reports/${encodeURIComponent(id)}`) },
  versions(id: string): Promise<ReportVersion[]> { return client.get(`/reports/${encodeURIComponent(id)}/versions`) },
  create(payload: { subject: string; plan: ReportPlan; idempotency_key: string }): Promise<ReportRecord> { return client.post('/reports', payload) },
  approve(id: string, payload: ReportCommand & { plan_confirmed: boolean }): Promise<ReportRecord> { return client.post(`/reports/${encodeURIComponent(id)}/approve-plan`, payload, { timeout: 60000 }) },
  retry(id: string, payload: ReportCommand): Promise<ReportRecord> { return client.post(`/reports/${encodeURIComponent(id)}/retry`, payload, { timeout: 60000 }) },
  save(id: string, payload: ReportCommand & { draft: ReportDraft }): Promise<ReportRecord> { return client.patch(`/reports/${encodeURIComponent(id)}/draft`, payload) },
  publish(id: string, payload: ReportCommand & { definitions_confirmed: boolean; causes_acknowledged: boolean }): Promise<ReportRecord> { return client.post(`/reports/${encodeURIComponent(id)}/publish`, payload) },
}
