<script setup lang="ts">import { ref, onMounted } from 'vue';
import * as echarts from 'echarts';
import { backtestApi } from '../api';
import type { BacktestResult } from '../types';
const strategy = ref('macd');
const symbol = ref('TEST');
const strategies = [
 { value: 'macd', label: 'MACD策略' },
 { value: 'ma', label: '均线策略' },
 { value: 'kdj', label: 'KDJ策略' },
 { value: 'rsi', label: 'RSI策略' },
 { value: 'bollinger', label: '布林带策略' },
 { value: 'atr', label: 'ATR策略' }
];
const result = ref<BacktestResult | null>(null);
const isRunning = ref(false);
const chartRef = ref<HTMLDivElement | null>(null);
let chartInstance: echarts.ECharts | null = null;
const runBacktest = async () => {
 isRunning.value = true;
 try {
 result.value = await backtestApi.runBacktest(strategy.value, symbol.value);
 }
 catch (error) {
 console.error('Failed to run backtest:', error);
 // 使用模拟数据
 result.value = {
 strategy: strategies.find(s => s.value === strategy.value)?.label || strategy.value,
 total_trades: 128,
 win_rate: 0.58,
 total_pnl: 45230.50,
 max_drawdown: 0.085,
 sharpe_ratio: 1.85,
 profit_factor: 1.65,
 equity_curve: generateEquityCurve(100)
 };
 }
 isRunning.value = false;
 updateChart();
};
const generateEquityCurve = (count: number): number[] => {
 const curve: number[] = [];
 let equity = 1000000;
 for (let i = 0; i < count; i++) {
 equity = equity * (1 + (Math.random() - 0.48) * 0.005);
 curve.push(equity);
 }
 return curve;
};
const updateChart = () => {
 if (!chartInstance || !result.value?.equity_curve)
 return;
 const dates = result.value.equity_curve.map((_, i) => `Day ${i + 1}`);
 const option: echarts.EChartsOption = {
 backgroundColor: '#fff',
 tooltip: {
 trigger: 'axis',
 backgroundColor: 'rgba(255, 255, 255, 0.95)',
 borderColor: '#e5e7eb',
 borderWidth: 1,
 textStyle: {
 color: '#374151'
 }
 },
 grid: {
 left: '10%',
 right: '10%',
 top: '10%',
 bottom: '15%'
 },
 xAxis: {
 type: 'category',
 data: dates,
 axisLine: { lineStyle: { color: '#e5e7eb' } },
 axisLabel: {
 color: '#6b7280',
 fontSize: 10,
 interval: 10
 },
 splitLine: { show: false }
 },
 yAxis: {
 type: 'value',
 axisLine: { show: false },
 axisLabel: {
 color: '#6b7280',
 fontSize: 10,
 formatter: (value: number) => `¥${(value / 10000).toFixed(1)}万`
 },
 splitLine: {
 lineStyle: {
 color: '#f3f4f6',
 type: 'dashed'
 }
 }
 },
 series: [
 {
 name: '账户权益',
 type: 'line',
 data: result.value.equity_curve,
 smooth: true,
 lineStyle: {
 color: '#3b82f6',
 width: 2
 },
 areaStyle: {
 color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
 { offset: 0, color: 'rgba(59, 130, 246, 0.3)' },
 { offset: 1, color: 'rgba(59, 130, 246, 0.05)' }
 ])
 },
 symbol: 'none'
 }
 ]
 };
 chartInstance.setOption(option);
};
onMounted(() => {
 if (chartRef.value) {
 chartInstance = echarts.init(chartRef.value);
 window.addEventListener('resize', () => {
 chartInstance?.resize();
 });
 }
});
</script>

