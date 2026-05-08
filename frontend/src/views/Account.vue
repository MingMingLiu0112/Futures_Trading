<script setup lang="ts">import { ref, onMounted } from 'vue';
import * as echarts from 'echarts';
import { accountApi } from '../api';
import type { AccountInfo, TradeRecord } from '../types';
const accountInfo = ref<AccountInfo | null>(null);
const tradeHistory = ref<TradeRecord[]>([]);
const chartRef = ref<HTMLDivElement | null>(null);
let chartInstance: echarts.ECharts | null = null;
const loadAccountInfo = async () => {
 try {
 accountInfo.value = await accountApi.getAccountInfo();
 tradeHistory.value = await accountApi.getTradeHistory();
 }
 catch (error) {
 console.error('Failed to load account info:', error);
 // 使用模拟数据
 accountInfo.value = {
 balance: 1000000,
 equity: 1005230,
 margin: 25000,
 available: 975230,
 frozen: 0,
 unrealized_pnl: 5230,
 realized_pnl: 12580
 };
 tradeHistory.value = [
 {
 id: '1',
 symbol: 'TEST',
 direction: 'long',
 entry_price: 4980,
 exit_price: 5020,
 pnl: 40,
 pnl_pct: 0.008,
 entry_time: '2024-01-15 09:30:00',
 exit_time: '2024-01-15 10:15:00',
 status: 'closed'
 },
 {
 id: '2',
 symbol: 'TEST',
 direction: 'short',
 entry_price: 5050,
 exit_price: 5010,
 pnl: 40,
 pnl_pct: 0.0079,
 entry_time: '2024-01-14 14:20:00',
 exit_time: '2024-01-14 15:00:00',
 status: 'closed'
 },
 {
 id: '3',
 symbol: 'RB2401',
 direction: 'long',
 entry_price: 3820,
 exit_price: 3865,
 pnl: 45,
 pnl_pct: 0.0118,
 entry_time: '2024-01-14 10:00:00',
 exit_time: '2024-01-14 11:30:00',
 status: 'closed'
 },
 {
 id: '4',
 symbol: 'HC2401',
 direction: 'short',
 entry_price: 4250,
 exit_price: 4280,
 pnl: -30,
 pnl_pct: -0.0071,
 entry_time: '2024-01-13 14:00:00',
 exit_time: '2024-01-13 14:45:00',
 status: 'closed'
 },
 {
 id: '5',
 symbol: 'TEST',
 direction: 'long',
 entry_price: 5020,
 exit_price: 0,
 pnl: 0,
 pnl_pct: 0,
 entry_time: '2024-01-15 10:30:00',
 exit_time: '',
 status: 'open'
 }
 ];
 }
 updateChart();
};
const updateChart = () => {
 if (!chartInstance)
 return;
 const balanceHistory = [1000000, 1002500, 998000, 1005000, 1001500, 1008000, 1003500, 1005230];
 const dates = ['1/9', '1/10', '1/11', '1/12', '1/13', '1/14', '1/15', '1/16'];
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
 fontSize: 12
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
 name: '账户余额',
 type: 'line',
 data: balanceHistory,
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
 symbol: 'circle',
 symbolSize: 6
 }
 ]
 };
 chartInstance.setOption(option);
};
const getDirectionClass = (direction: string) => {
 return direction === 'long' ? 'text-green-500' : 'text-red-500';
};
const getPnlClass = (pnl: number) => {
 return pnl >= 0 ? 'text-green-500' : 'text-red-500';
};
const getStatusClass = (status: string) => {
 switch (status) {
 case 'open':
 return 'bg-blue-100 text-blue-800';
 case 'closed':
 return 'bg-gray-100 text-gray-800';
 case 'stopped':
 return 'bg-red-100 text-red-800';
 case 'targeted':
 return 'bg-green-100 text-green-800';
 default:
 return 'bg-gray-100 text-gray-800';
 }
};
const getStatusLabel = (status: string) => {
 switch (status) {
 case 'open':
 return '持有中';
 case 'closed':
 return '已平仓';
 case 'stopped':
 return '止损';
 case 'targeted':
 return '止盈';
 default:
 return status;
 }
};
onMounted(() => {
 loadAccountInfo();
 if (chartRef.value) {
 chartInstance = echarts.init(chartRef.value);
 window.addEventListener('resize', () => {
 chartInstance?.resize();
 });
 }
});
</script>

