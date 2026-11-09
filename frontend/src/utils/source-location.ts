export function sourceLocation(value?: string): string {
  if (!value) return '正文'
  if (value.startsWith('page=')) {
    const page = value.match(/^page=(\d+);/)
    const section = value.match(/;section=(.*);paragraph=/)?.[1]
    const paragraph = value.match(/;paragraph=(\d+)$/)
    return [page ? `第 ${page[1]} 页` : '', section && section !== 'None' ? section : '',
      paragraph ? `第 ${paragraph[1]} 段` : ''].filter(Boolean).join(' · ') || '正文'
  }
  return value.replace(/#chunk-(\d+)$/, (_, index) => ` · 第 ${Number(index) + 1} 个片段`)
}
