<script setup lang="ts">import { ref, onMounted } from 'vue';
import { riskApi } from '../api';
import type { RiskLimits } from '../types';
const riskLimits = ref<RiskLimits>({
 max_drawdown: 0.1,
 risk_per_trade: 0.01,
 max_position_size: 0.1,
 stop_loss_pct: 0.02,
 take_profit_pct: 0.04
});
const isSaving = ref(false);
const loadRiskLimits = async () => {
 try {
 riskLimits.value = await riskApi.getRiskLimits();
 }
 catch (error) {
 console.error('Failed to load risk limits:', error);
 }
};
const saveRiskLimits = async () => {
 isSaving.value = true;
 try {
 await riskApi.updateRiskLimits(riskLimits.value);
 alert('风险参数保存成功！');
 }
 catch (error) {
 console.error('Failed to save risk limits:', error);
 alert('保存失败，请重试');
 }
 isSaving.value = false;
};
const positionStatus = ref([
 { symbol: 'TEST', direction: 'long', quantity: 2, avg_cost: 5020, current_price: 5080, pnl: 120, pnl_pct: 0.0119, margin: 25100 },
 { symbol: 'RB2401', direction: 'short', quantity: 1, avg_cost: 3850, current_price: 3820, pnl: 30, pnl_pct: 0.0078, margin: 19250 }
]);
const getPnlClass = (pnl: number) => {
 return pnl >= 0 ? 'text-green-500' : 'text-red-500';
};
onMounted(() => {
 loadRiskLimits();
});
</script>

