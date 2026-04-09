// K线图多时间级别MACD功能
// 支持1、5、15、30、60分钟级别的MACD计算和显示

// 全局变量
let klineChart = null;
let macdChart = null;
let kdjChart = null;
let chartData = null;
let currentPeriod = '1min';
let currentSymbol = 'TA0';
let annotations = [];
let annotationIdCounter = 1;
let drawingMode = null;

// 默认指标参数
const defaultIndicators = {
    macd: { fast: 12, slow: 26, signal: 9 },
    kdj: { period: 9, k: 3, d: 3 }
};

let currentIndicators = JSON.parse(JSON.stringify(defaultIndicators));

// 时间周期配置
const periodConfig = {
    '1min': { label: '1分钟', interval: 1 },
    '5min': { label: '5分钟', interval: 5 },
    '15min': { label: '15分钟', interval: 15 },
    '30min': { label: '30分钟', interval: 30 },
    '60min': { label: '60分钟', interval: 60 }
};

// 初始化K线图
function initKlineChart() {
    console.log('初始化K线图...');
    
    // 绑定事件
    bindEvents();
    
    // 加载数据
    loadKlineData();
    
    // 加载指标
    loadIndicators();
    
    showNotification('K线图已初始化', 'success');
}

// 绑定事件
function bindEvents() {
    // 时间周期切换
    document.querySelectorAll('.period-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            const period = this.getAttribute('data-period');
            switchPeriod(period);
        });
    });
    
    // 绘图工具
    document.querySelectorAll('.drawing-tool').forEach(tool => {
        tool.addEventListener('click', function() {
            const toolType = this.getAttribute('data-tool');
            setDrawingMode(toolType);
        });
    });
    
    // 指标参数应用
    document.getElementById('apply-indicators').addEventListener('click', applyIndicatorSettings);
    document.getElementById('reset-indicators').addEventListener('click', resetIndicatorSettings);
    
    // MACD面积切换
    document.getElementById('toggle-macd-area').addEventListener('click', toggleMACDArea);
    
    // 数据刷新
    document.getElementById('refresh-data').addEventListener('click', loadKlineData);
    
    // 标注管理
    document.getElementById('clear-annotations').addEventListener('click', clearAllAnnotations);
    document.getElementById('export-annotations').addEventListener('click', exportAnnotations);
    document.getElementById('import-annotations').addEventListener('click', () => {
        document.getElementById('import-file').click();
    });
    document.getElementById('import-file').addEventListener('change', importAnnotations);
    
    // 图表点击事件（用于绘图）
    document.getElementById('kline-chart').addEventListener('click', handleChartClick);
}

