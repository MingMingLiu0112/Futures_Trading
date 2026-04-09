<template>
  <div class="kline-page">
    <div class="toolbar">
      <select v-model="period" @change="loadData">
        <option value="1min">1分钟</option>
        <option value="5min">5分钟</option>
        <option value="15min">15分钟</option>
        <option value="30min">30分钟</option>
        <option value="60min">60分钟</option>
        <option value="1day">日线</option>
      </select>
      <div class="chan-toggles">
        <button v-for="t in chanToggles" :key="t.key"
          :class="['toggle-btn', t.on ? 'on' : '']"
          @click="toggleChan(t.key)">{{ t.label }}</button>
      </div>
      <div class="price-info">
        <span class="price">{{ price }}</span>
        <span :class="change >= 0 ? 'up' : 'down'">
          {{ change >= 0 ? '+' : '' }}{{ change.toFixed(0) }} ({{ changePct.toFixed(2) }}%)
        </span>
      </div>
      <div class="chan-badges">
        <span class="badge bi">笔 {{ stats.bi }}</span>
        <span class="badge seg">线 {{ stats.seg }}</span>
        <span class="badge zs">枢 {{ stats.zs }}</span>
      </div>
    </div>
    <div ref="chartRef" class="chart-container"></div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import axios from 'axios'
import * as echarts from 'echarts'

const chartRef = ref(null)
let chart = null

const period = ref('1min')
const price = ref(0)
const change = ref(0)
const changePct = ref(0)
const stats = ref({ bi: 0, seg: 0, zs: 0 })
const chanData = ref(null)

const chanToggles = ref([
  { key: 'bi', label: '笔', on: true },
  { key: 'seg', label: '线段', on: false },
  { key: 'zs', label: '中枢', on: false },
])

function toggleChan(key) {
  const t = chanToggles.value.find(x => x.key === key)
  if (t) t.on = !t.on
  renderChart()
}

async function loadData() {
  try {
    const [kRes, cRes] = await Promise.all([
      axios.get(`/api/kline/data?period=${period.value}`),
      axios.get(`/api/chan/analysis?period=${period.value}`),
    ])
    const kd = kRes.data
    const cd = cRes.data

    price.value = kd.current_price
    change.value = kd.change
    changePct.value = kd.change_pct
    chanData.value = cd
    stats.value = {
      bi: cd.stats?.bi_count || 0,
      seg: cd.stats?.seg_count || 0,
      zs: cd.stats?.zs_count || 0,
    }
    renderChart()
  } catch (e) {
    console.error('加载失败:', e)
  }
}