<template>
  <div class="risk-container">
    <!-- 头部 -->
    <div class="flex items-center justify-between mb-6">
      <h2 class="text-xl font-semibold text-gray-800">风险控制</h2>
    </div>

    <!-- 风险参数配置 -->
    <div class="bg-white rounded-xl shadow-lg p-6 mb-6">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-lg font-semibold text-gray-800">风险参数配置</h3>
        <button 
          @click="saveRiskLimits"
          :disabled="isSaving"
          class="px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors disabled:opacity-50"
        >
          {{ isSaving ? '保存中...' : '保存配置' }}
        </button>
      </div>
      
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <div>
          <label class="block text-sm text-gray-600 mb-2">最大回撤限制</label>
          <div class="flex items-center gap-4">
            <input 
              v-model.number="riskLimits.max_drawdown"
              type="range"
              min="0.01"
              max="0.3"
              step="0.01"
              class="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-500"
            />
            <span class="text-sm font-medium text-gray-800 w-16 text-right">{{ (riskLimits.max_drawdown * 100).toFixed(0) }}%</span>
          </div>
          <p class="text-xs text-gray-400 mt-1">账户最大允许回撤比例</p>
        </div>

        <div>
          <label class="block text-sm text-gray-600 mb-2">单笔风险比例</label>
          <div class="flex items-center gap-4">
            <input 
              v-model.number="riskLimits.risk_per_trade"
              type="range"
              min="0.005"
              max="0.05"
              step="0.005"
              class="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-500"
            />
            <span class="text-sm font-medium text-gray-800 w-16 text-right">{{ (riskLimits.risk_per_trade * 100).toFixed(1) }}%</span>
          </div>
          <p class="text-xs text-gray-400 mt-1">每笔交易允许的最大风险</p>
        </div>

        <div>
          <label class="block text-sm text-gray-600 mb-2">最大仓位比例</label>
          <div class="flex items-center gap-4">
            <input 
              v-model.number="riskLimits.max_position_size"
              type="range"
              min="0.05"
              max="0.5"
              step="0.05"
              class="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-500"
            />
            <span class="text-sm font-medium text-gray-800 w-16 text-right">{{ (riskLimits.max_position_size * 100).toFixed(0) }}%</span>
          </div>
          <p class="text-xs text-gray-400 mt-1">单一合约最大持仓比例</p>
        </div>

        <div>
          <label class="block text-sm text-gray-600 mb-2">默认止损比例</label>
          <div class="flex items-center gap-4">
            <input 
              v-model.number="riskLimits.stop_loss_pct"
              type="range"
              min="0.005"
              max="0.1"
              step="0.005"
              class="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-500"
            />
            <span class="text-sm font-medium text-gray-800 w-16 text-right">{{ (riskLimits.stop_loss_pct * 100).toFixed(1) }}%</span>
          </div>
          <p class="text-xs text-gray-400 mt-1">新订单默认止损比例</p>
        </div>

        <div>
          <label class="block text-sm text-gray-600 mb-2">默认止盈比例</label>
          <div class="flex items-center gap-4">
            <input 
              v-model.number="riskLimits.take_profit_pct"
              type="range"
              min="0.005"
              max="0.2"
              step="0.005"
              class="flex-1 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-500"
            />
            <span class="text-sm font-medium text-gray-800 w-16 text-right">{{ (riskLimits.take_profit_pct * 100).toFixed(1) }}%</span>
          </div>
          <p class="text-xs text-gray-400 mt-1">新订单默认止盈比例</p>
        </div>
      </div>
    </div>

    <!-- 当前持仓状态 -->
    <div class="bg-white rounded-xl shadow-lg p-6">
      <h3 class="text-lg font-semibold text-gray-800 mb-4">当前持仓状态</h3>
      
      <div class="overflow-x-auto">
        <table class="w-full">
          <thead class="bg-gray-50">
            <tr>
              <th class="px-6 py-4 text-left text-sm font-semibold text-gray-600">合约</th>
              <th class="px-6 py-4 text-center text-sm font-semibold text-gray-600">方向</th>
              <th class="px-6 py-4 text-right text-sm font-semibold text-gray-600">持仓数量</th>
              <th class="px-6 py-4 text-right text-sm font-semibold text-gray-600">持仓成本</th>
              <th class="px-6 py-4 text-right text-sm font-semibold text-gray-600">当前价格</th>
              <th class="px-6 py-4 text-right text-sm font-semibold text-gray-600">盈亏</th>
              <th class="px-6 py-4 text-right text-sm font-semibold text-gray-600">占用保证金</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-200">
            <tr v-for="pos in positionStatus" :key="pos.symbol" class="hover:bg-gray-50">
              <td class="px-6 py-4 text-sm font-medium text-gray-800">{{ pos.symbol }}</td>
              <td class="px-6 py-4 text-center">
                <span 
                  class="inline-flex items-center justify-center px-3 py-1 rounded-full text-sm font-medium"
                  :class="pos.direction === 'long' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'"
                >
                  {{ pos.direction === 'long' ? '多头' : '空头' }}
                </span>
              </td>
              <td class="px-6 py-4 text-right text-sm text-gray-600">{{ pos.quantity }}</td>
              <td class="px-6 py-4 text-right text-sm text-gray-600">¥{{ pos.avg_cost.toLocaleString() }}</td>
              <td class="px-6 py-4 text-right text-sm text-gray-600">¥{{ pos.current_price.toLocaleString() }}</td>
              <td class="px-6 py-4 text-right text-sm">
                <span :class="getPnlClass(pos.pnl)">
                  {{ pos.pnl >= 0 ? '+' : '' }}¥{{ pos.pnl.toLocaleString() }} ({{ (pos.pnl_pct * 100).toFixed(2) }}%)
                </span>
              </td>
              <td class="px-6 py-4 text-right text-sm text-gray-600">¥{{ pos.margin.toLocaleString() }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="positionStatus.length === 0" class="text-center py-12 text-gray-400">
          当前无持仓
        </div>
      </div>

      <!-- 持仓汇总 -->
      <div class="mt-6 pt-6 border-t border-gray-200">
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div class="text-center">
            <p class="text-gray-500 text-sm">总持仓数</p>
            <p class="text-xl font-bold text-gray-800">{{ positionStatus.reduce((sum, p) => sum + p.quantity, 0) }}</p>
          </div>
          <div class="text-center">
            <p class="text-gray-500 text-sm">多头持仓</p>
            <p class="text-xl font-bold text-green-500">
              {{ positionStatus.filter(p => p.direction === 'long').reduce((sum, p) => sum + p.quantity, 0) }}
            </p>
          </div>
          <div class="text-center">
            <p class="text-gray-500 text-sm">空头持仓</p>
            <p class="text-xl font-bold text-red-500">
              {{ positionStatus.filter(p => p.direction === 'short').reduce((sum, p) => sum + p.quantity, 0) }}
            </p>
          </div>
          <div class="text-center">
            <p class="text-gray-500 text-sm">总盈亏</p>
            <p class="text-xl font-bold" :class="positionStatus.reduce((sum, p) => sum + p.pnl, 0) >= 0 ? 'text-green-500' : 'text-red-500'">
              {{ positionStatus.reduce((sum, p) => sum + p.pnl, 0) >= 0 ? '+' : '' }}¥{{ positionStatus.reduce((sum, p) => sum + p.pnl, 0).toLocaleString() }}
            </p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.risk-container {
  padding: 20px;
}
</style>
