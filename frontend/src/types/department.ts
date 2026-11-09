export interface Announcement {
  id: string
  department_id: string
  author_id: string
  title: string
  body: string
  state: 'DRAFT' | 'PUBLISHED' | 'WITHDRAWN'
  revision: number
  published_at: string | null
  withdrawn_at: string | null
  read_at: string | null
  can_manage: boolean
}
export interface WorkItem {
  id: string
  source: 'approval' | 'work_task'
  title: string
  business_id: string
  state: string
  due_at: string | null
  href: string
}
