<script setup lang="ts">
import { ref, onMounted, watch, onUnmounted } from 'vue';
import * as echarts from 'echarts';
import { dataApi } from '../api';
import type { KlineData } from '../types';

const symbol = ref('TEST');
const frequency = ref('1min');
const chartRef = ref<HTMLDivElement | null>(null);
let chartInstance: echarts.ECharts | null = null;
const klines = ref<KlineData[]>([]);
const selectedIndicators = ref<string[]>(['ma5', 'ma10', 'macd']);

const availableIndicators = [
  { value: 'ma5', label: 'MA5' },
  { value: 'ma10', label: 'MA10' },
  { value: 'ma20', label: 'MA20' },
  { value: 'macd', label: 'MACD' },
  { value: 'kdj', label: 'KDJ' },
  { value: 'rsi', label: 'RSI' },
  { value: 'bollinger', label: '布林带' },
  { value: 'volume', label: '成交量' }
];

const toggleIndicator = (indicator: string) => {
  const index = selectedIndicators.value.indexOf(indicator);
  if (index > -1) {
    selectedIndicators.value.splice(index, 1);
  } else {
    selectedIndicators.value.push(indicator);
  }
};

const loadData = async () => {
  try {
    klines.value = await dataApi.getKlines(symbol.value, frequency.value);
  } catch (error) {
    console.error('Failed to load klines:', error);
    klines.value = generateMockKlines(100);
  }
  updateChart();
};

const generateMockKlines = (count: number): KlineData[] => {
  const data: KlineData[] = [];
  let basePrice = 5000;
  const now = new Date();
  for (let i = count - 1; i >= 0; i--) {
    const change = (Math.random() - 0.5) * 20;
    const open = basePrice;
    const close = basePrice + change;
    const high = Math.max(open, close) + Math.random() * 5;
    const low = Math.min(open, close) - Math.random() * 5;
    const timestamp = new Date(now.getTime() - i * 60 * 1000).toISOString();
    data.push({
      timestamp,
      open: Math.round(open * 100) / 100,
      high: Math.round(high * 100) / 100,
      low: Math.round(low * 100) / 100,
      close: Math.round(close * 100) / 100,
      volume: Math.floor(Math.random() * 1000) + 100
    });
    basePrice = close;
  }
  return data;
};

const updateChart = () => {
  if (!chartInstance || klines.value.length === 0) return;

  const dates = klines.value.map(k => {
    const date = new Date(k.timestamp);
    return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`;
  });

  const ohlc = klines.value.map(k => [k.open, k.close, k.low, k.high]);
  const volumes = klines.value.map(k => k.volume || 0);
  const colors = klines.value.map(k => k.close >= k.open ? '#ef4444' : '#22c55e');

  const option: echarts.EChartsOption = {
    backgroundColor: '#fff',
    animation: false,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: 'rgba(255, 255, 255, 0.95)',
      borderColor: '#e5e7eb',
      borderWidth: 1,
      textStyle: { color: '#374151' },
      formatter: (params: any) => {
        const kline = params.find((p: any) => p.seriesName === 'K线');
        if (!kline) return '';
        const data = kline.data;
        return `<div style="padding: 8px;"><div style="font-weight: bold; margin-bottom: 8px;">${kline.axisValue}</div><div>开盘: ¥${data[1]}</div><div>收盘: ¥${data[2]}</div><div>最低: ¥${data[3]}</div><div>最高: ¥${data[4]}</div></div>`;
      }
    },
    legend: {
      data: ['K线', ...selectedIndicators.value],
      bottom: 10,
      textStyle: { color: '#6b7280' }
    },
    grid: [
      { left: '10%', right: '10%', top: '5%', height: '55%' },
      { left: '10%', right: '10%', top: '70%', height: '20%' }
    ],
    xAxis: [
      {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#e5e7eb' } },
        axisLabel: { color: '#6b7280', fontSize: 10 },
        splitLine: { show: false }
      },
      {
        type: 'category',
        gridIndex: 1,
        data: dates,
        axisLine: { lineStyle: { color: '#e5e7eb' } },
        axisLabel: { show: false },
        splitLine: { show: false }
      }
    ],
    yAxis: [
      {
        type: 'value',
        scale: true,
        axisLine: { show: false },
        axisLabel: { color: '#6b7280', fontSize: 10, formatter: (value: number) => `¥${value}` },
        splitLine: { lineStyle: { color: '#f3f4f6', type: 'dashed' as const } }
      },
      {
        type: 'value',
        gridIndex: 1,
        scale: true,
        axisLine: { show: false },
        axisLabel: { color: '#6b7280', fontSize: 10 },
        splitLine: { lineStyle: { color: '#f3f4f6', type: 'dashed' as const } }
      }
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: 50, end: 100 },
      {
        show: true,
        xAxisIndex: [0, 1],
        type: 'slider',
        bottom: 40,
        start: 50,
        end: 100,
        height: 20,
        borderColor: '#e5e7eb',
        fillerColor: 'rgba(59, 130, 246, 0.2)',
        handleStyle: { color: '#3b82f6' }
      }
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: ohlc,
        itemStyle: {
          color: '#ef4444',
          color0: '#22c55e',
          borderColor: '#ef4444',
          borderColor0: '#22c55e'
        }
      }
    ]
  };

  if (selectedIndicators.value.includes('volume')) {
    const series = option.series as any[];
    series.push({
      name: '成交量',
      type: 'bar',
      xAxisIndex: 1,
      yAxisIndex: 1,
      data: volumes.map((v, i) => ({ value: v, itemStyle: { color: colors[i] } }))
    });
  }

  chartInstance.setOption(option);
};

onMounted(() => {
  if (chartRef.value) {
    chartInstance = echarts.init(chartRef.value);
    loadData();
    window.addEventListener('resize', () => chartInstance?.resize());
  }
});

watch([symbol, frequency], () => loadData());
watch(selectedIndicators, () => updateChart(), { deep: true });

onUnmounted(() => {
  chartInstance?.dispose();
  window.removeEventListener('resize', () => chartInstance?.resize());
});
</script>

<template>
  <div class="charts-container">
    <div class="flex flex-wrap items-center justify-between gap-4 mb-6">
      <div class="flex items-center gap-4">
        <div>
          <label class="block text-sm text-gray-600 mb-1">合约代码</label>
          <input 
            v-model="symbol" 
            type="text" 
            class="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="输入合约代码"
          />
        </div>
        <div>
          <label class="block text-sm text-gray-600 mb-1">时间周期</label>
          <select 
            v-model="frequency" 
            class="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="1min">1分钟</option>
            <option value="5min">5分钟</option>
            <option value="15min">15分钟</option>
            <option value="1h">1小时</option>
            <option value="1d">1日</option>
          </select>
        </div>
      </div>
      <button 
        @click="loadData"
        class="px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors"
      >
        刷新数据
      </button>
    </div>

    <div class="flex flex-wrap gap-2 mb-4">
      <button
        v-for="indicator in availableIndicators"
        :key="indicator.value"
        @click="toggleIndicator(indicator.value)"
        class="px-3 py-1 text-sm rounded-full transition-colors"
        :class="selectedIndicators.includes(indicator.value) 
          ? 'bg-blue-500 text-white' 
          : 'bg-gray-100 text-gray-600 hover:bg-gray-200'"
      >
        {{ indicator.label }}
      </button>
    </div>

    <div class="bg-white rounded-xl shadow-lg p-4">
      <div ref="chartRef" class="w-full h-[500px]"></div>
    </div>
  </div>
</template>

<style scoped>
.charts-container {
  padding: 20px;
}
</style>