<template>
  <div class="account-container">
    <!-- 头部 -->
    <div class="flex items-center justify-between mb-6">
      <h2 class="text-xl font-semibold text-gray-800">账户信息</h2>
    </div>

    <!-- 账户概览 -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      <div class="bg-white rounded-xl shadow-lg p-6">
        <p class="text-gray-500 text-sm mb-2">账户余额</p>
        <p class="text-2xl font-bold text-gray-800">¥{{ accountInfo?.balance.toLocaleString() || '-' }}</p>
      </div>
      <div class="bg-white rounded-xl shadow-lg p-6">
        <p class="text-gray-500 text-sm mb-2">账户权益</p>
        <p class="text-2xl font-bold text-blue-500">¥{{ accountInfo?.equity.toLocaleString() || '-' }}</p>
      </div>
      <div class="bg-white rounded-xl shadow-lg p-6">
        <p class="text-gray-500 text-sm mb-2">可用资金</p>
        <p class="text-2xl font-bold text-purple-500">¥{{ accountInfo?.available.toLocaleString() || '-' }}</p>
      </div>
      <div class="bg-white rounded-xl shadow-lg p-6">
        <p class="text-gray-500 text-sm mb-2">已实现盈亏</p>
        <p class="text-2xl font-bold" :class="(accountInfo?.realized_pnl || 0) >= 0 ? 'text-green-500' : 'text-red-500'">
          {{ (accountInfo?.realized_pnl || 0) >= 0 ? '+' : '' }}¥{{ (accountInfo?.realized_pnl || 0).toLocaleString() }}
        </p>
      </div>
    </div>

    <!-- 余额趋势 -->
    <div class="bg-white rounded-xl shadow-lg p-6 mb-6">
      <h3 class="text-lg font-semibold text-gray-800 mb-4">账户余额趋势</h3>
      <div ref="chartRef" class="w-full h-[300px]"></div>
    </div>

    <!-- 交易历史 -->
    <div class="bg-white rounded-xl shadow-lg p-6">
      <h3 class="text-lg font-semibold text-gray-800 mb-4">交易历史</h3>
      
      <div class="overflow-x-auto">
        <table class="w-full">
          <thead class="bg-gray-50">
            <tr>
              <th class="px-6 py-4 text-left text-sm font-semibold text-gray-600">时间</th>
              <th class="px-6 py-4 text-left text-sm font-semibold text-gray-600">合约</th>
              <th class="px-6 py-4 text-center text-sm font-semibold text-gray-600">方向</th>
              <th class="px-6 py-4 text-right text-sm font-semibold text-gray-600">开仓价</th>
              <th class="px-6 py-4 text-right text-sm font-semibold text-gray-600">平仓价</th>
              <th class="px-6 py-4 text-right text-sm font-semibold text-gray-600">盈亏</th>
              <th class="px-6 py-4 text-center text-sm font-semibold text-gray-600">状态</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-200">
            <tr v-for="trade in tradeHistory" :key="trade.id" class="hover:bg-gray-50">
              <td class="px-6 py-4 text-sm text-gray-600">{{ trade.entry_time }}</td>
              <td class="px-6 py-4 text-sm font-medium text-gray-800">{{ trade.symbol }}</td>
              <td class="px-6 py-4 text-center">
                <span :class="getDirectionClass(trade.direction)" class="font-medium">
                  {{ trade.direction === 'long' ? '多头' : '空头' }}
                </span>
              </td>
              <td class="px-6 py-4 text-right text-sm text-gray-600">¥{{ trade.entry_price.toLocaleString() }}</td>
              <td class="px-6 py-4 text-right text-sm text-gray-600">
                {{ trade.exit_price > 0 ? `¥${trade.exit_price.toLocaleString()}` : '-' }}
              </td>
              <td class="px-6 py-4 text-right text-sm">
                <span :class="getPnlClass(trade.pnl)">
                  {{ trade.pnl >= 0 ? '+' : '' }}¥{{ trade.pnl.toLocaleString() }} ({{ (trade.pnl_pct * 100).toFixed(2) }}%)
                </span>
              </td>
              <td class="px-6 py-4 text-center">
                <span 
                  class="inline-flex items-center justify-center px-3 py-1 rounded-full text-sm font-medium"
                  :class="getStatusClass(trade.status)"
                >
                  {{ getStatusLabel(trade.status) }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="tradeHistory.length === 0" class="text-center py-12 text-gray-400">
          暂无交易记录
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.account-container {
  padding: 20px;
}
</style>
