import client from './client'
import type { ContractResponse, ContractSummary, ContractVersion, ContractPayload, ContractCommand } from '@/types/contract'
export const contractApi = {
  list(params = {}): Promise<{ items: ContractSummary[]; total: number; page: number; page_size: number }> { return client.get('/contracts', { params }) },
  get(id: string): Promise<ContractResponse> { return client.get(`/contracts/${encodeURIComponent(id)}`) },
  versions(id: string): Promise<ContractVersion[]> { return client.get(`/contracts/${encodeURIComponent(id)}/versions`) },
  create(payload: ContractPayload): Promise<ContractResponse> { return client.post('/contracts', payload) },
  upload(payload: FormData): Promise<ContractResponse> { return client.post('/contracts/uploads', payload) },
  command(id: string, payload: ContractCommand): Promise<ContractResponse> { return client.post(`/contracts/${encodeURIComponent(id)}/commands`, payload) },
}
