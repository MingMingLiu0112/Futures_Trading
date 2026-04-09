// 隐含波动率曲线组件
class IVCurve {
    constructor() {
        this.chart = null;
        this.animationInterval = null;
        this.animationFrame = 0;
        this.maxAnimationFrames = 30;
        this.isAnimating = false;
        this.currentData = null;
        this.previousData = null;
        this.realTimeData = null;
        
        this.init();
    }

    init() {
        // 初始化Chart.js
        this.initChart();
        
        // 绑定事件
        this.bindEvents();
        
        // 加载初始数据
        this.loadInitialData();
        
        // 更新UI
        this.updateUI();
    }

    initChart() {
        const ctx = document.getElementById('ivChart').getContext('2d');
        
        this.chart = new Chart(ctx, {
            type: 'line',
            data: {
                datasets: []
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false,
                },
                plugins: {
                    legend: {
                        position: 'top',
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return `${context.dataset.label}: ${context.parsed.y.toFixed(2)}%`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        type: 'linear',
                        position: 'bottom',
                        title: {
                            display: true,
                            text: '行权价 / 标的价格 (%)',
                            font: {
                                size: 14,
                                weight: 'bold'
                            }
                        },
                        grid: {
                            color: 'rgba(0, 0, 0, 0.1)'
                        }
                    },
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: '隐含波动率 (%)',
                            font: {
                                size: 14,
                                weight: 'bold'
                            }
                        },
                        grid: {
                            color: 'rgba(0, 0, 0, 0.1)'
                        }
                    }
                },
                animation: {
                    duration: 1000,
                    easing: 'easeInOutQuart'
                }
            }
        });
    }

    bindEvents() {
        // 绑定滑块事件
        document.getElementById('timeRange').addEventListener('input', (e) => {
            document.getElementById('timeRangeValue').textContent = `${e.target.value}天`;
        });

        document.getElementById('strikeRange').addEventListener('input', (e) => {
            document.getElementById('strikeRangeValue').textContent = `${e.target.value}%`;
        });

        // 绑定复选框事件
        document.getElementById('showPreviousDay').addEventListener('change', () => this.updateChart());
        document.getElementById('showRealTime').addEventListener('change', () => this.updateChart());
        document.getElementById('showSmile').addEventListener('change', () => this.updateChart());
        document.getElementById('showMovement').addEventListener('change', () => this.updateChart());

        // 绑定动画速度控制
        document.getElementById('animationSpeed').addEventListener('input', (e) => {
            if (this.isAnimating) {
                this.stopAnimation();
                this.startAnimation();
            }
        });
    }

    async loadInitialData() {
        this.showStatus('正在加载初始数据...');
        
        try {
            // 尝试从API获取数据
            const symbol = document.getElementById('symbolSelect').value;
            const expiry = document.getElementById('expirySelect').value;
            
            // 同时获取前日和实时数据
            const [previousResponse, realtimeResponse] = await Promise.all([
                this.fetchIVData('previous', symbol, expiry),
                this.fetchIVData('current', symbol, expiry)
            ]);
            
            if (previousResponse && realtimeResponse) {
                this.previousData = this.processAPIData(previousResponse, 'previous');
                this.realTimeData = this.processAPIData(realtimeResponse, 'realtime');
                this.currentData = this.realTimeData;
                this.showStatus('API数据加载完成', 'success');
            } else {
                // API失败时使用模拟数据
                this.previousData = this.generateMockData('previous');
                this.realTimeData = this.generateMockData('realtime');
                this.currentData = this.realTimeData;
                this.showStatus('使用模拟数据', 'warning');
            }
            
            // 更新图表
            this.updateChart();
            
        } catch (error) {
            console.error('加载数据失败:', error);
            // 使用模拟数据作为后备
            this.previousData = this.generateMockData('previous');
            this.realTimeData = this.generateMockData('realtime');
            this.currentData = this.realTimeData;
            this.updateChart();
            this.showStatus('使用模拟数据', 'warning');
        }
    }
    
    async fetchIVData(type, symbol, expiry) {
        const endpoint = type === 'previous' ? 'previous' : 'current';
        const apiUrl = `http://localhost:5000/api/iv/${endpoint}?symbol=${symbol}&expiry=${expiry}`;
        
        try {
            const response = await fetch(apiUrl);
            if (!response.ok) {
                throw new Error(`API响应错误: ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.warn(`无法从API获取${type}数据:`, error);
            return null;
        }
    }
    
    processAPIData(apiData, type) {
        return {
            strikePrices: apiData.strike_prices || [],
            ivValues: apiData.iv_values || [],
            timestamp: apiData.timestamp || (type === 'previous' ? '前日收盘' : '实时数据'),
            atmIV: apiData.atm_iv || 0,
            skew: apiData.skew || 0,
            kurtosis: apiData.kurtosis || 0,
            symbol: apiData.symbol || 'TA',
            expiry: apiData.expiry || 'current'
        };
    }

    generateMockData(type = 'realtime') {
        const strikePrices = [];
        const ivValues = [];
        
        // 生成行权价范围 (80% - 120%)
        for (let i = 80; i <= 120; i += 2) {
            strikePrices.push(i);
            
            // 生成微笑曲线形状的IV值
            let baseIV;
            if (type === 'previous') {
                baseIV = 25 + Math.random() * 5; // 前日收盘IV较高
            } else {
                baseIV = 20 + Math.random() * 8; // 实时IV较低
            }
            
            // 微笑曲线效果：虚值期权IV更高
            const distanceFromATM = Math.abs(i - 100);
            const smileEffect = distanceFromATM * 0.15;
            
            // 添加随机噪声
            const noise = (Math.random() - 0.5) * 2;
            
            const iv = baseIV + smileEffect + noise;
            ivValues.push(Math.max(15, Math.min(50, iv)));
        }
        
        return {
            strikePrices,
            ivValues,
            timestamp: type === 'previous' ? '2024-04-07 15:00' : new Date().toLocaleString('zh-CN'),
            atmIV: ivValues[10], // ATM IV (100%行权价)
            skew: this.calculateSkew(ivValues),
            kurtosis: this.calculateKurtosis(ivValues)
        };
    }

    calculateSkew(ivValues) {
        // 计算IV偏度（微笑曲线不对称性）
        const atmIndex = 10; // 100%行权价
        const leftAvg = ivValues.slice(0, atmIndex).reduce((a, b) => a + b, 0) / atmIndex;
        const rightAvg = ivValues.slice(atmIndex + 1).reduce((a, b) => a + b, 0) / (ivValues.length - atmIndex - 1);
        return (rightAvg - leftAvg).toFixed(2);
    }

    calculateKurtosis(ivValues) {
        // 计算IV峰度（微笑曲线陡峭程度）
        const mean = ivValues.reduce((a, b) => a + b, 0) / ivValues.length;
        const variance = ivValues.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / ivValues.length;
        const std = Math.sqrt(variance);
        
        const fourthMoment = ivValues.reduce((a, b) => a + Math.pow((b - mean) / std, 4), 0) / ivValues.length;
        return (fourthMoment - 3).toFixed(2); // 超额峰度
    }

    updateChart() {
        if (!this.chart) return;
        
        const datasets = [];
        const showPreviousDay = document.getElementById('showPreviousDay').checked;
        const showRealTime = document.getElementById('showRealTime').checked;
        const showSmile = document.getElementById('showSmile').checked;
        const showMovement = document.getElementById('showMovement').checked;
        
        // 添加前日收盘曲线
        if (showPreviousDay && this.previousData) {
            datasets.push({
                label: `前日收盘 (${this.previousData.timestamp})`,
                data: this.previousData.strikePrices.map((x, i) => ({x, y: this.previousData.ivValues[i]})),
                borderColor: 'rgba(255, 99, 132, 0.8)',
                backgroundColor: 'rgba(255, 99, 132, 0.1)',
                borderWidth: 3,
                fill: false,
                tension: 0.4,
                pointRadius: 0
            });
        }
        
        // 添加实时曲线
        if (showRealTime && this.realTimeData) {
            datasets.push({
                label: `实时数据 (${this.realTimeData.timestamp})`,
                data: this.realTimeData.strikePrices.map((x, i) => ({x, y: this.realTimeData.ivValues[i]})),
                borderColor: 'rgba(54, 162, 235, 0.8)',
                backgroundColor: 'rgba(54, 162, 235, 0.1)',
                borderWidth: 3,
                fill: false,
                tension: 0.4,
                pointRadius: 0
            });
        }
        
        // 添加微笑曲线拟合
        if (showSmile && this.currentData) {
            const smileData = this.fitSmileCurve(this.currentData.strikePrices, this.currentData.ivValues);
            datasets.push({
                label: '微笑曲线拟合',
                data: smileData,
                borderColor: 'rgba(75, 192, 192, 0.6)',
                borderWidth: 2,
                borderDash: [5, 5],
                fill: false,
                tension: 0.3,
                pointRadius: 0
            });
        }
        
        // 添加曲线移动指示器
        if (showMovement && showPreviousDay && showRealTime && this.previousData && this.realTimeData) {
            this.addMovementIndicators(datasets);
        }
        
        this.chart.data.datasets = datasets;
        this.chart.update();
        
        // 更新图例
        this.updateLegend();
        
        // 更新分析结果
        this.updateAnalysisResults();
    }

    fitSmileCurve(strikePrices, ivValues) {
        // 二次多项式拟合微笑曲线
        const n = strikePrices.length;
        let sumX = 0, sumX2 = 0, sumX3 = 0, sumX4 = 0;
        let sumY = 0, sumXY = 0, sumX2Y = 0;
        
        for (let i = 0; i < n; i++) {
            const x = strikePrices[i] - 100; // 中心化
            const y = ivValues[i];
            
            sumX += x;
            sumX2 += x * x;
            sumX3 += x * x * x;
            sumX4 += x * x * x * x;
            sumY += y;
            sumXY += x * y;
            sumX2Y += x * x * y;
        }
        
        // 解正规方程
        const Sxx = sumX2 - sumX * sumX / n;
        const Sxy = sumXY - sumX * sumY / n;
        const Sxx2 = sumX3 - sumX * sumX2 / n;
        const Sx2y = sumX2Y - sumX2 * sumY / n;
        const Sx2x2 = sumX4 - sumX2 * sumX2 / n;
        
        const denom = Sxx * Sx2x2 - Sxx2 * Sxx2;
        const a = (Sxy * Sx2x2 - Sx2y * Sxx2) / denom;
        const b = (Sx2y * Sxx - Sxy * Sxx2) / denom;
        const c = (sumY - a * sumX - b * sumX2) / n;
        
        // 生成拟合曲线数据
        return strikePrices.map(x => {
            const xCentered = x - 100;
            const y = a * xCentered + b * xCentered * xCentered + c;
            return {x, y};
        });
    }

    addMovementIndicators(datasets) {
        const arrowPoints = [];
        const sampleIndices = [5, 10, 15]; // 采样几个点显示箭头
        
        sampleIndices.forEach(idx => {
            const x = this.previousData.strikePrices[idx];
            const y1 = this.previousData.ivValues[idx];
            const y2 = this.realTimeData.ivValues[idx];
            
            if (Math.abs(y2 - y1) > 0.5) { // 只显示显著变化
                arrowPoints.push({
                    x, y1, y2,
                    color: y2 > y1 ? 'rgba(255, 0, 0, 0.6)' : 'rgba(0, 128, 0, 0.6)'
                });
            }
        });
        
        // 添加箭头数据集
        arrowPoints.forEach((point, i) => {
            datasets.push({
                label: `移动指示器${i + 1}`,
                data: [
                    {x: point.x, y: point.y1},
                    {x: point.x, y: point.y2}
                ],
                borderColor: point.color,
                borderWidth: 2,
                borderDash: [2, 2],
                fill: false,
                pointRadius: 4,
                pointBackgroundColor: point.color,
                showLine: true
            });
        });
    }

    updateLegend() {
        const legendContainer = document.getElementById('chartLegend');
        legendContainer.innerHTML = '';
        
        this.chart.data.datasets.forEach(dataset => {
            if (!dataset.label.includes('移动指示器')) {
                const legendItem = document.createElement('div');
                legendItem.className = 'legend-item';
                
                const colorBox = document.createElement('div');
                colorBox.className = 'legend-color';
                colorBox.style.backgroundColor = dataset.borderColor;
                
                const label = document.createElement('span');
                label.textContent = dataset.label;
                label.style.color = '#666';
                label.style.fontSize = '14px';
                
                legendItem.appendChild(colorBox);
                legendItem.appendChild(label);
                legendContainer.appendChild(legendItem);
            }
        });
    }

    updateAnalysisResults() {
        if (!this.previousData || !this.realTimeData) return;
        
        const container = document.getElementById('analysisResults');
        
        // 计算各种分析指标
        const verticalShift = this.calculateVerticalShift();
        const horizontalShift = this.calculateHorizontalShift();
        const twistAnalysis = this.calculateTwistAnalysis();
        const skewChange = this.calculateSkewChange();
        const atmIVChange = this.calculateATMIVChange();
        
        container.innerHTML = `
            <div class="analysis-card">
                <h4>📏 垂直移动</h4>
                <div class="value">${verticalShift.value}%</div>
                <p>${verticalShift.description}</p>
            </div>
            
            <div class="analysis-card">
                <h4>↔️ 水平移动</h4>
                <div class="value">${horizontalShift.value}%</div>
                <p>${horizontalShift.description}</p>
            </div>
            
            <div class="analysis-card">
                <h4>🌀 扭曲分析</h4>
                <div class="value">${twistAnalysis.value}</div>
                <p>${twistAnalysis.description}</p>
            </div>
            
            <div class="analysis-card">
                <h4>😊 微笑变化</h4>
                <div class="value">${skewChange.value}</div>
                <p>${skewChange.description}</p>
            </div>
            
            <div class="analysis-card">
                <h4>🎯 ATM IV变化</h4>
                <div class="value">${atmIVChange.value}%</div>
                <p>${atmIVChange.description}</p>
            </div>
            
            <div class="analysis-card">
                <h4>📈 市场情绪</h4>
                <div class="value">${this.getMarketSentiment()}</div>
                <p>${this.getMarketSentimentDescription()}</p>
            </div>
        `;
    }

    calculateVerticalShift() {
        // 计算整体IV水平的变化
        const prevAvg = this.previousData.ivValues.reduce((a, b) => a + b, 0) / this.previousData.ivValues.length;
        const currAvg = this.realTimeData.ivValues.reduce((a, b) => a + b, 0) / this.realTimeData.ivValues.length;
        const shift = currAvg - prevAvg;
        
        return {
            value: shift.toFixed(2),
            description: shift > 0 ? '整体IV上升，市场波动预期增强' : '整体IV下降，市场趋于平静'
        };
    }

    calculateHorizontalShift() {
        // 计算微笑曲线中心的水平移动
        const prevMinIndex = this.previousData.ivValues.indexOf(Math.min(...this.previousData.ivValues));
        const currMinIndex = this.realTimeData.ivValues.indexOf(Math.min(...this.realTimeData.ivValues));
        const shift = this.realTimeData.strikePrices[currMinIndex] - this.previousData.strikePrices[prevMinIndex];
        
        return {
            value: shift.toFixed(1),
            description: shift > 0 ? '微笑中心右移，市场预期上涨' : '微笑中心左移，市场预期下跌'
        };
    }

    calculateTwistAnalysis() {
        // 计算曲线扭曲程度（两端变化不一致）
        const leftChange = this.realTimeData.ivValues[0] - this.previousData.ivValues[0];
        const rightChange = this.realTimeData.ivValues[this.realTimeData.ivValues.length - 1] - 
                          this.previousData.ivValues[this.previousData.ivValues.length - 1];
        const twist = Math.abs(leftChange - rightChange);
        
        let description;
        if (twist < 1) {
            description = '曲线平行移动，无显著扭曲';
        } else if (leftChange > rightChange) {
            description = '左端上升更多，虚值看跌期权需求增加';
        } else {
            description = '右端上升更多，虚值看涨期权需求增加';
        }
        
        return {
            value: twist.toFixed(2),
            description: description
        };
    }

    calculateSkewChange() {
        const prevSkew = parseFloat(this.previousData.skew);
        const currSkew = parseFloat(this.realTimeData.skew);
        const change = currSkew - prevSkew;
        
        return {
            value: change.toFixed(2),
            description: change > 0 ? '微笑曲线更陡峭，波动预期增强' : '微笑曲线更平坦，波动预期减弱'
        };
    }

    calculateATMIVChange() {
        const change = this.realTimeData.atmIV - this.previousData.atmIV;
        
        return {
            value: change.toFixed(2),
            description: change > 0 ? '平值期权IV上升，短期波动预期增强' : '平值期权IV下降，短期波动预期减弱'
        };
    }

    getMarketSentiment() {
        const verticalShift = parseFloat(this.calculateVerticalShift().value);
        const horizontalShift = parseFloat(this.calculateHorizontalShift().value);
        const skewChange = parseFloat(this.calculateSkewChange().value);
        
        let sentiment = '中性';
        
        if (verticalShift > 1 && horizontalShift > 0 && skewChange > 0) {
            sentiment = '强烈看涨';
        } else if (verticalShift > 1 && horizontalShift < 0 && skewChange > 0) {
            sentiment = '波动加大，方向不明';
        } else if (verticalShift < -1 && horizontalShift < 0 && skewChange < 0) {
            sentiment = '强烈看跌';
        } else if (verticalShift > 0.5) {
            sentiment = '偏多波动';
        } else if (verticalShift < -0.5) {
            sentiment = '偏空波动';
        }
        
        return sentiment;
    }

    getMarketSentimentDescription() {
        const sentiment = this.getMarketSentiment();
        
        const descriptions = {
            '强烈看涨': 'IV全面上升，微笑曲线右移，市场预期大幅上涨',
            '强烈看跌': 'IV全面上升，微笑曲线左移，市场预期大幅下跌',
            '偏多波动': 'IV温和上升，市场预期上涨但幅度有限',
            '偏空波动': 'IV温和下降，市场预期下跌但幅度有限',
            '波动加大，方向不明': 'IV上升但微笑曲线扭曲，市场分歧加大',
            '中性': 'IV变化不大，市场处于平衡状态'
        };
        
        return descriptions[sentiment] || '市场情绪平稳';
    }

    // 动画控制
    startAnimation() {
        if (this.isAnimating) return;
        
        this.isAnimating = true;
        this.animationFrame = 0;
        
        const speed = parseInt(document.getElementById('animationSpeed').value);
        const interval = 1000 / speed;
        
        this.animationInterval = setInterval(() => {
            this.animationFrame++;
            
            if (this.animationFrame >= this.maxAnimationFrames) {
                this.animationFrame = 0;
            }
            
            // 生成动画中间状态
            this.animateCurveTransition();
            
        }, interval);
        
        this.showStatus('动画播放中...', 'info');
    }

    pauseAnimation() {
        if (this.animationInterval) {
            clearInterval(this.animationInterval);
            this.animationInterval = null;
            this.isAnimating = false;
            this.showStatus('动画已暂停', 'info');
        }
    }

    resetAnimation() {
        this.pauseAnimation();
        this.animationFrame = 0;
        this.updateChart();
        this.showStatus('动画已重置', 'info');
    }

    animateCurveTransition() {
        if (!this.previousData || !this.realTimeData) return;
        
        const progress = this.animationFrame / this.maxAnimationFrames;
        
        // 插值生成中间状态
        const animatedIV = this.previousData.ivValues.map((prevIV, i) => {
            const currIV = this.realTimeData.ivValues[i];
            return prevIV + (currIV - prevIV) * progress;
        });
        
        // 创建动画数据集
        const animatedData = {
            ...this.realTimeData,
            ivValues: animatedIV,
            timestamp: `动画帧 ${this.animationFrame}/${this.maxAnimationFrames}`
        };
        
        // 临时更新图表
        const tempChart = this.chart;
        const animatedDataset = {
            label: `动画过渡 (${animatedData.timestamp})`,
            data: animatedData.strikePrices.map((x, i) => ({x, y: animatedIV[i]})),
            borderColor: 'rgba(255, 193, 7, 0.8)',
            backgroundColor: 'rgba(255, 193, 7, 0.1)',
            borderWidth: 3,
            borderDash: [3, 3],
            fill: false,
            tension: 0.4,
            pointRadius: 0
        };
        
        // 替换实时数据为动画数据
        const datasets = tempChart.data.datasets.filter(ds => !ds.label.includes('实时数据'));
        datasets.push(animatedDataset);
        
        tempChart.data.datasets = datasets;
        tempChart.update();
    }

    // 分析函数
    analyzeVerticalShift() {
        const result = this.calculateVerticalShift();
        this.showAnalysisAlert('垂直移动分析', result.description, result.value);
    }

    analyzeHorizontalShift() {
        const result = this.calculateHorizontalShift();
        this.showAnalysisAlert('水平移动分析', result.description, result.value);
    }

    analyzeTwist() {
        const result = this.calculateTwistAnalysis();
        this.showAnalysisAlert('扭曲分析', result.description, result.value);
    }

    showAnalysisAlert(title, description, value) {
        alert(`🔍 ${title}\n\n📊 数值: ${value}\n📝 解读: ${description}`);
    }

    // 工具函数
    showStatus(message, type = 'info') {
        const statusBar = document.getElementById('statusBar');
        statusBar.textContent = message;
        statusBar.style.display = 'block';
        
        // 根据类型设置颜色
        const colors = {
            info: 'rgba(0, 0, 0, 0.8)',
            success: 'rgba(76, 175, 80, 0.9)',
            error: 'rgba(244, 67, 54, 0.9)',
            warning: 'rgba(255, 152, 0, 0.9)'
        };
        
        statusBar.style.background = colors[type] || colors.info;
        
        // 3秒后自动隐藏
        setTimeout(() => {
            statusBar.style.display = 'none';
        }, 3000);
    }

    // 数据加载函数（供外部调用）
    async loadData() {
        const symbol = document.getElementById('symbolSelect').value;
        const expiry = document.getElementById('expirySelect').value;
        const timeRange = document.getElementById('timeRange').value;
        
        this.showStatus(`正在加载 ${symbol} ${expiry} 数据...`, 'info');
        
        try {
            // 同时获取前日和实时数据
            const [previousResponse, realtimeResponse] = await Promise.all([
                this.fetchIVData('previous', symbol, expiry),
                this.fetchIVData('current', symbol, expiry)
            ]);
            
            if (previousResponse && realtimeResponse) {
                this.previousData = this.processAPIData(previousResponse, 'previous');
                this.realTimeData = this.processAPIData(realtimeResponse, 'realtime');
                this.showStatus(`${symbol} API数据加载完成`, 'success');
            } else {
                // API失败时使用模拟数据
                this.previousData = this.generateMockData('previous');
                this.realTimeData = this.generateMockData('realtime');
                this.showStatus(`${symbol} 使用模拟数据`, 'warning');
            }
            
            // 获取分析结果
            await this.fetchAnalysis(symbol, expiry);
            
            this.updateChart();
            
        } catch (error) {
            console.error('加载数据失败:', error);
            // 使用模拟数据作为后备
            this.previousData = this.generateMockData('previous');
            this.realTimeData = this.generateMockData('realtime');
            this.updateChart();
            this.showStatus('数据加载失败，使用模拟数据', 'error');
        }
    }
    
    async fetchAnalysis(symbol, expiry) {
        try {
            const response = await fetch(`http://localhost:5000/api/iv/analyze?symbol=${symbol}&expiry=${expiry}`);
            if (response.ok) {
                const analysis = await response.json();
                // 可以在这里使用分析结果
                console.log('曲线移动分析:', analysis);
            }
        } catch (error) {
            console.warn('无法获取分析数据:', error);
        }
    }

    exportChart() {
        const link = document.createElement('a');
        link.download = `IV曲线_${new Date().toISOString().slice(0, 10)}.png`;
        link.href = this.chart.toBase64Image();
        link.click();
        this.showStatus('图表已导出为PNG文件', 'success');
    }
}

// 全局函数供HTML调用
let ivCurveInstance = null;

function initIVCurve() {
    ivCurveInstance = new IVCurve();
}

function loadData() {
    if (ivCurveInstance) {
        ivCurveInstance.loadData();
    }
}

function exportChart() {
    if (ivCurveInstance) {
        ivCurveInstance.exportChart();
    }
}

function startAnimation() {
    if (ivCurveInstance) {
        ivCurveInstance.startAnimation();
    }
}

function pauseAnimation() {
    if (ivCurveInstance) {
        ivCurveInstance.pauseAnimation();
    }
}

function resetAnimation() {
    if (ivCurveInstance) {
        ivCurveInstance.resetAnimation();
    }
}

function analyzeVerticalShift() {
    if (ivCurveInstance) {
        ivCurveInstance.analyzeVerticalShift();
    }
}

function analyzeHorizontalShift() {
    if (ivCurveInstance) {
        ivCurveInstance.analyzeHorizontalShift();
    }
}

function analyzeTwist() {
    if (ivCurveInstance) {
        ivCurveInstance.analyzeTwist();
    }
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', initIVCurve);