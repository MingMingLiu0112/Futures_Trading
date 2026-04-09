import React, { useState, useMemo } from 'react';
import { OptionChainProps, OptionData, TShapeConfig } from '../types';
import OptionRow from './OptionRow';

const defaultConfig: TShapeConfig = {
  showFields: {
    price: true,           // 价格（最新价）
    openInterest: true,    // 持仓量
    volume: true,          // 成交量
    impliedVol: true,      // 隐含波动率
    ivChangeAbs: true,     // 隐波绝对值变化
    concentration: true,   // 持仓密集度（新增）
    intrinsicValue: false, // 内在价值（默认隐藏）
    greeks: true           // 希腊字母
  },
  sortBy: 'strike',
  ascending: true,
  maxDisplay: 10,
  highlightATM: true,
  highlightConcentration: true, // 高亮高密集度合约
  colorScheme: 'green-red'
};

const OptionChain: React.FC<OptionChainProps> = ({ 
  data, 
  config = {}, 
  onOptionClick,
  className = ''
}) => {
  const [currentConfig, setCurrentConfig] = useState<TShapeConfig>({
    ...defaultConfig,
    ...config
  });

  // 分离看涨和看跌期权
  const { calls, puts } = useMemo(() => {
    const calls: OptionData[] = [];
    const puts: OptionData[] = [];
    
    data.forEach(option => {
      if (option.optionType === 'C') {
        calls.push(option);
      } else {
        puts.push(option);
      }
    });
    
    return { calls, puts };
  }, [data]);

  // 排序函数
  const sortOptions = (options: OptionData[], sortBy: string, ascending: boolean): OptionData[] => {
    const sorted = [...options];
    
    sorted.sort((a, b) => {
      let valueA, valueB;
      
      switch (sortBy) {
        case 'strike':
          valueA = a.strikePrice;
          valueB = b.strikePrice;
          break;
        case 'volume':
          valueA = a.volume;
          valueB = b.volume;
          break;
        case 'openInterest':
          valueA = a.openInterest;
          valueB = b.openInterest;
          break;
        case 'impliedVol':
          valueA = a.impliedVol;
          valueB = b.impliedVol;
          break;
        case 'concentration':
          valueA = a.concentration;
          valueB = b.concentration;
          break;
        default:
          valueA = a.strikePrice;
          valueB = b.strikePrice;
      }
      
      return ascending ? valueA - valueB : valueB - valueA;
    });
    
    return sorted.slice(0, currentConfig.maxDisplay);
  };

  const sortedCalls = sortOptions(calls, currentConfig.sortBy, currentConfig.ascending);
  const sortedPuts = sortOptions(puts, currentConfig.sortBy, currentConfig.ascending);

  // 处理期权点击
  const handleOptionClick = (option: OptionData) => {
    if (onOptionClick) {
      onOptionClick(option);
    }
  };

  // 配置变更处理
  const handleConfigChange = (key: keyof TShapeConfig, value: any) => {
    setCurrentConfig(prev => ({
      ...prev,
      [key]: value
    }));
  };

  const handleFieldToggle = (field: keyof TShapeConfig['showFields']) => {
    setCurrentConfig(prev => ({
      ...prev,
      showFields: {
        ...prev.showFields,
        [field]: !prev.showFields[field]
      }
    }));
  };

  return (
    <div className={`option-chain-container ${className}`}>
      {/* 控制面板 */}
      <div className="controls mb-4">
        <div className="row g-3">
          <div className="col-md-6">
            <div className="mb-3">
              <label className="form-label">排序方式</label>
              <select 
                className="form-select"
                value={currentConfig.sortBy}
                onChange={(e) => handleConfigChange('sortBy', e.target.value)}
              >
                <option value="strike">行权价</option>
                <option value="volume">成交量</option>
                <option value="openInterest">持仓量</option>
                <option value="impliedVol">隐含波动率</option>
                <option value="concentration">持仓密集度</option>
              </select>
            </div>
          </div>
          
          <div className="col-md-6">
            <div className="mb-3">
              <label className="form-label">排序方向</label>
              <select 
                className="form-select"
                value={currentConfig.ascending ? 'asc' : 'desc'}
                onChange={(e) => handleConfigChange('ascending', e.target.value === 'asc')}
              >
                <option value="asc">升序</option>
                <option value="desc">降序</option>
              </select>
            </div>
          </div>
          
          <div className="col-md-12">
            <div className="mb-3">
              <label className="form-label me-3">显示字段:</label>
              <div className="form-check form-check-inline">
                <input
                  className="form-check-input"
                  type="checkbox"
                  checked={currentConfig.showFields.price}
                  onChange={() => handleFieldToggle('price')}
                  id="showPrice"
                />
                <label className="form-check-label" htmlFor="showPrice">价格</label>
              </div>
              <div className="form-check form-check-inline">
                <input
                  className="form-check-input"
                  type="checkbox"
                  checked={currentConfig.showFields.openInterest}
                  onChange={() => handleFieldToggle('openInterest')}
                  id="showOI"
                />
                <label className="form-check-label" htmlFor="showOI">持仓量</label>
              </div>
              <div className="form-check form-check-inline">
                <input
                  className="form-check-input"
                  type="checkbox"
                  checked={currentConfig.showFields.volume}
                  onChange={() => handleFieldToggle('volume')}
                  id="showVolume"
                />
                <label className="form-check-label" htmlFor="showVolume">成交量</label>
              </div>
              <div className="form-check form-check-inline">
                <input
                  className="form-check-input"
                  type="checkbox"
                  checked={currentConfig.showFields.impliedVol}
                  onChange={() => handleFieldToggle('impliedVol')}
                  id="showImpliedVol"
                />
                <label className="form-check-label" htmlFor="showImpliedVol">隐波</label>
              </div>
              <div className="form-check form-check-inline">
                <input
                  className="form-check-input"
                  type="checkbox"
                  checked={currentConfig.showFields.ivChangeAbs}
                  onChange={() => handleFieldToggle('ivChangeAbs')}
                  id="showIVChange"
                />
                <label className="form-check-label" htmlFor="showIVChange">隐波变化</label>
              </div>
              <div className="form-check form-check-inline">
                <input
                  className="form-check-input"
                  type="checkbox"
                  checked={currentConfig.showFields.concentration}
                  onChange={() => handleFieldToggle('concentration')}
                  id="showConcentration"
                />
                <label className="form-check-label" htmlFor="showConcentration">持仓密集度</label>
              </div>
              <div className="form-check form-check-inline">
                <input
                  className="form-check-input"
                  type="checkbox"
                  checked={currentConfig.showFields.intrinsicValue}
                  onChange={() => handleFieldToggle('intrinsicValue')}
                  id="showIntrinsic"
                />
                <label className="form-check-label" htmlFor="showIntrinsic">内在价值</label>
              </div>
              <div className="form-check form-check-inline">
                <input
                  className="form-check-input"
                  type="checkbox"
                  checked={currentConfig.showFields.greeks}
                  onChange={() => handleFieldToggle('greeks')}
                  id="showGreeks"
                />
                <label className="form-check-label" htmlFor="showGreeks">希腊字母</label>
              </div>
            </div>
          </div>
          
          <div className="col-md-6">
            <div className="mb-3">
              <label className="form-label">最大显示数量</label>
              <input
                type="range"
                className="form-range"
                min="5"
                max="20"
                step="1"
                value={currentConfig.maxDisplay}
                onChange={(e) => handleConfigChange('maxDisplay', parseInt(e.target.value))}
              />
              <div className="text-center">
                <span className="badge bg-primary">{currentConfig.maxDisplay} 个/侧</span>
              </div>
            </div>
          </div>
          
          <div className="col-md-6">
            <div className="row">
              <div className="col-6">
                <div className="form-check form-switch mt-3">
                  <input
                    className="form-check-input"
                    type="checkbox"
                    checked={currentConfig.highlightATM}
                    onChange={(e) => handleConfigChange('highlightATM', e.target.checked)}
                    id="highlightATM"
                  />
                  <label className="form-check-label" htmlFor="highlightATM">
                    高亮平值期权
                  </label>
                </div>
              </div>
              <div className="col-6">
                <div className="form-check form-switch mt-3">
                  <input
                    className="form-check-input"
                    type="checkbox"
                    checked={currentConfig.highlightConcentration}
                    onChange={(e) => handleConfigChange('highlightConcentration', e.target.checked)}
                    id="highlightConcentration"
                  />
                  <label className="form-check-label" htmlFor="highlightConcentration">
                    高亮高密集度
                  </label>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* T型期权链显示 */}
      <div className="t-shape-layout">
        {/* 看涨期权侧 */}
        <div className="calls-section">
          <div className="section-title">
            <i className="fas fa-arrow-up text-success me-2"></i>
            看涨期权 (Calls)
            <span className="badge bg-success ms-2">{sortedCalls.length}</span>
          </div>
          
          {sortedCalls.length > 0 ? (
            sortedCalls.map((option, index) => (
              <OptionRow
                key={`call-${option.contractCode}-${index}`}
                option={option}
                isCall={true}
                config={currentConfig}
                onClick={() => handleOptionClick(option)}
              />
            ))
          ) : (
            <div className="text-center text-muted py-4">
              <i className="fas fa-info-circle me-2"></i>
              暂无看涨期权数据
            </div>
          )}
        </div>

        {/* 看跌期权侧 */}
        <div className="puts-section">
          <div className="section-title">
            <i className="fas fa-arrow-down text-danger me-2"></i>
            看跌期权 (Puts)
            <span className="badge bg-danger ms-2">{sortedPuts.length}</span>
          </div>
          
          {sortedPuts.length > 0 ? (
            sortedPuts.map((option, index) => (
              <OptionRow
                key={`put-${option.contractCode}-${index}`}
                option={option}
                isCall={false}
                config={currentConfig}
                onClick={() => handleOptionClick(option)}
              />
            ))
          ) : (
            <div className="text-center text-muted py-4">
              <i className="fas fa-info-circle me-2"></i>
              暂无看跌期权数据
            </div>
          )}
        </div>
      </div>

      {/* 统计信息 */}
      <div className="mt-4 pt-3 border-top">
        <div className="row">
          <div className="col-md-6">
            <div className="text-muted small">
              <i className="fas fa-chart-bar me-1"></i>
              看涨期权总数: {calls.length} | 看跌期权总数: {puts.length}
            </div>
          </div>
          <div className="col-md-6 text-end">
            <div className="text-muted small">
              <i className="fas fa-sync-alt me-1"></i>
              显示: {sortedCalls.length + sortedPuts.length} / {data.length} 个合约
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default OptionChain;