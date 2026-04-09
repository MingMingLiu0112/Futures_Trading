import React from 'react';
import { MarketStatsProps } from '../types';

const MarketStats: React.FC<MarketStatsProps> = ({ stats }) => {
  const {
    underlyingPrice,
    atmStrike,
    totalVolume,
    totalOI,
    putCallRatio,
    ivSkew,
    maxPain,
    updateTime
  } = stats;

  const formatNumber = (value: number, decimals: number = 2): string => {
    if (value === undefined || value === null) return '--';
    return value.toLocaleString('zh-CN', {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals
    });
  };

  const formatRatio = (value: number): string => {
    if (value === undefined || value === null) return '--';
    return value.toFixed(3);
  };

  const getPCRColor = (pcr: number): string => {
    if (pcr > 1.2) return 'text-danger'; // 看跌情绪浓厚
    if (pcr > 0.8) return 'text-warning'; // 中性偏看跌
    if (pcr > 0.5) return 'text-success'; // 中性偏看涨
    return 'text-primary'; // 看涨情绪浓厚
  };

  const getSkewColor = (skew: number): string => {
    if (skew > 0.1) return 'text-danger'; // 看跌波动率溢价
    if (skew > -0.1) return 'text-warning'; // 基本对称
    return 'text-success'; // 看涨波动率溢价
  };

  return (
    <div className="row g-3">
      <div className="col-md-3 col-6">
        <div className="stats-card text-center">
          <div className="stat-label">标的物价格</div>
          <div className="stat-value text-primary">{formatNumber(underlyingPrice)}</div>
          <div className="text-muted small">PTA主力合约</div>
        </div>
      </div>

      <div className="col-md-3 col-6">
        <div className="stats-card text-center">
          <div className="stat-label">平值行权价</div>
          <div className="stat-value text-success">{formatNumber(atmStrike, 0)}</div>
          <div className="text-muted small">ATM Strike</div>
        </div>
      </div>

      <div className="col-md-3 col-6">
        <div className="stats-card text-center">
          <div className="stat-label">总成交量</div>
          <div className="stat-value">{formatNumber(totalVolume, 0)}</div>
          <div className="text-muted small">手</div>
        </div>
      </div>

      <div className="col-md-3 col-6">
        <div className="stats-card text-center">
          <div className="stat-label">总持仓量</div>
          <div className="stat-value">{formatNumber(totalOI, 0)}</div>
          <div className="text-muted small">手</div>
        </div>
      </div>

      <div className="col-md-4 col-6">
        <div className="stats-card text-center">
          <div className="stat-label">Put/Call比率</div>
          <div className={`stat-value ${getPCRColor(putCallRatio)}`}>
            {formatRatio(putCallRatio)}
          </div>
          <div className="text-muted small">
            {putCallRatio > 1 ? '看跌情绪' : '看涨情绪'}
          </div>
        </div>
      </div>

      <div className="col-md-4 col-6">
        <div className="stats-card text-center">
          <div className="stat-label">IV偏斜</div>
          <div className={`stat-value ${getSkewColor(ivSkew)}`}>
            {formatNumber(ivSkew, 3)}
          </div>
          <div className="text-muted small">
            {ivSkew > 0 ? 'Put IV溢价' : 'Call IV溢价'}
          </div>
        </div>
      </div>

      <div className="col-md-4 col-6">
        <div className="stats-card text-center">
          <div className="stat-label">最大痛点</div>
          <div className="stat-value text-info">{formatNumber(maxPain, 0)}</div>
          <div className="text-muted small">行权价</div>
        </div>
      </div>

      <div className="col-12">
        <div className="text-center text-muted small">
          <i className="fas fa-clock me-1"></i>
          数据更新时间: {updateTime}
        </div>
      </div>
    </div>
  );
};

export default MarketStats;