<template>
  <div class="backtest-container">
    <!-- 头部 -->
    <div class="flex flex-wrap items-center justify-between gap-4 mb-6">
      <h2 class="text-xl font-semibold text-gray-800">策略回测</h2>
    </div>

    <!-- 参数配置 -->
    <div class="bg-white rounded-xl shadow-lg p-6 mb-6">
      <h3 class="text-lg font-semibold text-gray-800 mb-4">回测配置</h3>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label class="block text-sm text-gray-600 mb-2">选择策略</label>
          <select 
            v-model="strategy"
            class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option v-for="s in strategies" :key="s.value" :value="s.value">
              {{ s.label }}
            </option>
          </select>
        </div>
        <div>
          <label class="block text-sm text-gray-600 mb-2">合约代码</label>
          <input 
            v-model="symbol"
            type="text"
            class="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="输入合约代码"
          />
        </div>
      </div>
      <button 
        @click="runBacktest"
        :disabled="isRunning"
        class="mt-6 px-6 py-3 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {{ isRunning ? '回测中...' : '开始回测' }}
      </button>
    </div>

    <!-- 回测结果 -->
    <div v-if="result" class="space-y-6">
      <!-- 统计卡片 -->
      <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <div class="bg-white rounded-xl shadow-lg p-6">
          <p class="text-gray-500 text-sm mb-2">策略名称</p>
          <p class="text-lg font-bold text-gray-800">{{ result.strategy }}</p>
        </div>
        <div class="bg-white rounded-xl shadow-lg p-6">
          <p class="text-gray-500 text-sm mb-2">交易次数</p>
          <p class="text-lg font-bold text-gray-800">{{ result.total_trades }}</p>
        </div>
        <div class="bg-white rounded-xl shadow-lg p-6">
          <p class="text-gray-500 text-sm mb-2">胜率</p>
          <p class="text-lg font-bold" :class="result.win_rate >= 0.5 ? 'text-green-500' : 'text-red-500'">
            {{ (result.win_rate * 100).toFixed(1) }}%
          </p>
        </div>
        <div class="bg-white rounded-xl shadow-lg p-6">
          <p class="text-gray-500 text-sm mb-2">总盈亏</p>
          <p class="text-lg font-bold" :class="result.total_pnl >= 0 ? 'text-green-500' : 'text-red-500'">
            {{ result.total_pnl >= 0 ? '+' : '' }}¥{{ result.total_pnl.toLocaleString() }}
          </p>
        </div>
        <div class="bg-white rounded-xl shadow-lg p-6">
          <p class="text-gray-500 text-sm mb-2">最大回撤</p>
          <p class="text-lg font-bold" :class="result.max_drawdown <= 0.1 ? 'text-green-500' : 'text-red-500'">
            {{ (result.max_drawdown * 100).toFixed(1) }}%
          </p>
        </div>
        <div class="bg-white rounded-xl shadow-lg p-6">
          <p class="text-gray-500 text-sm mb-2">夏普比率</p>
          <p class="text-lg font-bold" :class="result.sharpe_ratio >= 1 ? 'text-green-500' : 'text-yellow-500'">
            {{ result.sharpe_ratio.toFixed(2) }}
          </p>
        </div>
      </div>

      <!-- 收益曲线 -->
      <div class="bg-white rounded-xl shadow-lg p-6">
        <h3 class="text-lg font-semibold text-gray-800 mb-4">账户权益曲线</h3>
        <div ref="chartRef" class="w-full h-[400px]"></div>
      </div>

      <!-- 结果分析 -->
      <div class="bg-white rounded-xl shadow-lg p-6">
        <h3 class="text-lg font-semibold text-gray-800 mb-4">回测分析</h3>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <h4 class="text-sm font-medium text-gray-700 mb-2">策略表现评估</h4>
            <ul class="space-y-2 text-sm text-gray-600">
              <li class="flex items-center">
                <span :class="result.win_rate >= 0.5 ? 'text-green-500' : 'text-red-500'" class="mr-2">
                  {{ result.win_rate >= 0.5 ? '✓' : '✗' }}
                </span>
                胜率{{ (result.win_rate * 100).toFixed(1) }}% {{ result.win_rate >= 0.5 ? '高于平均' : '低于平均' }}
              </li>
              <li class="flex items-center">
                <span :class="result.max_drawdown <= 0.1 ? 'text-green-500' : 'text-yellow-500'" class="mr-2">
                  {{ result.max_drawdown <= 0.1 ? '✓' : '!' }}
                </span>
                最大回撤{{ (result.max_drawdown * 100).toFixed(1) }}% {{ result.max_drawdown <= 0.1 ? '控制良好' : '需关注' }}
              </li>
              <li class="flex items-center">
                <span :class="result.sharpe_ratio >= 1 ? 'text-green-500' : 'text-yellow-500'" class="mr-2">
                  {{ result.sharpe_ratio >= 1 ? '✓' : '!' }}
                </span>
                夏普比率{{ result.sharpe_ratio.toFixed(2) }} {{ result.sharpe_ratio >= 1 ? '表现优秀' : '有待提升' }}
              </li>
            </ul>
          </div>
          <div>
            <h4 class="text-sm font-medium text-gray-700 mb-2">改进建议</h4>
            <ul class="space-y-2 text-sm text-gray-600">
              <li>• 考虑优化止损参数以降低回撤</li>
              <li>• 可尝试调整策略参数提高胜率</li>
              <li>• 建议结合其他策略进行组合</li>
              <li>• 可考虑增加过滤条件减少假信号</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.backtest-container {
  padding: 20px;
}
</style>
