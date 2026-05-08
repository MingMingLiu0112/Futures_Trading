import axios, { type AxiosResponse } from 'axios'

const baseURL = import.meta.env.VITE_API_URL || 'http://localhost:5000/api'

const api = axios.create({
  baseURL,
  timeout: 10000
})

api.interceptors.request.use(
  (config) => config,
  (error) => Promise.reject(error)
)

api.interceptors.response.use(
  (response: AxiosResponse) => response.data,
  (error) => {
    console.error('API Error:', error)
    return Promise.reject(error)
  }
)

export const dataApi = {
  async getKlines(symbol: string, frequency: string = '1min') {
    return api.get(`/data/klines?symbol=${symbol}&frequency=${frequency}`) as Promise<any[]>
  },
  async collectData(symbol: string) {
    return api.post('/data/collect', { symbol }) as Promise<{ status: string; count: number }>
  }
}

export const signalApi = {
  async getSignals(symbol: string) {
    return api.get(`/signals?symbol=${symbol}`) as Promise<any[]>
  },
  async getSignalHistory(symbol: string, strategy: string) {
    return api.get(`/signals/history?symbol=${symbol}&strategy=${strategy}`) as Promise<any[]>
  }
}

export const backtestApi = {
  async runBacktest(strategy: string, symbol: string, params?: Record<string, any>) {
    return api.post('/backtest/run', { strategy, symbol, params }) as Promise<any>
  },
  async getResults() {
    return api.get('/backtest/results') as Promise<any[]>
  },
  async compareStrategies(strategies: string[], symbol: string) {
    return api.post('/backtest/compare', { strategies, symbol }) as Promise<any[]>
  }
}

export const riskApi = {
  async getRiskLimits() {
    return api.get('/risk/limits') as Promise<any>
  },
  async updateRiskLimits(limits: Record<string, any>) {
    return api.put('/risk/limits', limits) as Promise<any>
  },
  async getPositionStatus() {
    return api.get('/risk/positions') as Promise<any>
  }
}

export const accountApi = {
  async getAccountInfo() {
    return api.get('/account/info') as Promise<any>
  },
  async getTradeHistory() {
    return api.get('/account/trades') as Promise<any[]>
  },
  async getBalanceHistory() {
    return api.get('/account/balance') as Promise<any[]>
  }
}

export default api
