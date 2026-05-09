#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略导入API
支持文件上传和代码文本两种方式导入自定义策略
"""

import os
import re
import uuid
import time
import shutil
import hashlib
from datetime import datetime
from flask import Blueprint, request, jsonify

# 策略存储目录
STRATEGIES_DIR = os.path.join(os.path.dirname(__file__), 'user_strategies')

# 确保目录存在
os.makedirs(STRATEGIES_DIR, exist_ok=True)

# 全局策略注册表（运行时）
_registered_strategies = {}

# 内置策略列表
BUILTIN_STRATEGIES = [
    {'id': 'macd', 'name': 'MACD策略', 'symbol': 'PTA', 'period': '5min',
     'desc': '基于MACD金叉死叉的趋势跟踪策略'},
    {'id': 'bollinger', 'name': '布林带策略', 'symbol': 'PTA', 'period': '15min',
     'desc': '布林带突破策略，配合波动率过滤'},
    {'id': 'kdj', 'name': 'KDJ策略', 'symbol': 'PTA', 'period': '5min',
     'desc': 'KDJ超买超卖区间交易策略'},
    {'id': 'rsi', 'name': 'RSI策略', 'symbol': 'PTA', 'period': '15min',
     'desc': 'RSI相对强弱指标策略'},
    {'id': 'breakout', 'name': '突破策略', 'symbol': 'PTA', 'period': '5min',
     'desc': '均线+成交量突破确认策略'},
    {'id': 'atr', 'name': 'ATR策略', 'symbol': 'PTA', 'period': '15min',
     'desc': '基于ATR波动率管理的趋势策略'},
]

# ==================== 辅助函数 ====================

def _validate_strategy_code(code: str) -> tuple:
    """验证策略代码格式，返回 (是否有效, 类名列表, 错误信息)"""
    # 检查是否包含策略类
    class_pattern = r'class\s+(\w+)\s*\(\s*StrategyBase\s*\)'
    matches = re.findall(class_pattern, code)
    
    if not matches:
        return False, [], "未找到继承自 StrategyBase 的策略类"
    
    # 检查是否实现了 on_bar 方法
    if 'def on_bar' not in code:
        return False, [], "策略类必须实现 on_bar 方法"
    
    # 检查是否有危险的系统调用
    dangerous_patterns = ['os.system', 'subprocess.', 'eval(', 'exec(', 'import os', 'import subprocess']
    for pattern in dangerous_patterns:
        if pattern in code:
            return False, [], f"策略代码包含禁止的内容: {pattern}"
    
    return True, matches, None


def _compile_strategy(code: str, strategy_id: str) -> tuple:
    """编译策略代码，返回 (模块对象, 错误信息)"""
    try:
        # 创建隔离的命名空间
        namespace = {
            '__name__': f'user_strategy_{strategy_id}',
            '__file__': f'{STRATEGIES_DIR}/{strategy_id}.py',
        }
        
        # 添加基类引用
        from .strategy_base import StrategyBase, StrategySignal
        namespace['StrategyBase'] = StrategyBase
        namespace['StrategySignal'] = StrategySignal
        
        # 编译执行
        compiled = compile(code, f'{STRATEGIES_DIR}/{strategy_id}.py', 'exec')
        exec(compiled, namespace)
        
        return namespace, None
    except SyntaxError as e:
        return None, f"语法错误: {e}"
    except Exception as e:
        return None, f"编译错误: {e}"


def _extract_strategy_class(namespace: dict) -> tuple:
    """从命名空间提取策略类"""
    for name, obj in namespace.items():
        if isinstance(obj, type) and issubclass(obj, namespace['StrategyBase']) and obj != namespace['StrategyBase']:
            return obj, None
    return None, "未找到策略类"


def _save_strategy_file(strategy_id: str, code: str, metadata: dict) -> str:
    """保存策略文件到磁盘"""
    filepath = os.path.join(STRATEGIES_DIR, f'{strategy_id}.py')
    
    # 添加文件头
    header = f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用户自定义策略: {metadata.get('name', strategy_id)}
创建时间: {datetime.now().isoformat()}
策略ID: {strategy_id}
"""

