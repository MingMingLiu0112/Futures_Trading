// 重置指标设置
function resetIndicatorSettings() {
    currentIndicators = JSON.parse(JSON.stringify(defaultIndicators));
    
    document.getElementById('macd-fast').value = defaultIndicators.macd.fast;
    document.getElementById('macd-slow').value = defaultIndicators.macd.slow;
    document.getElementById('macd-signal').value = defaultIndicators.macd.signal;
    
    document.getElementById('kdj-period').value = defaultIndicators.kdj.period;
    document.getElementById('kdj-k').value = defaultIndicators.kdj.k;
    document.getElementById('kdj-d').value = defaultIndicators.kdj.d;
    
    if (chartData) updateCharts();
    showNotification('指标参数已重置', 'info');
}

// 切换MACD面积显示
function toggleMACDArea() {
    const btn = document.getElementById('toggle-macd-area');
    const showing = btn.textContent.includes('显示');
    btn.innerHTML = showing ? 
        '<i class="fas fa-chart-area me-1"></i>隐藏MACD面积' :
        '<i class="fas fa-chart-area me-1"></i>显示MACD面积';
}

// 标注功能
function addHorizontalLine(y) {
    annotations.push({
        id: annotationIdCounter++,
        type: 'horizontal',
        y: y,
        color: document.getElementById('line-color').value,
        width: parseInt(document.getElementById('line-width').value),
        createdAt: new Date().toLocaleString()
    });
    updateAnnotationList();
    showNotification('水平线已添加', 'success');
}

function addVerticalLine(x) {
    annotations.push({
        id: annotationIdCounter++,
        type: 'vertical',
        x: x,
        color: document.getElementById('line-color').value,
        width: parseInt(document.getElementById('line-width').value),
        createdAt: new Date().toLocaleString()
    });
    updateAnnotationList();
    showNotification('垂直线已添加', 'success');
}

function addTextAnnotation(x, y) {
    const text = document.getElementById('text-content').value.trim();
    if (!text) {
        showNotification('请输入文本内容', 'warning');
        return;
    }
    
    annotations.push({
        id: annotationIdCounter++,
        type: 'text',
        x: x, y: y,
        text: text,
        color: document.getElementById('line-color').value,
        createdAt: new Date().toLocaleString()
    });
    
    updateAnnotationList();
    document.getElementById('text-content').value = '';
    showNotification('文本标注已添加', 'success');
}

// 更新标注列表
function updateAnnotationList() {
    const list = document.getElementById('annotation-list');
    
    if (annotations.length === 0) {
        list.innerHTML = '<div class="text-muted text-center py-3">暂无标注</div>';
        return;
    }
    
    let html = '';
    annotations.forEach(anno => {
        let typeText = '', details = '';
        
        switch(anno.type) {
            case 'horizontal':
                typeText = '水平线'; details = `Y=${anno.y.toFixed(2)}`; break;
            case 'vertical':
                typeText = '垂直线'; details = `X=${new Date(anno.x).toLocaleTimeString()}`; break;
            case 'text':
                typeText = '文本标注'; details = `"${anno.text}"`; break;
        }
        
        html += `
            <div class="annotation-item" data-id="${anno.id}">
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <strong>${typeText}</strong>
                        <small class="text-muted ms-2">${details}</small>
                    </div>
                    <div>
                        <small class="text-muted me-2">${anno.createdAt}</small>
                        <button class="btn btn-sm btn-outline-danger btn-delete-annotation" data-id="${anno.id}">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
            </div>
        `;
    });
    
    list.innerHTML = html;
    
    document.querySelectorAll('.btn-delete-annotation').forEach(btn => {
        btn.addEventListener('click', function() {
            deleteAnnotation(parseInt(this.dataset.id));
        });
    });
}

// 删除标注
function deleteAnnotation(id) {
    const index = annotations.findIndex(a => a.id === id);
    if (index !== -1) {
        annotations.splice(index, 1);
        updateAnnotationList();
        showNotification('标注已删除', 'info');
    }
}

// 清除所有标注
function clearAllAnnotations() {
    if (annotations.length === 0) {
        showNotification('没有可清除的标注', 'info');
        return;
    }
    
    if (confirm('确定要清除所有标注吗？')) {
        annotations = [];
        updateAnnotationList();
        showNotification('所有标注已清除', 'info');
    }
}

// 导出标注
function exportAnnotations() {
    if (annotations.length === 0) {
        showNotification('没有可导出的标注', 'warning');
        return;
    }
    
    const dataStr = JSON.stringify(annotations, null, 2);
    const dataUri = 'data:application/json;charset=utf-8,'+ encodeURIComponent(dataStr);
    
    const link = document.createElement('a');
    link.setAttribute('href', dataUri);
    link.setAttribute('download', `pta_annotations_${new Date().toISOString().slice(0,10)}.json`);
    link.click();
    
    showNotification('标注已导出', 'success');
}

// 导入标注
function importAnnotations() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    
    input.onchange = function(e) {
        const file = e.target.files[0];
        if (!file) return;
        
        const reader = new FileReader();
        reader.onload = function(e) {
            try {
                const imported = JSON.parse(e.target.result);
                if (Array.isArray(imported)) {
                    annotations = imported;
                    const maxId = annotations.reduce((max, a) => Math.max(max, a.id || 0), 0);
                    annotationIdCounter = maxId + 1;
                    updateAnnotationList();
                    showNotification('标注已导入', 'success');
                } else {
                    showNotification('文件格式不正确', 'error');
                }
            } catch (err) {
                showNotification('导入失败: ' + err.message, 'error');
            }
        };
        reader.readAsText(file);
    };
    
    input.click();
}

// 显示通知
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
    notification.style.cssText = `
        top: 20px;
        right: 20px;
        z-index: 9999;
        min-width: 300px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    `;
    
    notification.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        if (notification.parentNode) notification.remove();
    }, 3000);
}

// 页面初始化
document.addEventListener('DOMContentLoaded', function() {
    console.log('初始化K线图功能...');
    initKlineChart();
    bindEvents();
    loadData(1);
});

console.log('K线图功能已加载');