import React, { useState, useEffect } from 'react';
import OptionChain from './components/OptionChain';
import MarketStats from './components/MarketStats';
import { OptionData, MarketStats as MarketStatsType } from './types';

// 模拟数据生成函数
const generateMockData = (): OptionData[] => {
  const data: OptionData[] = [];
  const underlyingPrice = 6920;
  const atmStrike = 6900;
  
  // 生成看涨期权
  for (let i = -5; i <= 5; i++) {
    const strike = atmStrike + i * 50;
    const isATM = strike === atmStrike;
    
    data.push({
      contractCode: `TA605C${strike}`,
      strikePrice: strike,
      optionType: 'C',
      price: Math.max(50, 100 - Math.abs(strike - underlyingPrice) * 0.5),
      priceChange: (Math.random() - 0.5) * 10,
      priceChangePercent: (Math.random() - 0.5) * 5,
      openInterest: Math.floor(Math.random() * 10000) + 1000,
      oiChange: (Math.random() - 0.5) * 500,
      oiChangePercent: (Math.random() - 0.5) * 10,
      volume: Math.floor(Math.random() * 5000) + 500,
      volumeChange: (Math.random() - 0.5) * 200,
      volumeChangePercent: (Math.random() - 0.5) * 15,
      impliedVol: 0.2 + Math.random() * 0.1,
      ivChange: (Math.random() - 0.5) * 0.02,
      ivChangeAbs: Math.abs((Math.random() - 0.5) * 0.02),
      greeks: {
        delta: 0.5 + (underlyingPrice - strike) / 1000,
        gamma: 0.01 + Math.random() * 0.02,
        theta: -0.05 - Math.random() * 0.02,
        vega: 0.1 + Math.random() * 0.05,
        rho: 0.03 + Math.random() * 0.02
      },
      underlyingPrice,
      timeToExpiry: 30,
      isATM
    });
  }
  
  // 生成看跌期权
  for (let i = -5; i <= 5; i++) {
    const strike = atmStrike + i * 50;
    const isATM = strike === atmStrike;
    
    data.push({
      contractCode: `TA605P${strike}`,
      strikePrice: strike,
      optionType: 'P',
      price: Math.max(30, 80 - Math.abs(strike - underlyingPrice) * 0.4),
      priceChange: (Math.random() - 0.5) * 8,
      priceChangePercent: (Math.random() - 0.5) * 4,
      openInterest: Math.floor(Math.random() * 8000) + 800,
      oiChange: (Math.random() - 0.5) * 400,
      oiChangePercent: (Math.random() - 0.5) * 8,
      volume: Math.floor(Math.random() * 4000) + 400,
      volumeChange: (Math.random() - 0.5) * 150,
      volumeChangePercent: (Math.random() - 0.5) * 12,
      impliedVol: 0.22 + Math.random() * 0.12,
      ivChange: (Math.random() - 0.5) * 0.025,
      ivChangeAbs: Math.abs((Math.random() - 0.5) * 0.025),
      greeks: {
        delta: -0.5 + (strike - underlyingPrice) / 1000,
        gamma: 0.01 + Math.random() * 0.02,
        theta: -0.04 - Math.random() * 0.02,
        vega: 0.12 + Math.random() * 0.06,
        rho: -0.02 - Math.random() * 0.01
      },
      underlyingPrice,
      timeToExpiry: 30,
      isATM
    });
  }
  
  return data;
};

// 生成市场统计数据
const generateMarketStats = (): MarketStatsType => {
  const now = new Date();
  return {
    underlyingPrice: 6920,
    atmStrike: 6900,
    totalVolume: 125430,
    totalOI: 892150,
    putCallRatio: 0.85,
    ivSkew: -0.035,
    maxPain: 6850,
    updateTime: now.toLocaleTimeString('zh-CN')
  };
};