function renderChart() {
  if (!chart || !chanData.value) return

  const kd = chanData.value.klines
  const timeData = kd.map(d => d.time)
  const candleData = kd.map(d => [d.open, d.close, d.low, d.high])
  const volData = kd.map(d => d.volume)
  const ma5 = calcMA(candleData, 5)
  const ma10 = calcMA(candleData, 10)
  const ma20 = calcMA(candleData, 20)
  const macd = calcMACD(candleData.map(d => d[1]))
  const kdj = calcKDJ(candleData)

  const e = chanData.value.echarts || {}

  // MACD颜色
  const macdColor = v => v >= 0 ? '#f23645' : '#089981'
  const macdBars = macd.bar.map(v => ({ value: v, itemStyle: { color: macdColor(v) } }))

  const series = [
    { name: 'K线', type: 'candlestick', data: candleData, xAxisIndex: 0, yAxisIndex: 0,
      itemStyle: { color: '#f23645', color0: '#089981', borderColor: '#f23645', borderColor0: '#089981' }},
    { name: 'MA5', type: 'line', data: ma5, xAxisIndex: 0, yAxisIndex: 0, smooth: true, symbol: 'none', lineStyle: { color: '#ff6b6b', width: 1 }},
    { name: 'MA10', type: 'line', data: ma10, xAxisIndex: 0, yAxisIndex: 0, smooth: true, symbol: 'none', lineStyle: { color: '#ffd93d', width: 1 }},
    { name: 'MA20', type: 'line', data: ma20, xAxisIndex: 0, yAxisIndex: 0, smooth: true, symbol: 'none', lineStyle: { color: '#6bcb77', width: 1 }},
    { name: 'MACD', type: 'bar', data: macdBars, xAxisIndex: 1, yAxisIndex: 1 },
    { name: 'DIF', type: 'line', data: macd.diff, xAxisIndex: 1, yAxisIndex: 1, smooth: true, symbol: 'none', lineStyle: { color: '#6bcb77', width: 1 }},
    { name: 'DEA', type: 'line', data: macd.dea, xAxisIndex: 1, yAxisIndex: 1, smooth: true, symbol: 'none', lineStyle: { color: '#ff6b6b', width: 1 }},
    { name: 'K', type: 'line', data: kdj.k, xAxisIndex: 2, yAxisIndex: 2, smooth: true, symbol: 'none', lineStyle: { color: '#ff6b6b', width: 1 }},
    { name: 'D', type: 'line', data: kdj.d, xAxisIndex: 2, yAxisIndex: 2, smooth: true, symbol: 'none', lineStyle: { color: '#ffd93d', width: 1 }},
    { name: 'J', type: 'line', data: kdj.j, xAxisIndex: 2, yAxisIndex: 2, smooth: true, symbol: 'none', lineStyle: { color: '#6bcb77', width: 1 }},
  ]

  // 缠论笔
  if (chanToggles.value.find(t => t.key === 'bi')?.on && e.bi_markline?.length) {
    series.push({
      name: '笔', type: 'line', xAxisIndex: 0, yAxisIndex: 0, symbol: 'none', z: 10,
      markLine: { silent: true, symbol: ['none','none'], data: e.bi_markline }
    })
  }

  // 缠论线段
  if (chanToggles.value.find(t => t.key === 'seg')?.on && e.seg_markline?.length) {
    series.push({
      name: '线段', type: 'line', xAxisIndex: 0, yAxisIndex: 0, symbol: 'none', z: 11,
      markLine: { silent: true, symbol: ['none','none'], data: e.seg_markline }
    })
  }

  // 缠论中枢
  if (chanToggles.value.find(t => t.key === 'zs')?.on && e.zs_markarea?.length) {
    series.push({
      name: '中枢', type: 'line', xAxisIndex: 0, yAxisIndex: 0, symbol: 'none', z: 5,
      markArea: { silent: true, data: e.zs_markarea.map(z => [
        { xAxis: z.xAxis, yAxis: z.yAxis, itemStyle: { color: 'rgba(233,69,96,0.08)', borderColor: '#e94560', borderWidth: 1, borderType: 'dashed' } },
        { xAxis: z.xAxis2, yAxis: z.yAxis2 }
      ])}
    })
  }

  chart.setOption({
    backgroundColor: '#0d1117',
    animation: false,
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' }, backgroundColor: 'rgba(22,33,62,0.95)', borderColor: '#e94560', textStyle: { color: '#e6edf3' }},
    legend: { data: ['K线','MA5','MA10','MA20'], top: 5, textStyle: { color: '#8b949e' }, selected: { MA10: false, MA20: false }},
    toolbox: { right: '5%', top: 0, feature: { dataZoom: { yAxisIndex: 'none', title: { zoom: '缩放', back: '还原' } }, restore: { title: '还原' }, saveAsImage: { title: '保存' } }},
    grid: [
      { left: '7%', right: '3%', top: '12%', height: '48%' },
      { left: '7%', right: '3%', top: '65%', height: '14%' },
      { left: '7%', right: '3%', top: '83%', height: '13%' }
    ],
    xAxis: [
      { type: 'category', data: timeData, gridIndex: 0, boundaryGap: false, axisLine: { lineStyle: { color: '#30363d' } }, axisLabel: { color: '#8b949e', fontSize: 9 }, splitLine: { show: false }},
      { type: 'category', data: timeData, gridIndex: 1, boundaryGap: false, axisLine: { lineStyle: { color: '#30363d' } }, axisLabel: { show: false }, splitLine: { show: false }},
      { type: 'category', data: timeData, gridIndex: 2, boundaryGap: false, axisLine: { lineStyle: { color: '#30363d' } }, axisLabel: { color: '#8b949e', fontSize: 9 }, splitLine: { show: false }}
    ],
    yAxis: [
      { type: 'value', scale: true, gridIndex: 0, splitLine: { lineStyle: { color: '#21262d' } }, axisLine: { lineStyle: { color: '#30363d' } }, axisLabel: { color: '#8b949e' }},
      { type: 'value', scale: true, gridIndex: 1, splitLine: { show: false }, axisLine: { lineStyle: { color: '#30363d' } }, axisLabel: { show: false }},
      { type: 'value', scale: true, gridIndex: 2, splitLine: { show: false }, axisLine: { lineStyle: { color: '#30363d' } }, axisLabel: { color: '#8b949e', fontSize: 9 }}
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0,1,2], start: 65, end: 100 },
      { type: 'slider', xAxisIndex: [0,1,2], bottom: '1%', height: 18, start: 65, end: 100, borderColor: '#30363d', fillerColor: 'rgba(233,69,96,0.15)', handleStyle: { color: '#e94560' }, textStyle: { color: '#8b949e' }}
    ],
    series,
  }, true)
}

