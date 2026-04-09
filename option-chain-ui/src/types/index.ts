// 期权数据类型定义 - 根据用户需求更新
export interface OptionData {
  contractCode: string;      // 合约代码，如 TA605C6400
  strikePrice: number;       // 行权价
  optionType: 'C' | 'P';     // 期权类型：C=看涨，P=看跌
  
  // 核心显示字段（用户要求）
  price: number;            // 当前价格（最新价）
  openInterest: number;     // 持仓量
  volume: number;           // 成交量
  impliedVol: number;       // 隐含波动率
  ivChangeAbs: number;      // 隐波绝对值变化
  
  // 新增字段
  intrinsicValue?: number;   // 内在价值（可选）
  concentration: number;     // 持仓密集度：当前合约持仓量 / ((上相邻+下相邻)/2)
  
  // 希腊字母（用户要求保留）
  greeks: {
    delta: number;          // Delta值
    gamma: number;          // Gamma值
    theta: number;          // Theta值
    vega: number;           // Vega值
  };
  
  // 基础信息
  underlyingPrice: number;  // 标的物价格
  timeToExpiry: number;     // 到期时间（天数）
  isATM: boolean;           // 是否为平值期权
  
  // 已删除字段（用户要求）：
  // priceChange, priceChangePercent, oiChange, oiChangePercent, 
  // volumeChange, volumeChangePercent, ivChange, rho
}

// T型显示配置 - 根据用户需求更新
export interface TShapeConfig {
  showFields: {
    price: boolean;          // 价格（最新价）
    openInterest: boolean;   // 持仓量
    volume: boolean;         // 成交量
    impliedVol: boolean;     // 隐含波动率
    ivChangeAbs: boolean;    // 隐波绝对值变化
    concentration: boolean;  // 持仓密集度（新增）
    intrinsicValue: boolean; // 内在价值（可选）
    greeks: boolean;         // 希腊字母
  };
  sortBy: 'strike' | 'volume' | 'openInterest' | 'impliedVol' | 'concentration';
  ascending: boolean;
  maxDisplay: number;       // 最大显示数量
  highlightATM: boolean;    // 高亮平值期权
  highlightConcentration: boolean; // 高亮高密集度合约
  colorScheme: 'green-red' | 'blue-orange' | 'monochrome';
}

// 市场统计数据
export interface MarketStats {
  underlyingPrice: number;
  atmStrike: number;
  totalVolume: number;
  totalOI: number;
  putCallRatio: number;
  ivSkew: number;
  maxPain: number;
  updateTime: string;
}

// 组件Props
export interface OptionChainProps {
  data: OptionData[];
  config?: Partial<TShapeConfig>;
  onOptionClick?: (option: OptionData) => void;
  className?: string;
}

export interface OptionRowProps {
  option: OptionData;
  isCall: boolean;
  config: TShapeConfig;
  onClick?: () => void;
}

export interface MarketStatsProps {
  stats: MarketStats;
}