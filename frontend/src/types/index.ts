// K线数据类型
export interface KlineData {
  timestamp: string
  open: number
  high: number
  low: number
  close: number
  volume?: number
  indicators?: IndicatorData
}

// 指标数据类型
export interface IndicatorData {
  ma5?: number
  ma10?: number
  ma20?: number
  ma60?: number
  ema12?: number
  ema26?: number
  dif?: number
  dea?: number
  macd?: number
  k?: number
  d?: number
  j?: number
  rsi?: number
  upper_band?: number
  middle_band?: number
  lower_band?: number
  atr?: number
  obv?: number
}

// 交易信号类型
export interface Signal {
  id: string
  symbol: string
  signal_type: 'buy' | 'sell' | 'hold'
  strategy: string
  price: number
  timestamp: string
  stop_loss?: number
  take_profit?: number
  confidence?: number
  indicator_value?: number
}

// 回测结果类型
export interface BacktestResult {
  strategy: string
  total_trades: number
  win_rate: number
  total_pnl: number
  max_drawdown: number
  sharpe_ratio: number
  profit_factor: number
  equity_curve?: number[]
  trade_history?: TradeRecord[]
}

// 交易记录类型
export interface TradeRecord {
  id: string
  symbol: string
  direction: 'long' | 'short'
  entry_price: number
  exit_price: number
  pnl: number
  pnl_pct: number
  entry_time: string
  exit_time: string
  status: 'open' | 'closed' | 'stopped' | 'targeted'
}

// 风险限制类型
export interface RiskLimits {
  max_drawdown: number
  risk_per_trade: number
  max_position_size: number
  stop_loss_pct: number
  take_profit_pct: number
}

// 账户信息类型
export interface AccountInfo {
  balance: number
  equity: number
  margin: number
  available: number
  frozen: number
  unrealized_pnl: number
  realized_pnl: number
}

// 策略信息类型
export interface StrategyInfo {
  name: string
  description: string
  parameters: StrategyParameter[]
}

// 策略参数类型
export interface StrategyParameter {
  name: string
  type: 'number' | 'string' | 'boolean'
  default: any
  min?: number
  max?: number
  step?: number
}

// 图表配置类型
export interface ChartConfig {
  type: 'kline' | 'line' | 'bar' | 'area'
  title: string
  data: any[]
  indicators?: string[]
  showVolume?: boolean
}
