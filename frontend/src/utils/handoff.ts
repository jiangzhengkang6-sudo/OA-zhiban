const reasons: Record<string, string> = {
  FAQ_UNCERTAIN: '知识库未找到可靠依据，需人工核实',
  FAQ_HUMAN_REQUEST: '用户主动请求人工服务',
  FAQ_NO_EVIDENCE: '知识库未找到可靠依据，需人工核实',
  TICKET_HUMAN: '工单需要人工处理',
  TASK_HANDOFF: '任务已转交人工处理',
  NEGATIVE_FEEDBACK: '用户反馈问题仍未解决',
}

export function handoffReason(code: string): string {
  return reasons[code] || (code ? `需人工核实（${code}）` : '需人工核实')
}
