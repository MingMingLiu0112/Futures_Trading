/**
 * 缠论图表绘制工具
 */

class ChanChartRenderer {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        this.chart = null;
        this.data = null;
    }
    
    /**
     * 初始化图表
     */
    initChart(data) {
        this.data = data;
        
        // 如果已有图表，销毁它
        if (this.chart) {
            this.chart.destroy();
        }
        
        // 准备图表数据
        const chartData = this.prepareChartData(data);
        
        // 创建图表
        this.chart = new Chart(this.ctx, {
            type: 'line',
            data: chartData,
            options: this.getChartOptions()
        });
        
        // 添加缠论元素
        this.addChanElements(data);
    }
    
    /**
     * 准备图表数据
     */
    prepareChartData(data) {
        const klines = data.klines || [];
        const timestamps = klines.map(k => new Date(k.time));
        const prices = klines.map(k => k.close);
        
        return {
            labels: timestamps,
            datasets: [{
                label: 'PTA价格',
                data: prices,
                borderColor: '#3498db',
                backgroundColor: 'rgba(52, 152, 219, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.1,
                pointRadius: 0
            }]
        };
    }
    
    /**
     * 获取图表选项
     */
    getChartOptions() {
        return {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    callbacks: {
                        label: function(context) {
                            let label = context.dataset.label || '';
                            if (label) {
                                label += ': ';
                            }
                            label += context.parsed.y.toFixed(2);
                            return label;
                        }
                    }
                }
            },
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: 'minute',
                        displayFormats: {
                            minute: 'HH:mm'
                        }
                    },
                    title: {
                        display: true,
                        text: '时间'
                    },
                    grid: {
                        color: 'rgba(0,0,0,0.05)'
                    }
                },
                y: {
                    title: {
                        display: true,
                        text: '价格'
                    },
                    ticks: {
                        callback: function(value) {
                            return value.toFixed(2);
                        }
                    },
                    grid: {
                        color: 'rgba(0,0,0,0.05)'
                    }
                }
            },
            interaction: {
                intersect: false,
                mode: 'index'
            }
        };
    }
    
    /**
     * 添加缠论元素
     */
    addChanElements(data) {
        if (!this.chart) return;
        
        // 添加笔
        this.addBiElements(data.bi_list || []);
        
        // 添加线段
        this.addXdElements(data.xd_list || []);
        
        // 添加中枢
        this.addZhongshuElements(data.zhongshu_list || []);
        
        // 添加分型
        this.addFenxingElements(data.fenxing_list || []);
    }
    
    /**
     * 添加笔元素
     */
    addBiElements(biList) {
        if (!this.chart || !biList.length) return;
        
        const chart = this.chart;
        const klines = this.data.klines || [];
        
        biList.forEach(bi => {
            const startIdx = bi.start_index;
            const endIdx = bi.end_index;
            
            if (startIdx < klines.length && endIdx < klines.length) {
                const startKline = klines[startIdx];
                const endKline = klines[endIdx];
                
                // 创建笔数据集
                chart.data.datasets.push({
                    label: bi.direction === 'up' ? '上升笔' : '下降笔',
                    data: [
                        { x: new Date(startKline.time), y: bi.start_price },
                        { x: new Date(endKline.time), y: bi.end_price }
                    ],
                    borderColor: bi.direction === 'up' ? '#27ae60' : '#e74c3c',
                    backgroundColor: 'transparent',
                    borderWidth: 2,
                    borderDash: [5, 5],
                    pointRadius: 4,
                    pointBackgroundColor: bi.direction === 'up' ? '#27ae60' : '#e74c3c',
                    fill: false,
                    tension: 0
                });
            }
        });
        
        chart.update();
    }
    
    /**
     * 添加线段元素
     */
    addXdElements(xdList) {
        if (!this.chart || !xdList.length) return;
        
        const chart = this.chart;
        const klines = this.data.klines || [];
        
        xdList.forEach((xd, index) => {
            // 获取线段对应的笔
            const startBiIdx = xd.start_bi_index;
            const endBiIdx = xd.end_bi_index;
            
            if (startBiIdx < this.data.bi_list.length && endBiIdx < this.data.bi_list.length) {
                const startBi = this.data.bi_list[startBiIdx];
                const endBi = this.data.bi_list[endBiIdx];
                
                // 找到对应的K线时间
                let startTime, endTime;
                if (startBi.start_index < klines.length) {
                    startTime = new Date(klines[startBi.start_index].time);
                }
                if (endBi.end_index < klines.length) {
                    endTime = new Date(klines[endBi.end_index].time);
                }
                
                if (startTime && endTime) {
                    // 创建线段数据集
                    chart.data.datasets.push({
                        label: `线段${index + 1}`,
                        data: [
                            { x: startTime, y: xd.start_price },
                            { x: endTime, y: xd.end_price }
                        ],
                        borderColor: '#9b59b6',
                        backgroundColor: 'transparent',
                        borderWidth: 3,
                        pointRadius: 0,
                        fill: false,
                        tension: 0
                    });
                }
            }
        });
        
        chart.update();
    }
    
    /**
     * 添加中枢元素
     */
    addZhongshuElements(zhongshuList) {
        if (!this.chart || !zhongshuList.length) return;
        
        const chart = this.chart;
        const klines = this.data.klines || [];
        
        zhongshuList.forEach((zs, index) => {
            // 找到中枢的时间范围
            const startXds = this.data.xd_list.slice(zs.start_xd_index, zs.end_xd_index + 1);
            if (!startXds.length) return;
            
            // 获取时间范围
            const firstXd = startXds[0];
            const lastXd = startXds[startXds.length - 1];
            
            let startTime, endTime;
            if (firstXd.start_bi_index < this.data.bi_list.length) {
                const firstBi = this.data.bi_list[firstXd.start_bi_index];
                if (firstBi.start_index < klines.length) {
                    startTime = new Date(klines[firstBi.start_index].time);
                }
            }
            if (lastXd.end_bi_index < this.data.bi_list.length) {
                const lastBi = this.data.bi_list[lastXd.end_bi_index];
                if (lastBi.end_index < klines.length) {
                    endTime = new Date(klines[lastBi.end_index].time);
                }
            }
            
            if (startTime && endTime) {
                // 创建中枢矩形
                const annotation = {
                    type: 'box',
                    xMin: startTime.getTime(),
                    xMax: endTime.getTime(),
                    yMin: zs.low,
                    yMax: zs.high,
                    backgroundColor: 'rgba(243, 156, 18, 0.2)',
                    borderColor: 'rgba(243, 156, 18, 0.5)',
                    borderWidth: 1,
                    label: {
                        display: true,
                        content: `中枢${index + 1}`,
                        position: 'start',
                        backgroundColor: 'rgba(243, 156, 18, 0.8)',
                        color: 'white',
                        font: {
                            size: 10
                        }
                    }
                };
                
                // 添加注释
                if (!chart.options.plugins.annotation) {
                    chart.options.plugins.annotation = { annotations: {} };
                }
                chart.options.plugins.annotation.annotations[`zhongshu_${index}`] = annotation;
            }
        });
        
        chart.update();
    }
    
    /**
     * 添加分型元素
     */
    addFenxingElements(fenxingList) {
        if (!this.chart || !fenxingList.length) return;
        
        const chart = this.chart;
        const klines = this.data.klines || [];
        
        fenxingList.forEach((fx, index) => {
            if (fx.index < klines.length) {
                const kline = klines[fx.index];
                const time = new Date(kline.time);
                
                // 创建分型点数据集
                chart.data.datasets.push({
                    label: fx.type === 'top' ? '顶分型' : '底分型',
                    data: [{ x: time, y: fx.price }],
                    borderColor: '#2c3e50',
                    backgroundColor: fx.type === 'top' ? '#e74c3c' : '#27ae60',
                    borderWidth: 2,
                    pointRadius: 6,
                    pointStyle: fx.type === 'top' ? 'triangle' : 'rectRot',
                    fill: true,
                    tension: 0
                });
            }
        });
        
        chart.update();
    }
    
    /**
     * 更新图表显示
     */
    updateDisplay(showBi, showXd, showZhongshu, showFenxing) {
        if (!this.chart) return;
        
        // 隐藏/显示数据集
        this.chart.data.datasets.forEach((dataset, index) => {
            if (index === 0) return; // 主K线图不隐藏
            
            const label = dataset.label || '';
            if (label.includes('笔') && !showBi) {
                dataset.hidden = true;
            } else if (label.includes('线段') && !showXd) {
                dataset.hidden = true;
            } else if (label.includes('分型') && !showFenxing) {
                dataset.hidden = true;
            } else {
                dataset.hidden = false;
            }
        });
        
        // 隐藏/显示中枢注释
        if (this.chart.options.plugins.annotation?.annotations) {
            Object.keys(this.chart.options.plugins.annotation.annotations).forEach(key => {
                if (key.startsWith('zhongshu_')) {
                    this.chart.options.plugins.annotation.annotations[key].display = showZhongshu;
                }
            });
        }
        
        this.chart.update();
    }
    
    /**
     * 销毁图表
     */
    destroy() {
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }
    }
}

// 导出全局实例
window.ChanChartRenderer = ChanChartRenderer;