function calcMA(data, period) {
  const r = []
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) r.push('-')
    else {
      let s = 0
      for (let j = 0; j < period; j++) s += data[i-j][1]
      r.push((s/period).toFixed(2))
    }
  }
  return r
}

function calcMACD(close) {
  const ema = (a, n) => { const k = 2/(n+1); const r=[]; for(let i=0;i<a.length;i++) r.push(i===0?a[i]:a[i]*k+r[i-1]*(1-k)); return r }
  const ef = ema(close,12), es = ema(close,26)
  const d = ef.map((v,i) => v - es[i])
  const de = ema(d, 9)
  const b = d.map((v,i) => (v-de[i])*2)
  return { diff: d, dea: de, bar: b }
}

function calcKDJ(data) {
  const n=9, k=[], d=[], j=[]
  for(let i=0;i<data.length;i++){
    if(i<n-1){k.push(50);d.push(50)}
    else{
      let maxH=-Infinity,minL=Infinity
      for(let t=i-n+1;t<=i;t++){
        if(data[t][3]>maxH)maxH=data[t][3]
        if(data[t][2]<minL)minL=data[t][2]
      }
      const rsv = maxH===minL?50:(data[i][1]-minL)/(maxH-minL)*100
      k.push(2/3*k[i-1]+1/3*rsv)
      d.push(2/3*d[i-1]+1/3*k[k.length-1])
    }
    j.push(3*k[k.length-1]-2*d[d.length-1])
  }
  return {k,d,j}
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
.kline-page { display: flex; flex-direction: column; height: calc(100vh - 52px); }
.toolbar {
  background: #161b22;
  border-bottom: 1px solid #30363d;
  padding: 8px 16px;
  display: flex;
  align-items: center;
  gap: 16px;
  flex-shrink: 0;
}
select { background: #21262d; border: 1px solid #30363d; color: #e6edf3; padding: 5px 12px; border-radius: 6px; font-size: 0.82rem; }
.chan-toggles { display: flex; gap: 6px; }
.toggle-btn { font-size: 0.75rem; padding: 4px 10px; border-radius: 10px; border: 1px solid #30363d; background: #21262d; color: #8b949e; cursor: pointer; }
.toggle-btn.on { background: #1f6feb; border-color: #1f6feb; color: #fff; }
.price-info { font-size: 0.9rem; display: flex; gap: 10px; align-items: center; }
.big-price { font-weight: 700; color: #e94560; }
.up { color: #f23645; }
.down { color: #089981; }
.chan-badges { display: flex; gap: 8px; margin-left: auto; }
.badge { background: #21262d; border: 1px solid #30363d; border-radius: 12px; padding: 2px 10px; font-size: 0.72rem; }
.badge .num { color: #e94560; font-weight: bold; }
.chart-container { flex: 1; min-height: 0; }
</style>
