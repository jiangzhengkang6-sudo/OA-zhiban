import client from './client'
import type { Announcement, WorkItem } from '@/types/department'
import type { Outcome, Command } from '@/types/oa'
export const departmentApi = {
  announcements: (manage = false): Promise<Announcement[]> => client.get('/oa/announcements', { params: { manage } }),
  announcement: (id: string): Promise<Announcement> => client.get(`/oa/announcements/${id}`),
  create: (data: { operation_id: string; department_id: string; title: string; body: string }): Promise<Outcome<Announcement>> => client.post('/oa/announcements', data),
  save: (id: string, data: Command & { title: string; body: string }): Promise<Outcome<Announcement>> => client.put(`/oa/announcements/${id}`, data),
  transition: (id: string, action: 'publish' | 'withdraw', data: Command): Promise<Outcome<Announcement>> => client.post(`/oa/announcements/${id}/${action}`, data),
  read: (id: string): Promise<Announcement> => client.post(`/oa/announcements/${id}/read`),
  pending: (params: { source?: string; page: number; page_size: number }): Promise<{ items: WorkItem[]; total: number }> => client.get('/oa/work-items', { params }),
}
