-- PTA Analysis 数据库初始化脚本
-- 运行: mysql -u root -p pta_analysis < schema.sql

USE pta_analysis;

-- 信号日志表
CREATE TABLE IF NOT EXISTS signal_log (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    symbol      VARCHAR(20) NOT NULL COMMENT '合约代码',
    last_price  DECIMAL(10,2) COMMENT '最新价',
    bid         DECIMAL(10,2) COMMENT '买一价',
    ask         DECIMAL(10,2) COMMENT '卖一价',
    volume      BIGINT COMMENT '成交量',
    open_interest BIGINT COMMENT '持仓量',
    pcr         DECIMAL(10,4) COMMENT '成交量PCR',
    oi_pcr      DECIMAL(10,4) COMMENT '持仓量PCR',
    iv          DECIMAL(10,4) COMMENT '隐含波动率',
    cost_low    DECIMAL(10,2) COMMENT '成本下限',
    cost_high   DECIMAL(10,2) COMMENT '成本上限',
    brent_usd   DECIMAL(10,2) COMMENT '布伦特原油(USD)',
    px_cny      DECIMAL(10,2) COMMENT 'PX现货(CNY)',
    pta_spot    DECIMAL(10,2) COMMENT 'PTA现货价',
    macro_score INT COMMENT '宏观得分',
    tech_score  INT COMMENT '技术得分',
    option_score INT COMMENT '期权得分',
    signal      VARCHAR(20) COMMENT '信号: 做多/做空/观望',
    INDEX idx_symbol (symbol),
    INDEX idx_created (created_at),
    INDEX idx_signal (signal)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='信号日志';

-- K线数据表
CREATE TABLE IF NOT EXISTS kline_data (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol      VARCHAR(20) NOT NULL COMMENT '合约',
    timeframe   VARCHAR(10) NOT NULL COMMENT '周期: 1m/5m/30m/1d',
    open_time   DATETIME NOT NULL,
    open_price  DECIMAL(10,2),
    high_price  DECIMAL(10,2),
    low_price   DECIMAL(10,2),
    close_price DECIMAL(10,2),
    volume      BIGINT,
    turnover    DECIMAL(20,2),
    UNIQUE KEY uk_symbol_timeframe_opentime (symbol, timeframe, open_time),
    INDEX idx_symbol (symbol),
    INDEX idx_timeframe (timeframe)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='K线数据';

-- 持仓分析表
CREATE TABLE IF NOT EXISTS position_analysis (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol          VARCHAR(20) NOT NULL,
    expiry          VARCHAR(20) NOT NULL COMMENT '到期日',
    strike          DECIMAL(10,2) COMMENT '行权价',
    option_type     VARCHAR(10) COMMENT 'C/P',
    open_interest   BIGINT COMMENT '持仓量',
    volume          BIGINT COMMENT '成交量',
    iv              DECIMAL(10,4) COMMENT '隐波',
    delta           DECIMAL(10,4) COMMENT 'Delta',
    gamma           DECIMAL(10,6) COMMENT 'Gamma',
    theta           DECIMAL(10,4) COMMENT 'Theta',
    vega            DECIMAL(10,4) COMMENT 'Vega',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_symbol_expiry (symbol, expiry),
    INDEX idx_open_interest (open_interest DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='持仓分析';

-- 新闻日志表
CREATE TABLE IF NOT EXISTS macro_news_log (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    title       VARCHAR(500) NOT NULL,
    content     TEXT,
    source      VARCHAR(100),
    url         VARCHAR(500),
    published_at DATETIME,
    sentiment   VARCHAR(20) COMMENT 'positive/negative/neutral',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FULLTEXT INDEX ft_title (title)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='宏观新闻';
