import React from 'react';
import { OptionRowProps } from '../types';

const OptionRow: React.FC<OptionRowProps> = ({ option, isCall, config, onClick }) => {
  const {
    contractCode,
    strikePrice,
    price,
    openInterest,
    volume,
    impliedVol,
    ivChangeAbs,
    concentration,
    intrinsicValue,
    greeks,
    isATM
  } = option;

  const formatPercent = (value: number): string => {
    if (value === undefined || value === null) return '--';
    return `${value.toFixed(2)}%`;
  };

  const formatNumber = (value: number, decimals: number = 2): string => {
    if (value === undefined || value === null) return '--';
    return value.toFixed(decimals);
  };

  const getChangeColor = (value: number): string => {
    if (value > 0) return 'positive';
    if (value < 0) return 'negative';
    return 'neutral';
  };

  const getConcentrationColor = (value: number): string => {
    if (value > 1.5) return 'text-warning fw-bold'; // 高密集度
    if (value > 1.2) return 'text-info';           // 中等密集度
    if (value > 0.8) return '';                    // 正常范围
    return 'text-muted';                           // 低密集度
  };

  const optionClass = isCall ? 'call-option' : 'put-option';
  const atmClass = isATM ? 'atm-highlight' : '';
  const concentrationClass = config.highlightConcentration && concentration > 1.5 ? 'concentration-highlight' : '';

  return (
    <div 
      className={`${optionClass} ${atmClass} ${concentrationClass}`}
      onClick={onClick}
      style={{ cursor: onClick ? 'pointer' : 'default' }}
    >
      <div className="option-header mb-2">
        <div className="d-flex justify-content-between align-items-center">
          <div>
            <strong>{contractCode}</strong>
            <span className="ms-2 text-muted">行权价: {strikePrice}</span>
          </div>
          <div className={`badge ${isCall ? 'bg-success' : 'bg-danger'}`}>
            {isCall ? '看涨' : '看跌'}
          </div>
        </div>
      </div>

      <div className="option-fields">
        {/* 价格（最新价） */}
        {config.showFields.price && (
          <div className="option-field">
            <span className="field-label">价格:</span>
            <span className="field-value">
              {formatNumber(price)}
            </span>
          </div>
        )}

        {/* 内在价值（可选） */}
        {config.showFields.intrinsicValue && intrinsicValue !== undefined && (
          <div className="option-field">
            <span className="field-label">内在价值:</span>
            <span className="field-value">
              {formatNumber(intrinsicValue)}
            </span>
          </div>
        )}

        {/* 持仓量 */}
        {config.showFields.openInterest && (
          <div className="option-field">
            <span className="field-label">持仓量:</span>
            <span className="field-value">
              {formatNumber(openInterest, 0)}
            </span>
          </div>
        )}

        {/* 成交量 */}
        {config.showFields.volume && (
          <div className="option-field">
            <span className="field-label">成交量:</span>
            <span className="field-value">
              {formatNumber(volume, 0)}
            </span>
          </div>
        )}

        {/* 隐含波动率 */}
        {config.showFields.impliedVol && (
          <div className="option-field">
            <span className="field-label">隐波:</span>
            <span className="field-value">
              {formatPercent(impliedVol)}
            </span>
          </div>
        )}

        {/* 隐波绝对值变化 */}
        {config.showFields.ivChangeAbs && (
          <div className="option-field">
            <span className="field-label">隐波变化:</span>
            <span className={`field-value ${getChangeColor(ivChangeAbs)}`}>
              {formatNumber(ivChangeAbs, 4)}
            </span>
          </div>
        )}

        {/* 持仓密集度（新增） */}
        {config.showFields.concentration && (
          <div className="option-field">
            <span className="field-label">持仓密集度:</span>
            <span className={`field-value ${getConcentrationColor(concentration)}`}>
              {formatNumber(concentration, 3)}
              {concentration > 1.5 && (
                <i className="fas fa-exclamation-triangle ms-2 text-warning" title="高密集度"></i>
              )}
            </span>
          </div>
        )}

        {/* 希腊字母 */}
        {config.showFields.greeks && (
          <div className="greeks-section mt-2 pt-2 border-top">
            <div className="row g-2">
              <div className="col-3">
                <small className="text-muted d-block">Delta</small>
                <span className="fw-bold">{formatNumber(greeks.delta, 4)}</span>
              </div>
              <div className="col-3">
                <small className="text-muted d-block">Gamma</small>
                <span className="fw-bold">{formatNumber(greeks.gamma, 4)}</span>
              </div>
              <div className="col-3">
                <small className="text-muted d-block">Theta</small>
                <span className="fw-bold">{formatNumber(greeks.theta, 4)}</span>
              </div>
              <div className="col-3">
                <small className="text-muted d-block">Vega</small>
                <span className="fw-bold">{formatNumber(greeks.vega, 4)}</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default OptionRow;