'''
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(header + code)
    
    # 保存元数据
    meta_path = os.path.join(STRATEGIES_DIR, f'{strategy_id}.meta.json')
    import json
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    
    return filepath


# ==================== API路由 ====================

strategy_import_bp = Blueprint('strategy_import', __name__)


@strategy_import_bp.route('/api/strategy/list', methods=['GET'])
def list_strategies():
    """获取所有可用策略列表（内置+已导入）"""
    try:
        # 扫描用户策略
        user_strategies = []
        if os.path.exists(STRATEGIES_DIR):
            for fname in os.listdir(STRATEGIES_DIR):
                if fname.endswith('.meta.json'):
                    strategy_id = fname.replace('.meta.json', '')
                    meta_path = os.path.join(STRATEGIES_DIR, fname)
                    import json
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                    user_strategies.append({
                        'id': strategy_id,
                        'name': meta.get('name', strategy_id),
                        'symbol': meta.get('symbol', 'PTA'),
                        'period': meta.get('period', '5min'),
                        'desc': meta.get('desc', ''),
                        'created_at': meta.get('created_at', ''),
                        'type': 'user'
                    })
        
        # 合并内置策略
        all_strategies = [
            {**s, 'type': 'builtin'} for s in BUILTIN_STRATEGIES
        ] + user_strategies
        
        return jsonify({
            'success': True,
            'strategies': all_strategies,
            'total': len(all_strategies)
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400


@strategy_import_bp.route('/api/strategy/import/file', methods=['POST'])
def import_strategy_file():
    """通过文件上传导入策略"""
    try:
        # 检查是否有文件
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': '未提供文件'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': '文件名为空'}), 400
        
        # 读取文件内容
        code = file.read().decode('utf-8')
        
        # 获取元数据
        name = request.form.get('name', '').strip()
        symbol = request.form.get('symbol', 'PTA').strip()
        period = request.form.get('period', '5min').strip()
        desc = request.form.get('desc', '').strip()
        
        if not name:
            return jsonify({'success': False, 'error': '策略名称不能为空'}), 400
        
        # 验证代码
        valid, class_names, err = _validate_strategy_code(code)
        if not valid:
            return jsonify({'success': False, 'error': err}), 400
        
        # 生成策略ID
        strategy_id = request.form.get('id', '').strip()
        if not strategy_id:
            # 从文件名生成
            strategy_id = re.sub(r'[^a-zA-Z0-9_]', '_', os.path.splitext(file.filename)[0])
        
        # 检查是否已存在
        if os.path.exists(os.path.join(STRATEGIES_DIR, f'{strategy_id}.py')):
            return jsonify({'success': False, 'error': f'策略ID {strategy_id} 已存在'}), 400
        
        # 保存文件
        metadata = {
            'name': name,
            'symbol': symbol,
            'period': period,
            'desc': desc,
            'class_name': class_names[0],
            'created_at': datetime.now().isoformat(),
            'import_type': 'file',
            'original_filename': file.filename
        }
        
        filepath = _save_strategy_file(strategy_id, code, metadata)
        
        # 编译验证
        namespace, err = _compile_strategy(code, strategy_id)
        if err:
            # 删除已保存的文件
            os.remove(filepath)
            os.remove(filepath.replace('.py', '.meta.json'))
            return jsonify({'success': False, 'error': f'策略编译失败: {err}'}), 400
        
        # 注册到运行时
        strategy_class, _ = _extract_strategy_class(namespace)
        if strategy_class:
            _registered_strategies[strategy_id] = strategy_class
        
        return jsonify({
            'success': True,
            'strategy_id': strategy_id,
            'class_name': class_names[0],
            'message': f'策略 {name} 导入成功'
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400


@strategy_import_bp.route('/api/strategy/import/code', methods=['POST'])
def import_strategy_code():
    """通过代码文本导入策略"""
    try:
        data = request.get_json() or {}
        
        code = data.get('code', '').strip()
        if not code:
            return jsonify({'success': False, 'error': '策略代码不能为空'}), 400
        
        name = data.get('name', '').strip()
        symbol = data.get('symbol', 'PTA').strip()
        period = data.get('period', '5min').strip()
        desc = data.get('desc', '').strip()
        strategy_id = data.get('id', '').strip()
        
        if not name:
            return jsonify({'success': False, 'error': '策略名称不能为空'}), 400
        
        # 验证代码
        valid, class_names, err = _validate_strategy_code(code)
        if not valid:
            return jsonify({'success': False, 'error': err}), 400
        
        # 生成策略ID
        if not strategy_id:
            # 从类名+时间戳生成
            strategy_id = f"{class_names[0].lower()}_{int(time.time())}"
        
        # 检查是否已存在
        if os.path.exists(os.path.join(STRATEGIES_DIR, f'{strategy_id}.py')):
            return jsonify({'success': False, 'error': f'策略ID {strategy_id} 已存在'}), 400
        
        # 编译验证
        namespace, err = _compile_strategy(code, strategy_id)
        if err:
            return jsonify({'success': False, 'error': f'策略编译失败: {err}'}), 400
        
        strategy_class, err = _extract_strategy_class(namespace)
        if err:
            return jsonify({'success': False, 'error': err}), 400
        
        # 保存文件
        metadata = {
            'name': name,
            'symbol': symbol,
            'period': period,
            'desc': desc,
            'class_name': class_names[0],
            'created_at': datetime.now().isoformat(),
            'import_type': 'code'
        }
        
        _save_strategy_file(strategy_id, code, metadata)
        
        # 注册到运行时
        _registered_strategies[strategy_id] = strategy_class
        
        return jsonify({
            'success': True,
            'strategy_id': strategy_id,
            'class_name': class_names[0],
            'message': f'策略 {name} 导入成功'
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400


@strategy_import_bp.route('/api/strategy/<strategy_id>', methods=['GET'])
def get_strategy(strategy_id):
    """获取策略详情"""
    try:
        # 检查是否已注册
        if strategy_id in _registered_strategies:
            strategy_class = _registered_strategies[strategy_id]
            return jsonify({
                'success': True,
                'strategy_id': strategy_id,
                'name': getattr(strategy_class, 'name', strategy_id),
                'registered': True,
                'source': 'runtime'
            })
        
        # 从文件读取
        filepath = os.path.join(STRATEGIES_DIR, f'{strategy_id}.py')
        meta_path = os.path.join(STRATEGIES_DIR, f'{strategy_id}.meta.json')
        
        if not os.path.exists(filepath):
            return jsonify({'success': False, 'error': '策略不存在'}), 404
        
        # 读取元数据
        import json
        with open(meta_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        
        # 读取代码
        with open(filepath, 'r', encoding='utf-8') as f:
            code = f.read()
        
        return jsonify({
            'success': True,
            'strategy_id': strategy_id,
            'name': meta.get('name', strategy_id),
            'symbol': meta.get('symbol', 'PTA'),
            'period': meta.get('period', '5min'),
            'desc': meta.get('desc', ''),
            'class_name': meta.get('class_name', ''),
            'created_at': meta.get('created_at', ''),
            'source': 'file',
            'code_preview': code[:500]  # 预览前500字符
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400


@strategy_import_bp.route('/api/strategy/<strategy_id>', methods=['DELETE'])
def delete_strategy(strategy_id):
    """删除策略"""
    try:
        # 不允许删除内置策略
        if any(s['id'] == strategy_id for s in BUILTIN_STRATEGIES):
            return jsonify({'success': False, 'error': '无法删除内置策略'}), 400
        
        filepath = os.path.join(STRATEGIES_DIR, f'{strategy_id}.py')
        meta_path = os.path.join(STRATEGIES_DIR, f'{strategy_id}.meta.json')
        
        if not os.path.exists(filepath):
            return jsonify({'success': False, 'error': '策略不存在'}), 404
        
        # 删除文件
        os.remove(filepath)
        if os.path.exists(meta_path):
            os.remove(meta_path)
        
        # 从运行时移除
        if strategy_id in _registered_strategies:
            del _registered_strategies[strategy_id]
        
        return jsonify({
            'success': True,
            'message': f'策略 {strategy_id} 已删除'
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400


@strategy_import_bp.route('/api/strategy/<strategy_id>/validate', methods=['POST'])
def validate_strategy_code(strategy_id):
    """验证策略代码（不保存）"""
    try:
        data = request.get_json() or {}
        code = data.get('code', '').strip()
        
        if not code:
            return jsonify({'success': False, 'error': '策略代码不能为空'}), 400
        
        # 验证格式
        valid, class_names, err = _validate_strategy_code(code)
        if not valid:
            return jsonify({
                'success': False,
                'valid': False,
                'error': err
            }), 400
        
        # 编译验证
        test_id = f'validate_{int(time.time())}'
        namespace, err = _compile_strategy(code, test_id)
        if err:
            return jsonify({
                'success': False,
                'valid': False,
                'error': f'编译失败: {err}'
            }), 400
        
        # 提取类
        strategy_class, err = _extract_strategy_class(namespace)
        if err:
            return jsonify({
                'success': False,
                'valid': False,
                'error': err
            }), 400
        
        return jsonify({
            'success': True,
            'valid': True,
            'class_name': class_names[0],
            'message': '策略代码验证通过'
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400


def register_strategy_import_routes(app):
    """注册策略导入路由到Flask应用"""
    app.register_blueprint(strategy_import_bp)