const App: React.FC = () => {
  const [optionData, setOptionData] = useState<OptionData[]>([]);
  const [marketStats, setMarketStats] = useState<MarketStatsType | null>(null);
  const [loading, setLoading] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(true);

  // 加载数据
  const loadData = () => {
    setLoading(true);
    
    // 模拟API调用延迟
    setTimeout(() => {
      const data = generateMockData();
      const stats = generateMarketStats();
      
      setOptionData(data);
      setMarketStats(stats);
      setLoading(false);
    }, 500);
  };

  // 初始化加载
  useEffect(() => {
    loadData();
  }, []);

  // 自动刷新
  useEffect(() => {
    if (!autoRefresh) return;
    
    const interval = setInterval(() => {
      loadData();
    }, 30000); // 每30秒刷新一次
    
    return () => clearInterval(interval);
  }, [autoRefresh]);

  // 处理期权点击
  const handleOptionClick = (option: OptionData) => {
    console.log('期权被点击:', option);
    // 这里可以添加更多逻辑，比如显示详情、图表等
    alert(`选中期权: ${option.contractCode}\n行权价: ${option.strikePrice}\n价格: ${option.price}`);
  };

  // 手动刷新
  const handleRefresh = () => {
    loadData();
  };

  return (
    <div className="app-container">
      {/* 标题和控制 */}
      <div className="row mb-4">
        <div className="col-md-8">
          <h2 className="mb-0">
            <i className="fas fa-exchange-alt me-2 text-primary"></i>
            PTA期权链实时监控
          </h2>
          <p className="text-muted mb-0">
            简化字段：价格、持仓量变化%、成交量变化%、隐波绝对值变化、希腊字母
          </p>
        </div>
        <div className="col-md-4 text-end">
          <div className="btn-group">
            <button 
              className="btn btn-outline-primary"
              onClick={handleRefresh}
              disabled={loading}
            >
              <i className={`fas fa-sync-alt ${loading ? 'fa-spin' : ''} me-2`}></i>
              {loading ? '加载中...' : '刷新数据'}
            </button>
            <button 
              className={`btn ${autoRefresh ? 'btn-success' : 'btn-outline-success'}`}
              onClick={() => setAutoRefresh(!autoRefresh)}
            >
              <i className={`fas ${autoRefresh ? 'fa-pause' : 'fa-play'} me-2`}></i>
              {autoRefresh ? '自动刷新开' : '自动刷新关'}
            </button>
          </div>
        </div>
      </div>

      {/* 市场统计数据 */}
      {marketStats && (
        <div className="mb-4">
          <MarketStats stats={marketStats} />
        </div>
      )}

      {/* 期权链显示 */}
      <div className="mb-4">
        {loading ? (
          <div className="text-center py-5">
            <div className="spinner-border text-primary" role="status">
              <span className="visually-hidden">加载中...</span>
            </div>
            <p className="mt-3">正在加载期权数据...</p>
          </div>
        ) : (
          <OptionChain
            data={optionData}
            onOptionClick={handleOptionClick}
            config={{
              maxDisplay: 8,
              highlightATM: true
            }}
          />
        )}
      </div>

      {/* 说明和提示 */}
      <div className="row mt-4">
        <div className="col-md-6">
          <div className="alert alert-info">
            <h5><i className="fas fa-info-circle me-2"></i>使用说明</h5>
            <ul className="mb-0">
              <li>点击期权卡片查看详细信息</li>
              <li>使用上方控件自定义显示字段和排序</li>
              <li>绿色表示看涨期权，红色表示看跌期权</li>
              <li>平值期权会自动高亮显示</li>
            </ul>
          </div>
        </div>
        <div className="col-md-6">
          <div className="alert alert-light">
            <h5><i className="fas fa-lightbulb me-2"></i>数据解读</h5>
            <ul className="mb-0">
              <li><strong>持仓量变化%</strong>: 反映资金流向和市场情绪</li>
              <li><strong>成交量变化%</strong>: 反映短期交易活跃度</li>
              <li><strong>隐波变化</strong>: 反映市场波动预期变化</li>
              <li><strong>Put/Call比率</strong>: &gt;1看跌情绪，&lt;1看涨情绪</li>
            </ul>
          </div>
        </div>
      </div>

      {/* 集成说明 */}
      <div className="alert alert-success mt-3">
        <h5><i className="fas fa-plug me-2"></i>与PTA分析平台集成</h5>
        <p className="mb-2">
          此组件已设计为可轻松集成到现有PTA分析平台：
        </p>
        <ol className="mb-0">
          <li>将组件复制到平台的前端项目中</li>
          <li>连接后端API获取真实的期权数据</li>
          <li>调整样式以匹配平台设计规范</li>
          <li>添加数据自动更新和错误处理</li>
        </ol>
      </div>
    </div>
  );
};

export default App;