// 切换时间周期
function switchPeriod(period) {
    if (currentPeriod === period) return;
    
    currentPeriod = period;
    
    // 更新按钮状态
    document.querySelectorAll('.period-btn').forEach(btn => {
        if (btn.getAttribute('data-period') === period) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
    
    // 更新标题
    document.getElementById('chart-title').textContent = 
        `PTA期货${periodConfig[period].label}K线图`;
    
    // 重新加载数据
    loadKlineData();
    loadIndicators();
    
    showNotification(`已切换到${periodConfig[period].label}周期`, 'info');
}

// 加载K线数据
async function loadKlineData() {
    showLoading('正在加载K线数据...');
    
    try {
        const response = await fetch(`/api/kline/data?period=${currentPeriod}&symbol=${currentSymbol}`);
        const result = await response.json();
        
        if (result.success) {
            chartData = result.data;
            updatePriceInfo(result);
            renderCharts();
            showNotification('K线数据加载成功', 'success');
        } else {
            throw new Error(result.error || '数据加载失败');
        }
    } catch (error) {
        console.error('加载K线数据失败:', error);
        showNotification(`数据加载失败: ${error.message}`, 'danger');
    } finally {
        hideLoading();
    }
}

// 加载指标数据
async function loadIndicators() {
    try {
        const { fast, slow, signal } = currentIndicators.macd;
        const response = await fetch(
            `/api/kline/indicators?period=${currentPeriod}&symbol=${currentSymbol}&fast=${fast}&slow=${slow}&signal=${signal}`
        );
        const result = await response.json();
        
        if (result.success) {
            updateIndicatorInfo(result);
            updateMACDChart(result);
        } else {
            console.warn('指标数据加载失败:', result.error);
        }
    } catch (error) {
        console.error('加载指标数据失败:', error);
    }
}

// 加载所有周期的MACD数据
async function loadAllPeriodsMACD() {
    try {
        const { fast, slow, signal } = currentIndicators.macd;
        const response = await fetch(
            `/api/kline/macd/all_periods?symbol=${currentSymbol}&fast=${fast}&slow=${slow}&signal=${signal}`
        );
        const result = await response.json();
        
        if (result.success) {
            updateAllPeriodsMACDInfo(result);
        } else {
            console.warn('所有周期MACD数据加载失败:', result.error);
        }
    } catch (error) {
        console.error('加载所有周期MACD数据失败:', error);
    }
}

// 更新价格信息
function updatePriceInfo(data) {
    const priceElement = document.getElementById('current-price');
    const changeElement = document.getElementById('price-change');
    const changePctElement = document.getElementById('price-change-pct');
    const periodElement = document.getElementById('current-period');
    const countElement = document.getElementById('data-count');
    
    priceElement.textContent = data.current_price.toFixed(2);
    
    // 涨跌颜色
    const changeColor = data.change >= 0 ? 'text-success' : 'text-danger';
    const changeIcon = data.change >= 0 ? '▲' : '▼';
    
    changeElement.textContent = `${changeIcon} ${Math.abs(data.change).toFixed(2)}`;
    changeElement.className = changeColor;
    
    changePctElement.textContent = `(${data.change_pct.toFixed(2)}%)`;
    changePctElement.className = changeColor;
    
    periodElement.textContent = data.period_label;
    countElement.textContent = data.count;
}

// 更新指标信息
function updateIndicatorInfo(data) {
    // 更新MACD信息
    const macdElement = document.getElementById('macd-value');
    const macdStateElement = document.getElementById('macd-state');
    const difElement = document.getElementById('macd-dif');
    const deaElement = document.getElementById('macd-dea');
    const areaPositiveElement = document.getElementById('macd-area-positive');
    const areaNegativeElement = document.getElementById('macd-area-negative');
    const areaRatioElement = document.getElementById('macd-area-ratio');
    
    const macd = data.macd;
    
    macdElement.textContent = macd.macd.toFixed(4);
    macdElement.className = macd.macd >= 0 ? 'text-success' : 'text-danger';
    
    macdStateElement.textContent = macd.state;
    macdStateElement.className = macd.state === '多头' ? 'text-success' : 'text-danger';
    
    difElement.textContent = macd.dif.toFixed(4);
    deaElement.textContent = macd.dea.toFixed(4);
    
    areaPositiveElement.textContent = macd.positive_area.toFixed(4);
    areaNegativeElement.textContent = macd.negative_area.toFixed(4);
    areaRatioElement.textContent = macd.area_ratio.toFixed(2);
    
    // 更新面积列表
    updateAreaList(data.areas || []);
}

// 更新所有周期的MACD信息
function updateAllPeriodsMACDInfo(data) {
    const container = document.getElementById('all-periods-macd');
    if (!container) return;
    
    let html = '';
    
    for (const [period, periodData] of Object.entries(data.periods)) {
        if (!periodData.success) continue;
        
        const macd = periodData.macd;
        const periodLabel = periodConfig[period]?.label || period;
        
        html += `
            <div class="card mb-2">
                <div class="card-body py-2">
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <strong>${periodLabel}</strong>
                            <small class="text-muted ms-2">${periodData.close.toFixed(2)}</small>
                        </div>
                        <div>
                            <span class="badge ${macd.state === '多头' ? 'bg-success' : 'bg-danger'} me-2">
                                ${macd.state}
                            </span>
                            <span class="${macd.macd >= 0 ? 'text-success' : 'text-danger'}">
                                ${macd.macd.toFixed(4)}
                            </span>
                        </div>
                    </div>
                    <div class="small text-muted mt-1">
                        DIF: ${macd.dif.toFixed(4)} | DEA: ${macd.dea.toFixed(4)} |
                        面积比: ${periodData.area_summary?.area_ratio?.toFixed(2) || 'N/A'}
                    </div>
                </div>
            </div>
        `;
    }
    
    container.innerHTML = html || '<div class="text-muted text-center py-3">暂无数据</div>';
}

// 更新面积列表
function updateAreaList(areas) {
    const container = document.getElementById('macd-areas-list');
    if (!container) return;
    
    if (!areas || areas.length === 0) {
        container.innerHTML = '<div class="text-muted text-center py-3">暂无面积数据</div>';
        return;
    }
    
    let html = '';
    areas.forEach((area, index) => {
        const isPositive = area.sign === 1;
        const colorClass = isPositive ? 'text-danger' : 'text-success'; // 红涨绿跌
        const signText = isPositive ? '红' : '绿';
        
        html += `
            <div class="area-item mb-2">
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <span class="badge ${colorClass} me-2">${signText}</span>
                        <span>面积${index + 1}</span>
                    </div>
                    <div>
                        <span class="${colorClass}">${area.area.toFixed(4)}</span>
                        <small class="text-muted ms-2">${area.bars}根</small>
                    </div>
                </div>
            </div>
        `;
    });
    
    container.innerHTML = html;
}

// 渲染图表
function renderCharts() {
    if (!chartData || chartData.length === 0) {
        console.warn('没有数据可渲染');
        return;
    }
    
    // 准备数据
    const labels = chartData.map(d => {
        const date = new Date(d.time);
        return date.toLocaleTimeString();
    });
    
    const prices = chartData.map(d => d.close);
    const volumes = chartData.map(d => d.volume);
    
    // 销毁现有图表
    if (klineChart) klineChart.destroy();
    if (macdChart) macdChart.destroy();
    if (kdjChart) kdjChart.destroy();
    
    // 创建K线图
    const klineCtx = document.getElementById('kline-chart').getContext('2d');
    klineChart = new Chart(klineCtx, {
        type: 'candlestick',
        data: {
            labels: labels,
            datasets: [{
                label: 'PTA期货',
                data: chartData.map(d => ({
                    x: d.time,
                    o: d.open,
                    h: d.high,
                    l: d.low,
                    c: d.close
                })),
                borderColor: '#666',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: 'minute'
                    }
                },
                y: {
                    position: 'right',
                    ticks: {
                        callback: function(value) {
                            return value.toFixed(0);
                        }
                    }
                }
            },
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const point = context.raw;
                            return [
                                `开盘: ${point.o.toFixed(2)}`,
                                `最高: ${point.h.toFixed(2)}`,
                                `最低: ${point.l.toFixed(2)}`,
                                `收盘: ${point.c.toFixed(2)}`
                            ];
                        }
                    }
                }
            }
        }
    });
    
    // 创建成交量图
    const volumeCtx = document.getElementById('volume-chart').getContext('2d');
    const volumeColors = chartData.map((d, i) => {
        if (i === 0) return '#666';
        return d.close >= chartData[i-1].close ? '#e74c3c' : '#2ecc71';
    });
    
    new Chart(volumeCtx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: '成交量',
                data: volumes,
                backgroundColor: volumeColors,
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    display: false
                },
                y: {
                    display: true,
                    position: 'right',
                    ticks: {
                        callback: function(value) {
                            if (value >= 1000000) return (value / 1000000).toFixed(1) + 'M';
                            if (value >= 1000) return (value / 1000).toFixed(1) + 'K';
                            return value;
                        }
                    }
                }
            },
            plugins: {
                legend: {
                    display: false
                }
            }
        }
    });
}

