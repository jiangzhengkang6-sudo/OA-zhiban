<script setup lang="ts">
import { computed } from 'vue'
import type { ReportMetric } from '@/types/report'
const props = defineProps<{ metric: ReportMetric }>()
const ceiling = computed(() => Math.max(1, ...props.metric.buckets.map(bucket => bucket.value)))
const states: Record<string, string> = { OPEN: '待开始', IN_PROGRESS: '进行中', COMPLETED: '已完成', CANCELLED: '已取消', ARCHIVED: '已归档', open: '待处理', resolved: '已解决', APPROVED: '已批准', REJECTED: '已拒绝', WAITING: '待审批' }
</script>
<template>
  <article class="metric-result">
    <header><h3>{{ metric.name }}</h3><small>v{{ metric.version }} · {{ metric.source }}</small></header>
    <div class="metric-numbers"><strong data-testid="metric-current">{{ metric.current }} <small>{{ metric.unit }}</small></strong><span>前期 {{ metric.previous }} {{ metric.unit }}<br><small>{{ metric.comparison_available ? `变化 ${metric.change_percent}%` : '无对比数据' }}</small></span></div>
    <p class="metric-definition">{{ metric.definition }}</p>
    <el-tag v-if="metric.anomaly_candidate" type="warning">异常候选，原因待核查</el-tag>
    <el-empty v-if="!metric.current" description="本期无数据" :image-size="56" />
    <div v-else class="chart-scroll"><div class="bar-chart" :style="{ minWidth: Math.max(280, metric.buckets.length * 36) + 'px' }" role="img" :aria-label="metric.name + '每日统计图'">
      <div v-for="bucket in metric.buckets" :key="bucket.day" class="bar-column" :title="`${bucket.day}：${bucket.value} ${metric.unit}`"><span class="bar-value">{{ bucket.value }}</span><div class="bar-track"><div class="bar" :style="{ height: (bucket.value / ceiling * 100) + '%' }" /></div><small>{{ bucket.day.slice(5) }}</small></div>
    </div></div>
    <dl v-if="Object.keys(metric.status_counts).length" class="status-counts"><template v-for="(count, status) in metric.status_counts" :key="status"><dt>{{ states[status] || status }}</dt><dd>{{ count }}</dd></template></dl>
    <details><summary>每日明细</summary><div class="table-scroll"><table><thead><tr><th>日期（上海）</th><th>数量</th></tr></thead><tbody><tr v-for="bucket in metric.buckets" :key="bucket.day"><td>{{ bucket.day }}</td><td>{{ bucket.value }} {{ metric.unit }}</td></tr></tbody></table></div></details>
  </article>
</template>
<style scoped>
.metric-result { border-top: 1px solid #dce3e7; padding: 20px 0; min-width: 0; }
header { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; align-items: baseline; } h3 { margin: 0; font-size: 16px; }
small,.metric-definition { font-size: 12px; color: #667782; } .metric-definition { line-height: 1.6; }
.metric-numbers { display: flex; align-items: center; gap: 24px; margin: 16px 0; } strong { font-size: 26px; font-weight: 600; } strong small { font-size: 14px; }
.metric-numbers > span { font-size: 13px; line-height: 1.7; }
.chart-scroll,.table-scroll { overflow: auto; max-width: 100%; } .bar-chart { display: flex; height: 180px; align-items: stretch; gap: 6px; margin: 20px 0 12px; }
.bar-column { display: flex; flex: 1; min-width: 20px; flex-direction: column; justify-content: flex-end; align-items: center; } .bar-value { font-size: 11px; }
.bar-track { height: 130px; width: 100%; display: flex; align-items: flex-end; border-bottom: 1px solid #dce3e7; } .bar { background: #198877; width: 100%; min-height: 0; max-width: 42px; margin: auto auto 0; } .bar-column > small { font-size: 10px; white-space: nowrap; margin-top: 7px; }
.status-counts { display: grid; grid-template-columns: minmax(0, 1fr) auto; font-size: 13px; gap: 7px 16px; } dd { margin: 0; }
summary { cursor: pointer; color: #49657a; font-size: 13px; padding: 8px 0; } table { width: 100%; text-align: left; font-size: 12px; border-collapse: collapse; } th,td { padding: 7px; border-bottom: 1px solid #edf0f2; }
</style>
