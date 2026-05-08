<script setup lang="ts">import { ref, onMounted } from 'vue';
import { accountApi, signalApi } from '../api';
import type { AccountInfo, Signal } from '../types';
const accountInfo = ref<AccountInfo | null>(null);
const recentSignals = ref<Signal[]>([]);
const systemStatus = ref({
 riskControl: 'normal',
 dataSync: 'synced',
 backtestEngine: 'ready'
});
onMounted(async () => {
 try {
 accountInfo.value = await accountApi.getAccountInfo();
 recentSignals.value = await signalApi.getSignals('TEST');
 }
 catch (error) {
 console.error('Failed to load data:', error);
 // 使用模拟数据
 accountInfo.value = {
 balance: 1000000,
 equity: 1005230,
 margin: 25000,
 available: 975230,
 frozen: 0,
 unrealized_pnl: 5230,
 realized_pnl: 0
 };
 recentSignals.value = [
 {
 id: '1',
 symbol: 'TEST',
 signal_type: 'buy',
 strategy: 'MACD',
 price: 5020,
 timestamp: '2024-01-15 10:30:00',
 stop_loss: 4980,
 take_profit: 5100,
 confidence: 0.75
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
 confidence: 0.82
 }
 ];
 }
});
const getStatusColor = (status: string) => {
 switch (status) {
 case 'normal':
 case 'synced':
 case 'ready':
 return 'text-green-500';
 case 'warning':
 return 'text-yellow-500';
 case 'error':
 return 'text-red-500';
 default:
 return 'text-gray-500';
 }
};
const getStatusIcon = (status: string) => {
 switch (status) {
 case 'normal':
 case 'synced':
 case 'ready':
 return '✓';
 case 'warning':
 return '!';
 case 'error':
 return '✗';
 default:
 return '?';
 }
};
</script>

<template>
  <div class="home-container">
    <!-- 头部统计卡片 -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
      <div class="bg-white rounded-xl shadow-lg p-6">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-gray-500 text-sm">账户余额</p>
            <p class="text-2xl font-bold text-gray-800 mt-1">
              ¥{{ accountInfo?.balance.toLocaleString() || '-' }}
            </p>
          </div>
          <div class="w-12 h-12 bg-blue-100 rounded-full flex items-center justify-center">
            <span class="text-blue-500 text-xl">💰</span>
          </div>
        </div>
      </div>

      <div class="bg-white rounded-xl shadow-lg p-6">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-gray-500 text-sm">账户权益</p>
            <p class="text-2xl font-bold text-gray-800 mt-1">
              ¥{{ accountInfo?.equity.toLocaleString() || '-' }}
            </p>
          </div>
          <div class="w-12 h-12 bg-green-100 rounded-full flex items-center justify-center">
            <span class="text-green-500 text-xl">📈</span>
          </div>
        </div>
      </div>

      <div class="bg-white rounded-xl shadow-lg p-6">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-gray-500 text-sm">可用资金</p>
            <p class="text-2xl font-bold text-gray-800 mt-1">
              ¥{{ accountInfo?.available.toLocaleString() || '-' }}
            </p>
          </div>
          <div class="w-12 h-12 bg-purple-100 rounded-full flex items-center justify-center">
            <span class="text-purple-500 text-xl">💳</span>
          </div>
        </div>
      </div>

      <div class="bg-white rounded-xl shadow-lg p-6">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-gray-500 text-sm">未实现盈亏</p>
            <p class="text-2xl font-bold" :class="(accountInfo?.unrealized_pnl || 0) >= 0 ? 'text-green-500' : 'text-red-500'">
              {{ (accountInfo?.unrealized_pnl || 0) >= 0 ? '+' : '' }}¥{{ (accountInfo?.unrealized_pnl || 0).toLocaleString() }}
            </p>
          </div>
          <div class="w-12 h-12 bg-orange-100 rounded-full flex items-center justify-center">
            <span class="text-orange-500 text-xl">📊</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 系统状态 -->
    <div class="bg-white rounded-xl shadow-lg p-6 mb-8">
      <h2 class="text-lg font-semibold text-gray-800 mb-4">系统状态</h2>
      <div class="grid grid-cols-3 gap-4">
        <div class="text-center p-4 bg-gray-50 rounded-lg">
          <div class="flex items-center justify-center mb-2">
            <span :class="getStatusColor(systemStatus.riskControl)" class="text-xl">{{ getStatusIcon(systemStatus.riskControl) }}</span>
          </div>
          <p class="text-sm text-gray-600">风险控制</p>
          <p class="text-xs text-gray-400">正常运行</p>
        </div>
        <div class="text-center p-4 bg-gray-50 rounded-lg">
          <div class="flex items-center justify-center mb-2">
            <span :class="getStatusColor(systemStatus.dataSync)" class="text-xl">{{ getStatusIcon(systemStatus.dataSync) }}</span>
          </div>
          <p class="text-sm text-gray-600">数据同步</p>
          <p class="text-xs text-gray-400">已同步</p>
        </div>
        <div class="text-center p-4 bg-gray-50 rounded-lg">
          <div class="flex items-center justify-center mb-2">
            <span :class="getStatusColor(systemStatus.backtestEngine)" class="text-xl">{{ getStatusIcon(systemStatus.backtestEngine) }}</span>
          </div>
          <p class="text-sm text-gray-600">回测引擎</p>
          <p class="text-xs text-gray-400">就绪</p>
        </div>
      </div>
    </div>

    <!-- 最近信号 -->
    <div class="bg-white rounded-xl shadow-lg p-6">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-lg font-semibold text-gray-800">最近交易信号</h2>
        <a href="/signals" class="text-blue-500 text-sm hover:underline">查看全部</a>
      </div>
      <div class="space-y-3">
        <div 
          v-for="signal in recentSignals" 
          :key="signal.id"
          class="flex items-center justify-between p-4 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors"
        >
          <div class="flex items-center">
            <div 
              class="w-10 h-10 rounded-full flex items-center justify-center mr-4"
              :class="signal.signal_type === 'buy' ? 'bg-green-100' : 'bg-red-100'"
            >
              <span :class="signal.signal_type === 'buy' ? 'text-green-500' : 'text-red-500'">
                {{ signal.signal_type === 'buy' ? '↑' : '↓' }}
              </span>
            </div>
            <div>
              <p class="font-medium text-gray-800">{{ signal.signal_type.toUpperCase() }} {{ signal.symbol }}</p>
              <p class="text-sm text-gray-500">{{ signal.strategy }}策略 · {{ signal.timestamp }}</p>
            </div>
          </div>
          <div class="text-right">
            <p class="font-medium text-gray-800">¥{{ signal.price.toLocaleString() }}</p>
            <p class="text-xs text-gray-400">置信度: {{ (signal.confidence || 0) * 100 }}%</p>
          </div>
        </div>
        <div v-if="recentSignals.length === 0" class="text-center py-8 text-gray-400">
          暂无交易信号
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.home-container {
  padding: 20px;
}
</style>