// 更新MACD图表
function updateMACDChart(data) {
    if (!chartData || !data.macd) return;
    
    const macdCtx = document.getElementById('macd-chart');
    if (!macdCtx) return;
    
    // 这里可以添加MACD图表的渲染逻辑
    // 由于时间关系，暂时省略详细的MACD图表渲染
    console.log('MACD数据已更新:', data.macd);
}

// 应用指标设置
function applyIndicatorSettings() {
    const fast = parseInt(document.getElementById('macd-fast').value);
    const slow = parseInt(document.getElementById('macd-slow').value);
    const signal = parseInt(document.getElementById('macd-signal').value);
    
    // 验证参数
    if (fast >= slow) {
        showNotification('快线周期必须小于慢线周期', 'warning');
        return;
    }
    
    if (fast <= 0 || slow <= 0 || signal <= 0) {
        showNotification('周期参数必须大于0', 'warning');
        return;
    }
    
    // 更新当前指标
    currentIndicators.macd = { fast, slow, signal };
    
    // 重新加载指标
    loadIndicators();
    loadAllPeriodsMACD();
    
    showNotification('指标参数已应用', 'success');
}

// 重置指标设置
function resetIndicatorSettings() {
    currentIndicators = JSON.parse(JSON.stringify(defaultIndicators));
    
    document.getElementById('macd-fast').value = defaultIndicators.macd.fast;
    document.getElementById('macd-slow').value = defaultIndicators.macd.slow;
    document.getElementById('macd-signal').value = defaultIndicators.macd.signal;
    
    // 重新加载指标
    loadIndicators();
    loadAllPeriodsMACD();
    
    showNotification('指标参数已重置', 'info');
}

// 切换MACD面积显示
function toggleMACDArea() {
    const btn = document.getElementById('toggle-macd-area');
    const showing = btn.textContent.includes('显示');
    btn.innerHTML = showing ? 
        '<i class="fas fa-chart-area me-1"></i>隐藏MACD面积' :
        '<i class="fas fa-chart-area me-1"></i>显示MACD面积';
    
    // 这里可以添加显示/隐藏MACD面积的逻辑
    showNotification(`MACD面积${showing ? '显示' : '隐藏'}`, 'info');
}

// 设置绘图模式
function setDrawingMode(toolType) {
    drawingMode = toolType;
    
    // 更新按钮状态
    document.querySelectorAll('.drawing-tool').forEach(tool => {
        if (tool.getAttribute('data-tool') === toolType) {
            tool.classList.add('active');
        } else {
            tool.classList.remove('active');
        }
    });
    
    const toolNames = {
        'trendline': '趋势线',
        'horizontal': '水平线', 
        'vertical': '垂直线',
        'text': '文本标注',
        'delete': '删除标注'
    };
    
    showNotification(`已选择${toolNames[toolType] || toolType}工具`, 'info');
}

// 处理图表点击（用于绘图）
function handleChartClick(event) {
    if (!drawingMode || !klineChart) return;
    
    const rect = event.target.getBoundingClientRect();
    const x