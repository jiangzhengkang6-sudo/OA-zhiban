import client from './client'

export interface WorkTaskCandidate {
  candidate_id: string; title: string; assignee_id: string | null; due_at: string | null
  priority: 'low' | 'normal' | 'high'; sensitive: boolean; source_refs: string[]
}
export interface WorkTaskBatch {
  batch_id: string; thread_id: string; source_type: string; source_id: string; source_version: string
  source: { ref: string; title: string; content: string; source_type?: string; source_id?: string }; status: string; version: number
  draft: { candidates: WorkTaskCandidate[] } | null; available_actions: string[]; task_ids: string[]
  error: { message: string; trace_id: string } | null; created_at: string; updated_at: string
}
export interface WorkTask {
  task_id: string; batch_id: string; title: string; creator_id: string; assignee_id: string; due_at: string
  priority: 'low' | 'normal' | 'high'; sensitive: boolean; status: string; progress: number; version: number
  deadline_version: number; source_refs: string[]; source: WorkTaskBatch['source'] | null
  available_actions: string[]; created_at: string; updated_at: string
}
export interface TaskNotice { id: string; task_id: string; title: string; stage: string; due_at: string; read_at: string | null; created_at: string }
export interface TaskEvent { action: string; version: number; actor_id: string; details: Record<string, unknown>; created_at: string }
export interface TaskVersion { version: number; draft: { candidates: WorkTaskCandidate[] }; edited_by: string | null; created_at: string }
export interface TaskSourceInput { source_type: 'ticket' | 'meeting' | 'approval'; source_id: string; source_version?: number }
export interface TaskCommand { idempotency_key: string; expected_version: number }
export const workTaskApi = {
  list(params = {}): Promise<{ items: WorkTask[]; total: number; page: number; page_size: number }> { return client.get('/work-tasks', { params }) },
  get(id: string): Promise<WorkTask> { return client.get(`/work-tasks/${encodeURIComponent(id)}`) },
  batches(): Promise<WorkTaskBatch[]> { return client.get('/work-tasks/batches') },
  batch(id: string): Promise<WorkTaskBatch> { return client.get(`/work-tasks/batches/${encodeURIComponent(id)}`) },
  versions(id: string): Promise<TaskVersion[]> { return client.get(`/work-tasks/batches/${encodeURIComponent(id)}/versions`) },
  create(payload: TaskSourceInput & { idempotency_key: string }): Promise<WorkTaskBatch> { return client.post('/work-tasks/batches', payload) },
  extract(id: string, payload: TaskCommand): Promise<WorkTaskBatch> { return client.post(`/work-tasks/batches/${encodeURIComponent(id)}/extract`, payload) },
  save(id: string, payload: TaskCommand & { draft: { candidates: WorkTaskCandidate[] } }): Promise<WorkTaskBatch> { return client.patch(`/work-tasks/batches/${encodeURIComponent(id)}/draft`, payload) },
  decide(id: string, payload: TaskCommand & { action: 'confirm' | 'reject'; selected_candidate_ids: string[]; metadata_confirmed: boolean; risk_acknowledged: boolean; reason: string }): Promise<WorkTaskBatch> { return client.post(`/work-tasks/batches/${encodeURIComponent(id)}/decisions`, payload) },
  update(id: string, payload: TaskCommand & Pick<WorkTask, 'title' | 'assignee_id' | 'due_at' | 'priority' | 'sensitive'> & { metadata_confirmed: boolean; risk_acknowledged: boolean }): Promise<WorkTask> { return client.patch(`/work-tasks/${encodeURIComponent(id)}`, payload) },
  command(id: string, payload: TaskCommand & { action: string; progress?: number; comment: string }): Promise<WorkTask> { return client.post(`/work-tasks/${encodeURIComponent(id)}/commands`, payload) },
  events(id: string): Promise<TaskEvent[]> { return client.get(`/work-tasks/${encodeURIComponent(id)}/events`) },
  notifications(): Promise<TaskNotice[]> { return client.get('/work-tasks/notifications') },
  read(id: string, payload: TaskCommand): Promise<{ read: boolean }> { return client.post(`/work-tasks/notifications/${encodeURIComponent(id)}/read`, payload) },
}
