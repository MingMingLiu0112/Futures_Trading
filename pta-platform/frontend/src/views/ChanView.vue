<template>
  <div class="chan-page">
    <div class="toolbar">
      <select v-model="period" @change="loadData">
        <option value="1min">1分钟</option>
        <option value="5min">5分钟</option>
        <option value="15min">15分钟</option>
        <option value="30min">30分钟</option>
        <option value="60min">60分钟</option>
        <option value="1day">日线</option>
      </select>
      <div class="chan-badges">
        <span class="badge bi">笔 <b>{{ stats.bi }}</b></span>
        <span class="badge seg">线段 <b>{{ stats.seg }}</b></span>
        <span class="badge zs">中枢 <b>{{ stats.zs }}</b></span>
        <span class="badge bs">买卖 <b>{{ stats.bs }}</b></span>
      </div>
      <div class="price-info">
        <span class="price">{{ price }}</span>
        <span :class="change >= 0 ? 'up' : 'down'">
          {{ change >= 0 ? '+' : '' }}{{ change.toFixed(0) }}元
        </span>
      </div>
    </div>
    <div ref="chartRef" class="chart-container"></div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import axios from 'axios'
import * as echarts from 'echarts'

const chartRef = ref(null)
let chart = null
const period = ref('1min')
const price = ref(0)
const change = ref(0)
const stats = ref({ bi: 0, seg: 0, zs: 0, bs: 0 })
const chanData = ref(null)

async function loadData() {
  try {
    const r = await axios.get(`/api/chan/analysis?period=${period.value}`)
    chanData.value = r.data
    price.value = r.data.current_price
    change.value = r.data.change
    stats.value = {
      bi: r.data.stats?.bi_count || 0,
      seg: r.data.stats?.seg_count || 0,
      zs: r.data.stats?.zs_count || 0,
      bs: r.data.stats?.bs_count || 0,
    }
    renderChart()
  } catch (e) { console.error(e) }
}

function renderChart() {
  if (!chart || !chanData.value) return
  const kd = chanData.value.klines
  const timeData = kd.map(d => d.time)
  const candleData = kd.map(d => [d.open, d.close, d.low, d.high])
  const e = chanData.value.echarts || {}

  const series = [
    { name: 'K线', type: 'candlestick', data: candleData, xAxisIndex: 0, yAxisIndex: 0,
      itemStyle: { color: '#f23645', color0: '#089981', borderColor: '#f23645', borderColor0: '#089981' }},
  ]

  // 笔
  if (e.bi_markline?.length) {
    series.push({ name: '笔', type: 'line', xAxisIndex: 0, yAxisIndex: 0, symbol: 'none', z: 10,
      markLine: { silent: true, symbol: ['none','none'], data: e.bi_markline }})
  }
  // 线段
  if (e.seg_markline?.length) {
    series.push({ name: '线段', type: 'line', xAxisIndex: 0, yAxisIndex: 0, symbol: 'none', z: 11,
      markLine: { silent: true, symbol: ['none','none'], data: e.seg_markline }})
  }
  // 中枢
  if (e.zs_markarea?.length) {
    series.push({ name: '中枢', type: 'line', xAxisIndex: 0, yAxisIndex: 0, symbol: 'none', z: 5,
      markArea: { silent: true, data: e.zs_markarea.map(z => [
        { xAxis: z.xAxis, yAxis: z.yAxis, itemStyle: { color: 'rgba(233,69,96,0.1)', borderColor: '#e94560', borderWidth: 1, borderType: 'dashed' } },
        { xAxis: z.xAxis2, yAxis: z.yAxis2 }
      ])}}
    })
  }
  // 买卖点
  if (e.bs_scatter?.length) {
    series.push({ name: '买卖点', type: 'scatter', xAxisIndex: 0, yAxisIndex: 0, z: 20,
      data: e.bs_scatter, symbolSize: 14 })
  }

  chart.setOption({
    backgroundColor: '#0d1117',
    animation: false,
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' }, backgroundColor: 'rgba(22,33,62,0.95)', borderColor: '#e94560', textStyle: { color: '#e6edf3' }},
    legend: { data: ['K线','笔','线段','中枢','买卖点'], top: 5, textStyle: { color: '#8b949e' },
      selected: {'线段':false,'中枢':false,'买卖点':false} },
    toolbox: { right: '5%', top: 0, feature: { dataZoom: { yAxisIndex: 'none' }, restore: {}, saveAsImage: {} }},
    grid: [{ left: '7%', right: '3%', top: '12%', bottom: '8%' }],
    xAxis: [{ type: 'category', data: timeData, boundaryGap: false, axisLine: { lineStyle: { color: '#30363d' } }, axisLabel: { color: '#8b949e', fontSize: 9 }, splitLine: { show: false } }],
    yAxis: [{ type: 'value', scale: true, splitLine: { lineStyle: { color: '#21262d' } }, axisLine: { lineStyle: { color: '#30363d' } }, axisLabel: { color: '#8b949e' } }],
    dataZoom: [
      { type: 'inside', start: 50, end: 100 },
      { type: 'slider', bottom: '1%', height: 20, start: 50, end: 100, borderColor: '#30363d', fillerColor: 'rgba(233,69,96,0.15)', handleStyle: { color: '#e94560' }, textStyle: { color: '#8b949e' }}
    ],
    series,
  }, true)
}

onMounted(() => {
  chart = echarts.init(chartRef.value)
  window.addEventListener('resize', () => chart.resize())
  loadData()
})
onUnmounted(() => {
  window.removeEventListener('resize', () => chart.resize())
  chart?.dispose()
})
</script>

<style scoped>
.chan-page { display: flex; flex-direction: column; height: calc(100vh - 52px); }
.toolbar { background: #161b22; border-bottom: 1px solid #30363d; padding: 8px 16px; display: flex; align-items: center; gap: 16px; }
select { background: #21262d; border: 1px solid #30363d; color: #e6edf3; padding: 5px 12px; border-radius: 6px; font-size: 0.82rem; }
.chan-badges { display: flex; gap: 8px; }
.badge { background: #21262d; border: 1px solid #30363d; border-radius: 12px; padding: 2px 10px; font-size: 0.72rem; }
.badge b { color: #e94560; margin-left: 3px; }
.price-info { font-size: 0.9rem; display: flex; gap: 10px; align-items: center; margin-left: auto; }
.up { color: #f23645; }
.down { color: #089981; }
.chart-container { flex: 1; }
</style>
