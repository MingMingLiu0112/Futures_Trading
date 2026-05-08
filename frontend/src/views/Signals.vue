<script setup lang="ts">import { ref, onMounted } from 'vue';
import { signalApi } from '../api';
import type { Signal } from '../types';
const signals = ref<Signal[]>([]);
const selectedStrategy = ref('all');
const strategies = [
 { value: 'all', label: '全部策略' },
 { value: 'MACD', label: 'MACD策略' },
 { value: 'MA', label: '均线策略' },
 { value: 'KDJ', label: 'KDJ策略' },
 { value: 'RSI', label: 'RSI策略' },
 { value: 'Bollinger', label: '布林带策略' },
 { value: 'ATR', label: 'ATR策略' }
];
const filteredSignals = ref<Signal[]>([]);
const loadSignals = async () => {
 try {
 signals.value = await signalApi.getSignals('TEST');
 }
 catch (error) {
 console.error('Failed to load signals:', error);
 // 使用模拟数据
 signals.value = [
 {
 id: '1',
 symbol: 'TEST',
 signal_type: 'buy',
 strategy: 'MACD',
 price: 5020,
 timestamp: '2024-01-15 10:30:00',
 stop_loss: 4980,
 take_profit: 5100,
 confidence: 0.75,
 indicator_value: 0.85
 },
 {
 id: '2',
 symbol: 'TEST',
 signal_type: 'sell',
 strategy: 'RSI',
 price: 5080,
 timestamp: '2024-01-15 09:45:00',
 stop_loss: 5120,
 take_profit: 5000,
 confidence: 0.82,
 indicator_value: 72.5
 },
 {
 id: '3',
 symbol: 'TEST',
 signal_type: 'buy',
 strategy: 'KDJ',
 price: 4950,
 timestamp: '2024-01-15 09:20:00',
 stop_loss: 4910,
 take_profit: 5030,
 confidence: 0.78,
 indicator_value: 25.3
 },
 {
 id: '4',
 symbol: 'TEST',
 signal_type: 'sell',
 strategy: 'Bollinger',
 price: 5150,
 timestamp: '2024-01-15 08:55:00',
 stop_loss: 5190,
 take_profit: 5070,
 confidence: 0.88,
 indicator_value: 2.1
 },
 {
 id: '5',
 symbol: 'TEST',
 signal_type: 'buy',
 strategy: 'ATR',
 price: 4920,
 timestamp: '2024-01-15 08:30:00',
 stop_loss: 4880,
 take_profit: 5000,
 confidence: 0.73,
 indicator_value: 35.8
 }
 ];
 }
 filterSignals();
};
const filterSignals = () => {
 if (selectedStrategy.value === 'all') {
 filteredSignals.value = signals.value;
 }
 else {
 filteredSignals.value = signals.value.filter(s => s.strategy === selectedStrategy.value);
 }
};
const getSignalTypeClass = (type: string) => {
 switch (type) {
 case 'buy':
 return 'bg-green-100 text-green-800';
 case 'sell':
 return 'bg-red-100 text-red-800';
 default:
 return 'bg-gray-100 text-gray-800';
 }
};
const getSignalTypeIcon = (type: string) => {
 switch (type) {
 case 'buy':
 return '↑';
 case 'sell':
 return '↓';
 default:
 return '-';
 }
};
onMounted(() => {
 loadSignals();
});
</script>

<template>
  <div class="signals-container">
    <!-- 头部 -->
    <div class="flex flex-wrap items-center justify-between gap-4 mb-6">
      <h2 class="text-xl font-semibold text-gray-800">交易信号</h2>
      <select 
        v-model="selectedStrategy" 
        @change="filterSignals"
        class="px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
      >
        <option v-for="strategy in strategies" :key="strategy.value" :value="strategy.value">
          {{ strategy.label }}
        </option>
      </select>
    </div>

    <!-- 统计卡片 -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
      <div class="bg-white rounded-xl shadow-lg p-6">
        <p class="text-gray-500 text-sm mb-2">总信号数</p>
        <p class="text-3xl font-bold text-gray-800">{{ filteredSignals.length }}</p>
      </div>
      <div class="bg-white rounded-xl shadow-lg p-6">
        <p class="text-gray-500 text-sm mb-2">买入信号</p>
        <p class="text-3xl font-bold text-green-500">
          {{ filteredSignals.filter(s => s.signal_type === 'buy').length }}
        </p>
      </div>
      <div class="bg-white rounded-xl shadow-lg p-6">
        <p class="text-gray-500 text-sm mb-2">卖出信号</p>
        <p class="text-3xl font-bold text-red-500">
          {{ filteredSignals.filter(s => s.signal_type === 'sell').length }}
        </p>
      </div>
    </div>

    <!-- 信号列表 -->
    <div class="bg-white rounded-xl shadow-lg overflow-hidden">
      <table class="w-full">
        <thead class="bg-gray-50">
          <tr>
            <th class="px-6 py-4 text-left text-sm font-semibold text-gray-600">时间</th>
            <th class="px-6 py-4 text-left text-sm font-semibold text-gray-600">策略</th>
            <th class="px-6 py-4 text-center text-sm font-semibold text-gray-600">信号类型</th>
            <th class="px-6 py-4 text-right text-sm font-semibold text-gray-600">价格</th>
            <th class="px-6 py-4 text-right text-sm font-semibold text-gray-600">止损</th>
            <th class="px-6 py-4 text-right text-sm font-semibold text-gray-600">止盈</th>
            <th class="px-6 py-4 text-center text-sm font-semibold text-gray-600">置信度</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-200">
          <tr 
            v-for="signal in filteredSignals" 
            :key="signal.id"
            class="hover:bg-gray-50 transition-colors"
          >
            <td class="px-6 py-4 text-sm text-gray-600">{{ signal.timestamp }}</td>
            <td class="px-6 py-4 text-sm font-medium text-gray-800">{{ signal.strategy }}</td>
            <td class="px-6 py-4 text-center">
              <span 
                class="inline-flex items-center justify-center w-12 h-8 rounded-full text-sm font-medium"
                :class="getSignalTypeClass(signal.signal_type)"
              >
                {{ getSignalTypeIcon(signal.signal_type) }} {{ signal.signal_type.toUpperCase() }}
              </span>
            </td>
            <td class="px-6 py-4 text-right text-sm font-medium text-gray-800">¥{{ signal.price.toLocaleString() }}</td>
            <td class="px-6 py-4 text-right text-sm text-gray-600">¥{{ signal.stop_loss?.toLocaleString() || '-' }}</td>
            <td class="px-6 py-4 text-right text-sm text-gray-600">¥{{ signal.take_profit?.toLocaleString() || '-' }}</td>
            <td class="px-6 py-4 text-center">
              <div class="flex items-center justify-center">
                <div class="w-20 h-2 bg-gray-200 rounded-full overflow-hidden mr-2">
                  <div 
                    class="h-full rounded-full transition-all"
                    :class="(signal.confidence || 0) >= 0.7 ? 'bg-green-500' : (signal.confidence || 0) >= 0.5 ? 'bg-yellow-500' : 'bg-red-500'"
                    :style="{ width: `${(signal.confidence || 0) * 100}%` }"
                  ></div>
                </div>
                <span class="text-sm text-gray-600">{{ Math.round((signal.confidence || 0) * 100) }}%</span>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="filteredSignals.length === 0" class="text-center py-12 text-gray-400">
        暂无信号数据
      </div>
    </div>
  </div>
</template>

<style scoped>
.signals-container {
  padding: 20px;
}
</style>
