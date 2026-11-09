export const leaveTypeLabels: Record<string, string> = { annual: '年假', sick: '病假', personal: '事假', other: '其他假' }

export function leaveTypeCode(value: string): string {
  return Object.keys(leaveTypeLabels).find(code => leaveTypeLabels[code] === value) || value
}

export function leaveTypeLabel(value: string): string {
  return leaveTypeLabels[leaveTypeCode(value)] || value
}
