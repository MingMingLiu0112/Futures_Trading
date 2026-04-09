<template>
  <div class="home">
    <div class="hero">
      <h1>📊 PTA 精对苯二甲酸量化分析平台</h1>
      <p>基于缠论笔线段中枢的期货量化分析系统</p>
    </div>

    <div class="grid">
      <div class="card" @click="$router.push('/kline')">
        <div class="card-icon">📈</div>
        <h3>K线图表</h3>
        <p>专业K线图 + MACD + KDJ指标</p>
        <div class="card-tags">
          <span class="tag">ECharts</span>
          <span class="tag">多周期</span>
        </div>
      </div>

      <div class="card" @click="$router.push('/chan')">
        <div class="card-icon">🔮</div>
        <h3>缠论分析</h3>
        <p>笔线段中枢 + 买卖点识别</p>
        <div class="card-tags">
          <span class="tag">chan.py</span>
          <span class="tag">多级别</span>
        </div>
      </div>

      <div class="card info">
        <h3>📋 系统状态</h3>
        <div class="status-item" v-for="s in systemStatus" :key="s.label">
          <span>{{ s.label }}</span>
          <span :class="s.ok ? 'ok' : 'err'">{{ s.value }}</span>
        </div>
      </div>

      <div class="card info">
        <h3>📊 PTA 行情</h3>
        <div class="price-display" v-if="priceData.price">
          <div class="big-price">{{ priceData.price }}</div>
          <div :class="priceData.change >= 0 ? 'up' : 'down'">
            {{ priceData.change >= 0 ? '▲' : '▼' }}
            {{ Math.abs(priceData.change).toFixed(0) }}元
            ({{ priceData.changePct.toFixed(2) }}%)
          </div>
        </div>
        <div v-else class="loading">加载中...</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'

const systemStatus = ref([
  { label: '后端服务', value: '运行中', ok: true },
  { label: '缠论引擎', value: 'chan.py', ok: true },
  { label: '数据源', value: 'akshare', ok: true },
  { label: 'PTA品种', value: 'TA0', ok: true },
])

const priceData = ref({})

onMounted(async () => {
  try {
    const r = await axios.get('/api/kline/data?period=1min')
    const d = r.data
    priceData.value = {
      price: d.current_price,
      change: d.change,
      changePct: d.change_pct
    }
  } catch (e) {
    console.error(e)
  }
})
</script>

<style scoped>
.home { padding: 32px; max-width: 1400px; margin: 0 auto; }
.hero { text-align: center; margin-bottom: 40px; }
.hero h1 { font-size: 2rem; margin-bottom: 8px; color: #e94560; }
.hero p { color: #8b949e; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; }
.card {
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 12px;
  padding: 24px;
  cursor: pointer;
  transition: all 0.2s;
}
.card:hover { border-color: #e94560; transform: translateY(-2px); }
.card-icon { font-size: 2rem; margin-bottom: 12px; }
.card h3 { margin-bottom: 8px; }
.card p { color: #8b949e; font-size: 0.85rem; margin-bottom: 12px; }
.card-tags { display: flex; gap: 8px; }
.tag { background: #21262d; border: 1px solid #30363d; border-radius: 12px; padding: 2px 8px; font-size: 0.72rem; color: #8b949e; }
.status-item { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #21262d; font-size: 0.85rem; }
.status-item .ok { color: #3fb950; }
.status-item .err { color: #f85149; }
.price-display { text-align: center; }
.big-price { font-size: 2.5rem; font-weight: 700; color: #e94560; }
.up { color: #f23645; font-size: 1rem; }
.down { color: #089981; font-size: 1rem; }
.loading { color: #8b949e; text-align: center; padding: 20px; }
</style>
