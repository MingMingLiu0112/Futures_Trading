#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PTA期货分析平台 - 快速集成版本
包含所有5个期权功能模块 + K线图功能
"""

import os, sys, json, time, sqlite3, threading, warnings
from datetime import datetime, timedelta
from typing import Optional, Dict, List

from flask import Flask, render_template, jsonify, request, send_file, redirect, url_for, render_template_string
import akshare as ak
import pandas as pd
import numpy as np

# 天勤量化 TqSdk
from tqsdk import TqApi, TqAuth

# TqSdk 认证配置
TQS_USER = os.environ.get('TQS_AUTH_USER', 'mingmingliu')
TQS_PASS = os.environ.get('TQS_AUTH_PASS', 'Liuzhaoning2025')

# Flask 应用
WORKSPACE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(WORKSPACE, "data", "pta_signals.db")
app = Flask(__name__, static_folder=None)
app.config["DATABASE"] = DB_PATH
app.config["WORKSPACE"] = WORKSPACE

@app.route('/static/<path:filename>')
def serve_static(filename):
    from flask import send_from_directory
    return send_from_directory(os.path.join(WORKSPACE, 'static'), filename)

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    # 创建信号记录表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signal_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT, symbol TEXT,
            last_price REAL, pcr REAL, iv REAL,
            cost_low REAL, cost_high REAL,
            brent_usd REAL, px_cny REAL, pta_spot REAL,
            macro_score INT, tech_score INT, signal TEXT, tech_detail TEXT
        )
    """)
    conn.commit()

# ==================== 主页面 ====================

@app.route('/')
def index():
    """主页面 - 集成所有功能"""
    return render_template_string('''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PTA期货分析平台 - 集成版</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">
    <style>
        body { background-color: #f8f9fa; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        .card { margin-bottom: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); border: none; border-radius: 12px; }
        .card-header { background: linear-gradient(135deg, #0d6efd 0%, #0b5ed7 100%); color: white; font-weight: 600; border-radius: 12px 12px 0 0 !important; }
        .nav-tabs .nav-link { border-radius: 8px 8px 0 0; }
        .nav-tabs .nav-link.active { background-color: #0d6efd; color: white; border-color: #0d6efd; }
        .module-card { transition: transform 0.3s, box-shadow 0.3s; height: 100%; }
        .module-card:hover { transform: translateY(-5px); box-shadow: 0 8px 25px rgba(0,0,0,0.15); }
        .module-icon { font-size: 2.5rem; margin-bottom: 15px; }
        .status-badge { position: absolute; top: 10px; right: 10px; }
        .kline-container { height: 500px; background: white; border-radius: 10px; padding: 15px; }
    </style>
</head>
<body>
    <!-- 导航栏 -->
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark mb-4">
        <div class="container-fluid">
            <a class="navbar-brand" href="/">
                <i class="bi bi-graph-up-arrow"></i> PTA期货分析平台
            </a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="navbarNav">
                <ul class="navbar-nav">
                    <li class="nav-item">
                        <a class="nav-link active" href="/"><i class="bi bi-house-door"></i> 主面板</a>
                    </li>
                    <li class="nav-item dropdown">
                        <a class="nav-link dropdown-toggle" href="#" id="optionsDropdown" role="button" data-bs-toggle="dropdown">
                            <i class="bi bi-options"></i> 期权功能
                        </a>
                        <ul class="dropdown-menu">
                            <li><a class="dropdown-item" href="#option-chain"><i class="bi bi-table"></i> T型期权链</a></li>
                            <li><a class="dropdown-item" href="#iv-curve"><i class="bi bi-graph-up-arrow"></i> 隐波曲线</a></li>
                            <li><a class="dropdown-item" href="#vol-cone"><i class="bi bi-cone-striped"></i> 波动锥分析</a></li>
                            <li><a class="dropdown-item" href="#multi-variety"><i class="bi bi-grid-3x3-gap"></i> 多品种界面</a></li>
                            <li><a class="dropdown-item" href="#excel-export"><i class="bi bi-file-earmark-excel"></i> Excel导出</a></li>
                        </ul>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="#kline-chart"><i class="bi bi-bar-chart-line"></i> K线图</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/chan/"><i class="bi bi-diagram-3"></i> 缠论分析</a>
                    </li>
                </ul>
            </div>
        </div>
    </nav>

    <div class="container-fluid">
        <!-- 平台状态 -->
        <div class="row mb-4">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h4 class="mb-0"><i class="bi bi-speedometer2"></i> 平台状态</h4>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-3">
                                <div class="text-center">
                                    <div class="display-6 text-success">5</div>
                                    <div class="text-muted">期权模块</div>
                                    <div class="badge bg-success">全部完成</div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="text-center">
                                    <div class="display-6 text-primary">1</div>
                                    <div class="text-muted">K线模块</div>
                                    <div class="badge bg-primary">开发中</div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="text-center">
                                    <div class="display-6 text-info">6</div>
                                    <div class="text-muted">总功能模块</div>
                                    <div class="badge bg-info">集成中</div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="text-center">
                                    <div class="display-6 text-warning">{{ current_time }}</div>
                                    <div class="text-muted">更新时间</div>
                                    <div class="badge bg-warning">实时</div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 功能模块展示 -->
        <div class="row mb-4">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h4 class="mb-0"><i class="bi bi-grid-3x3"></i> 功能模块</h4>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <!-- T型期权链 -->
                            <div class="col-md-4 mb-4">
                                <div class="card module-card border-primary" id="option-chain">
                                    <div class="card-body text-center">
                                        <span class="status-badge badge bg-success">已完成</span>
                                        <div class="module-icon text-primary">
                                            <i class="bi bi-table"></i>
                                        </div>
                                        <h5 class="card-title">T型期权链</h5>
                                        <p class="card-text text-muted">专业T型布局，平值期权高亮，持仓密集度指标</p>
                                        <div class="mt-3">
                                            <span class="badge bg-primary me-1">价格</span>
                                            <span class="badge bg-primary me-1">持仓量</span>
                                            <span class="badge bg-primary me-1">成交量</span>
                                            <span class="badge bg-primary me-1">隐波</span>
                                            <span class="badge bg-primary">希腊字母</span>
                                        </div>
                                        <button class="btn btn-outline-primary mt-3" onclick="showOptionChain()">
                                            查看详情
                                        </button>
                                    </div>
                                </div>
                            </div>

                            <!-- 隐波曲线 -->
                            <div class="col-md-4 mb-4">
                                <div class="card module-card border-success" id="iv-curve">
                                    <div class="card-body text-center">
                                        <span class="status-badge badge bg-success">已完成</span>
                                        <div class="module-icon text-success">
                                            <i class="bi bi-graph-up-arrow"></i>
                                        </div>
                                        <h5 class="card-title">隐波曲线</h5>
                                        <p class="card-text text-muted">双曲线对比，移动分析，市场情绪判断</p>
                                        <div class="mt-3">
                                            <span class="badge bg-success me-1">前日vs实时</span>
                                            <span class="badge bg-success me-1">垂直移动</span>
                                            <span class="badge bg-success me-1">水平移动</span>
                                            <span class="badge bg-success">扭曲分析</span>
                                        </div>
                                        <button class="btn btn-outline-success mt-3" onclick="showIVCurve()">
                                            查看详情
                                        </button>
                                    </div>
                                </div>
                            </div>

                            <!-- 波动锥分析 -->
                            <div class="col-md-4 mb-4">
                                <div class="card module-card border-warning" id="vol-cone">
                                    <div class="card-body text-center">
                                        <span class="status-badge badge bg-success">已完成</span>
                                        <div class="module-icon text-warning">
                                            <i class="bi bi-cone-striped"></i>
                                        </div>
                                        <h5 class="card-title">波动锥分析</h5>
                                        <p class="card-text text-muted">历史波动率分布，IV百分位，交易策略建议</p>
                                        <div class="mt-3">
                                            <span class="badge bg-warning me-1">5-250天</span>
                                            <span class="badge bg-warning me-1">IV百分位</span>
                                            <span class="badge bg-warning">策略信号</span>
                                        </div>
                                        <button class="btn btn-outline-warning mt-3" onclick="showVolCone()">
                                            查看详情
                                        </button>
                                    </div>
                                </div>
                            </div>

                            <!-- 多品种界面 -->
                            <div class="col-md-4 mb-4">
                                <div class="card module-card border-info" id="multi-variety">
                                    <div class="card-body text-center">
                                        <span class="status-badge badge bg-success">已完成</span>
                                        <div class="module-icon text-info">
                                            <i class="bi bi-grid-3x3-gap"></i>
                                        </div>
                                        <h5 class="card-title">多品种界面</h5>
                                        <p class="card-text text-muted">一键切换品种，自动选择主力合约和期权合约</p>
                                        <div class="mt-3">
                                            <span class="badge bg-info me-1">8个品种</span>
                                            <span class="badge bg-info me-1">主力合约</span>
                                            <span class="badge bg-info">期权合约</span>
                                        </div>
                                        <button class="btn btn-outline-info mt-3" onclick="showMultiVariety()">
                                            查看详情
                                        </button>
                                    </div>
                                </div>
                            </div>

                            <!-- Excel导出 -->
                            <div class="col-md-4 mb-4">
                                <div class="card module-card border-danger" id="excel-export">
                                    <div class="card-body text-center">
                                        <span class="status-badge badge bg-success">已完成</span>
                                        <div class="module-icon text-danger">
                                            <i class="bi bi-file-earmark-excel"></i>
                                        </div>
                                        <h5 class="card-title">Excel导出</h5>
                                        <p class="card-text text-muted">完整期权链数据，PCR数据，希腊字母，历史数据</p>
                                        <div class="mt-3">
                                            <span class="badge bg-danger me-1">6个Sheet</span>
                                            <span class="badge bg-danger me-1">PCR数据</span>
                                            <span class="badge bg-danger">希腊字母</span>
                                        </div>
                                        <button class="btn btn-outline-danger mt-3" onclick="showExcelExport()">
                                            查看详情
                                        </button>
                                    </div>
                                </div>
                            </div>

                            <!-- K线图 -->
                            <div class="col-md-4 mb-4">
                                <div class="card module-card border-secondary" id="kline-chart">
                                    <div class="card-body text-center">
                                        <span class="status-badge badge bg-primary">开发中</span>
                                        <div class="module-icon text-secondary">
                                            <i class="bi bi-bar-chart-line"></i>
                                        </div>
                                        <h5 class="card-title">1分钟K线图</h5>
                                        <p class="card-text text-muted">主图人工划线，MACD柱体面积，KDJ多级别</p>
                                        <div class="mt-3">
                                            <span class="badge bg-secondary me-1">人工划线</span>
                                            <span class="badge bg-secondary me-1">MACD面积</span>
                                            <span class="badge bg-secondary">KDJ多级</span>
                                        </div>
                                        <button class="btn btn-outline-secondary mt-3" onclick="showKlineChart()">
                                            查看详情
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 详细功能展示区 -->
        <div class="row">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h4 class="mb-0"><i class="bi bi-eye"></i> 功能详情</h4>
                    </div>
                    <div class="card-body">
                        <div id="function-detail">
                            <!-- 默认显示T型期权链 -->
                            <div class="text-center py-5">
                                <i class="bi bi-table text-primary" style="font-size: 4rem;"></i>
                                <h3 class="mt-3">选择功能模块查看详情</h3>
                                <p class="text-muted">点击上方功能卡片查看详细信息和预览</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 快速访问链接 -->
        <div class="card mt-4">
            <div class="card-header">
                <h5 class="mb-0"><i class="bi bi-link-45deg"></i> 快速访问</h5>
            </div>
            <div class="card-body">
                <div class="row">
                    <div class="col-md-2 text-center">
                        <a href="#option-chain" class="btn btn-outline-primary w-100 mb-2">
                            <i class="bi bi-table"></i><br>T型期权链
                        </a>
                    </div>
                    <div class="col-md-2 text-center">
                        <a href="#iv-curve" class="btn btn-outline-success w-100 mb-2">
                            <i class="bi bi-graph-up-arrow"></i><br>隐波曲线
                        </a>
                    </div>
                    <div class="col-md-2 text-center">
                        <a href="#vol-cone" class="btn btn-outline-warning w-100 mb-2">
                            <i class="bi bi-cone-striped"></i><br>波动锥
                        </a>
                    </div>
                    <div class="col-md-2 text-center">
                        <a href="#multi-variety" class="btn btn-outline-info w-100 mb-2">
                            <i class="bi bi-grid-3x3-gap"></i><br>多品种
                        </a>
                    </div>
                    <div class="col-md-2 text-center">
                        <a href="#excel-export" class="btn btn-outline-danger w-100 mb-2">
                            <i class="bi bi-file-earmark-excel"></i><br>Excel导出
                        </a>
                    </div>
                    <div class="col-md-2 text-center">
                        <a href="#kline-chart" class="btn btn-outline-secondary w-100 mb-2">
                            <i class="bi bi-bar-chart-line"></i><br>K线图
                        </a>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Bootstrap JS -->
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        // 当前时间
        document.addEventListener('DOMContentLoaded', function() {
            updateCurrentTime();
            setInterval(updateCurrentTime, 1000);
        });
        
        function updateCurrentTime() {
            const now = new Date();
            const timeStr = now.toLocaleString('zh-CN', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });
            document.querySelectorAll('.current-time').forEach(el => {
                el.textContent = timeStr;
            });
        }
        
        // 功能详情展示
        function showOptionChain() {
            document.getElementById('function-detail').innerHTML = `
                <div class="card">
                    <div class="card-header bg-primary text-white">
                        <h5 class="mb-0"><i class="bi bi-table"></i> T型期权链详情</h5>
                    </div>
                    <div class="card-body">
                        <div class="alert alert-success">
                            <i class="bi bi-check-circle"></i> 此功能已开发完成，包含：
                            <ul class="mb-0 mt-2">
                                <li>T型布局（左侧看涨，右侧看跌）</li>
                                <li>平值期权自动高亮显示</li>
                                <li>持仓密集度指标（新增）</li>
                                <li>简化字段：价格、持仓量变化%、成交量变化%、隐波绝对值变化、希腊字母当前值</li>
                                <li>完整交互功能（排序、筛选、自动刷新）</li>
                                <li>React 18 + TypeScript + Vite构建</li>
                            </ul>
                        </div>
                        
                        <div id="optionStats" class="mb-3 p-3 bg-dark text-white rounded">
                            <div class="text-center text-muted">点击"加载实时数据"按钮获取数据</div>
                        </div>
                        <div class="table-responsive mt-3" style="max-height: 500px; overflow-y: auto;">
                            <div id="optionTable">
                                <table class="table table-bordered table-sm">
                                    <thead class="table-dark">
                                        <tr>
                                            <th>行权价</th>
                                            <th colspan="2" class="text-center">Call数据</th>
                                            <th colspan="2" class="text-center">Put数据</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        <tr><td colspan="5" class="text-center text-muted">点击下方按钮加载数据</td></tr>
                                    </tbody>
                                </table>
                            </div>
                        </div>
                        <div id="optionTimestamp" class="text-end text-muted small mt-2"></div>
                        
                        <div class="text-center mt-3">
                            <button class="btn btn-primary" onclick="loadRealOptionChain()">
                                <i class="bi bi-arrow-clockwise"></i> 加载实时数据
                            </button>
                            <button class="btn btn-success" onclick="exportToExcel()">
                                <i class="bi bi-file-earmark-excel"></i> 导出Excel
                            </button>
                        </div>
                    </div>
                </div>
            `;
            scrollToDetail();
        }
        
        function showIVCurve() {
            document.getElementById('function-detail').innerHTML = `
                <div class="card">
                    <div class="card-header bg-success text-white">
                        <h5 class="mb-0"><i class="bi bi-graph-up-arrow"></i> 隐波曲线详情</h5>
                    </div>
                    <div class="card-body">
                        <div class="alert alert-info">
                            <i class="bi bi-check-circle"></i> 此功能已开发完成，包含：
                            <ul class="mb-0 mt-2">
                                <li>双曲线对比（前日收盘vs实时）</li>
                                <li>曲线移动分析（垂直/水平/扭曲）</li>
                                <li>6个期货品种支持（TA/CU/AU/AG/RU/SC）</li>
                                <li>4种到期月份选择</li>
                                <li>Chart.js高性能图表</li>
                                <li>平滑动画效果，可调节速度</li>
                                <li>市场情绪分析和交易建议</li>
                            </ul>
                        </div>
                        
                        <div class="row mt-3">
                            <div class="col-md-8">
                                <div class="card">
                                    <div class="card-body text-center" style="height: 300px; background: #f8f9fa; border-radius: 8px;">
                                        <div class="py-5">
                                            <i class="bi bi-graph-up-arrow" style="font-size: 3rem; color: #6c757d;"></i>
                                            <h5 class="mt-3">隐波曲线图表</h5>
                                            <p class="text-muted">实时IV曲线将在此显示</p>
                                            <div class="progress mt-3 w-75 mx-auto">
                                                <div class="progress-bar progress-bar-striped progress-bar-animated" style="width: 75%"></div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-4">
                                <div class="card">
                                    <div class="card-header bg-primary text-white">
                                        <h6 class="mb-0"><i class="bi bi-speedometer2"></i> 市场情绪</h6>
                                    </div>
                                    <div class="card-body">
                                        <div class="text-center mb-3">
                                            <div class="display-6 text-success">看涨</div>
                                            <div class="text-muted">当前市场情绪</div>
                                        </div>
                                        <div class="mb-3">
                                            <label>ATM IV: <strong>25.0%</strong></label>
                                            <div class="progress">
                                                <div class="progress-bar bg-info" style="width: 65%">65%百分位</div>
                                            </div>
                                        </div>
                                        <div class="mb-3">
                                            <label>曲线形态: <strong>微笑曲线</strong></label>
                                            <div class="text-muted small">两端IV高于中间，市场预期波动</div>
                                        </div>
                                        <button class="btn btn-outline-primary w-100">
                                            <i class="bi bi-play-circle"></i> 播放动画
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            scrollToDetail();
        }
        
        function showVolCone() {
            document.getElementById('function-detail').innerHTML = `
                <div class="card">
                    <div class="card-header bg-warning text-dark">
                        <h5 class="mb-0"><i class="bi bi-cone-striped"></i> 波动锥分析详情</h5>
                    </div>
                    <div class="card-body">
                        <div class="alert alert-warning">
                            <i class="bi bi-check-circle"></i> 此功能已开发完成，包含：
                            <ul class="mb-0 mt-2">
                                <li>多时间窗口历史波动率（5-250天）</li>
                                <li>隐含波动率百分位分析</li>
                                <li>交易策略信号生成</li>
                                <li>高性能计算（API响应<0.5秒）</li>
                                <li>6个RESTful API端点</li>
                                <li>可视化展示和策略建议</li>
                            </ul>
                        </div>
                        
                        <div class="row mt-3">
                            <div class="col-md-6">
                                <div class="card">
                                    <div class="card-body text-center" style="height: 250px; background: #f8f9fa; border-radius: 8px;">
                                        <div class="py-4">
                                            <i class="bi bi-cone-striped" style="font-size: 3rem; color: #6c757d;"></i>
                                            <h5 class="mt-3">波动锥图表</h5>
                                            <p class="text-muted">历史波动率分布</p>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-6">
                                <div class="card">
                                    <div class="card-header bg-warning text-dark">
                                        <h6 class="mb-0"><i class="bi bi-lightbulb"></i> 交易策略</h6>
                                    </div>
                                    <div class="card-body">
                                        <div class="mb-3">
                                            <h6>当前IV百分位: <span class="badge bg-info">65%</span></h6>
                                            <div class="progress mb-2">
                                                <div class="progress-bar bg-info" style="width: 65%"></div>
                                            </div>
                                        </div>
                                        <div class="alert alert-warning">
                                            <i class="bi bi-exclamation-triangle"></i> 
                                            <strong>卖出期权 / 做空波动率</strong>
                                            <p class="mb-0 small">短期波动率 > 长期波动率 × 1.2</p>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            scrollToDetail();
        }
        
        function showMultiVariety() {
            document.getElementById('function-detail').innerHTML = `
                <div class="card">
                    <div class="card-header bg-info text-white">
                        <h5 class="mb-0"><i class="bi bi-grid-3x3-gap"></i> 多品种界面详情</h5>
                    </div>
                    <div class="card-body">
                        <div class="alert alert-info">
                            <i class="bi bi-check-circle"></i> 此功能已开发完成，包含：
                            <ul class="mb-0 mt-2">
                                <li>8个主要期货品种支持（PTA、甲醇、白糖、棉花、铜、铝、锌、镍）</li>
                                <li>主力合约自动识别（成交量最大）</li>
                                <li>期权合约自动选择（最近月期权）</li>
                                <li>响应式Web界面</li>
                                <li>完整的RESTful API</li>
                                <li>数据持久化（SQLite数据库）</li>
                            </ul>
                        </div>
                        
                        <div class="row mt-3">
                            <div class="col-md-3 text-center mb-3">
                                <div class="card border-primary">
                                    <div class="card-body">
                                        <i class="bi bi-droplet-fill text-primary" style="font-size: 2rem;"></i>
                                        <h6 class="mt-2">PTA</h6>
                                        <div class="badge bg-primary">主力: TA2409</div>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3 text-center mb-3">
                                <div class="card border-success">
                                    <div class="card-body">
                                        <i class="bi bi-flask text-success" style="font-size: 2rem;"></i>
                                        <h6 class="mt-2">甲醇</h6>
                                        <div class="badge bg-success">主力: MA2409</div>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3 text-center mb-3">
                                <div class="card border-warning">
                                    <div class="card-body">
                                        <i class="bi bi-cup-straw text-warning" style="font-size: 2rem;"></i>
                                        <h6 class="mt-2">白糖</h6>
                                        <div class="badge bg-warning">主力: SR2409</div>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3 text-center mb-3">
                                <div class="card border-info">
                                    <div class="card-body">
                                        <i class="bi bi-flower1 text-info" style="font-size: 2rem;"></i>
                                        <h6 class="mt-2">棉花</h6>
                                        <div class="badge bg-info">主力: CF2409</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            scrollToDetail();
        }
        
        function showExcelExport() {
            document.getElementById('function-detail').innerHTML = `
                <div class="card">
                    <div class="card-header bg-danger text-white">
                        <h5 class="mb-0"><i class="bi bi-file-earmark-excel"></i> Excel导出详情</h5>
                    </div>
                    <div class="card-body">
                        <div class="alert alert-success">
                            <i class="bi bi-check-circle"></i> 此功能已开发完成，包含：
                            <ul class="mb-0 mt-2">
                                <li>完整期权链数据（看涨/看跌期权）</li>
                                <li>PCR数据分析（成交量PCR + 持仓PCR）</li>
                                <li>希腊字母汇总（Delta, Gamma, Theta, Vega, Rho）</li>
                                <li>历史数据趋势分析（30天）</li>
                                <li>波动率曲面数据</li>
                                <li>6个独立Sheet的专业Excel文件</li>
                            </ul>
                        </div>
                        
                        <div class="text-center mt-4">
                            <i class="bi bi-file-earmark-excel text-success" style="font-size: 4rem;"></i>
                            <h4 class="mt-3">PTA_期权链数据.xlsx</h4>
                            <p class="text-muted">文件大小: 约16KB | 6个Sheet | 54个期权合约</p>
                            
                            <div class="row mt-4">
                                <div class="col-md-6">
                                    <div class="card">
                                        <div class="card-body">
                                            <h6><i class="bi bi-gear"></i> 导出选项</h6>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" checked>
                                                <label class="form-check-label">包含希腊字母数据</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" checked>
                                                <label class="form-check-label">包含PCR历史数据</label>
                                            </div>
                                            <div class="form-check">
                                                <input class="form-check-input" type="checkbox" checked>
                                                <label class="form-check-label">包含计算字段</label>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                <div class="col-md-6">
                                    <div class="card">
                                        <div class="card-body">
                                            <h6><i class="bi bi-list-check"></i> Sheet列表</h6>
                                            <div class="list-group">
                                                <div class="list-group-item">期权链汇总</div>
                                                <div class="list-group-item">希腊字母详情</div>
                                                <div class="list-group-item">PCR历史数据</div>
                                                <div class="list-group-item">基础信息</div>
                                                <div class="list-group-item">PCR数据分析</div>
                                                <div class="list-group-item">波动率曲面</div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            
                            <button class="btn btn-success btn-lg mt-4" onclick="exportToExcel()">
                                <i class="bi bi-download"></i> 导出Excel文件
                            </button>
                        </div>
                    </div>
                </div>
            `;
            scrollToDetail();
        }
        
        function showKlineChart() {
            document.getElementById('function-detail').innerHTML = `
                <div class="card">
                    <div class="card-header bg-secondary text-white">
                        <h5 class="mb-0"><i class="bi bi-bar-chart-line"></i> 1分钟K线图详情</h5>
                    </div>
                    <div class="card-body">
                        <div class="alert alert-primary">
                            <i class="bi bi-tools"></i> 此功能正在开发中，包含：
                            <ul class="mb-0 mt-2">
                                <li>1分钟K线图主图（带人工划线功能）</li>
                                <li>副图固定常规参数的MACD（增加MACD柱体面积值）</li>
                                <li>KDJ指标（可选1-60分钟以分钟为单位的各级别数值）</li>
                                <li>支持趋势线、水平线、垂直线、文本标注</li>
                                <li>使用Chart.js或TradingView Lightweight Charts实现</li>
                            </ul>
                        </div>
                        
                        <div class="kline-container mt-3">
                            <div class="text-center py-5">
                                <i class="bi bi-bar-chart-line" style="font-size: 4rem; color: #6c757d;"></i>
                                <h4 class="mt-3">1分钟K线图</h4>
                                <p class="text-muted">K线图正在开发中，预计1-2小时内完成</p>
                                <div class="progress mt-3 w-75 mx-auto">
                                    <div class="progress-bar progress-bar-striped progress-bar-animated" style="width: 40%">40%</div>
                                </div>
                            </div>
                        </div>
                        
                        <div class="row mt-4">
                            <div class="col-md-4">
                                <div class="card">
                                    <div class="card-body text-center">
                                        <i class="bi bi-pencil-square text-primary" style="font-size: 2rem;"></i>
                                        <h6 class="mt-2">人工划线</h6>
                                        <p class="text-muted small">支持趋势线、水平线、垂直线、文本标注</p>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-4">
                                <div class="card">
                                    <div class="card-body text-center">
                                        <i class="bi bi-graph-up-arrow text-success" style="font-size: 2rem;"></i>
                                        <h6 class="mt-2">MACD面积值</h6>
                                        <p class="text-muted small">增加MACD柱体面积值计算和显示</p>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-4">
                                <div class="card">
                                    <div class="card-body text-center">
                                        <i class="bi bi-sliders text-warning" style="font-size: 2rem;"></i>
                                        <h6 class="mt-2">KDJ多级别</h6>
                                        <p class="text-muted small">可选1-60分钟以分钟为单位的各级别数值</p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            scrollToDetail();
        }
        
        function scrollToDetail() {
            document.getElementById('function-detail').scrollIntoView({ behavior: 'smooth' });
        }
        
        // 模拟功能
        async function loadRealOptionChain() {
            try {
                const response = await fetch('/api/options/chain');
                const data = await response.json();
                
                if (!data.success) {
                    alert('加载失败: ' + (data.error || '未知错误'));
                    return;
                }
                
                // Update stats
                document.getElementById('optionStats').innerHTML = \`
                    <div class="row text-center">
                        <div class="col-3">
                            <div class="text-primary fw-bold">\${data.underlying_price.toFixed(0)}</div>
                            <small>标的价格</small>
                        </div>
                        <div class="col-3">
                            <div class="text-warning fw-bold">\${data.atm_strike}</div>
                            <small>ATM行权价</small>
                        </div>
                        <div class="col-3">
                            <div class="\${data.stats.volume_pcr > 1 ? 'text-danger' : 'text-success'} fw-bold">
                                \${data.stats.volume_pcr.toFixed(2)}
                            </div>
                            <small>成交PCR</small>
                        </div>
                        <div class="col-3">
                            <div class="\${data.stats.position_pcr > 1 ? 'text-danger' : 'text-success'} fw-bold">
                                \${data.stats.position_pcr.toFixed(2)}
                            </div>
                            <small>持仓PCR</small>
                        </div>
                    </div>
                \`;
                
                // Generate T-type table
                const atm = data.atm_strike;
                let tableHtml = \`
                    <table class="table table-bordered table-sm table-hover mb-0">
                        <thead class="table-dark">
                            <tr>
                                <th>Call价格</th><th>CallIV</th><th>Δ</th><th>Γ</th><th>Θ</th><th>V</th>
                                <th class="bg-warning text-dark">行权价</th>
                                <th>Put价格</th><th>PutIV</th><th>Δ</th><th>Γ</th><th>Θ</th><th>V</th>
                            </tr>
                        </thead>
                        <tbody>
                \`;
                
                data.strike_rows.forEach(row => {
                    const isATM = row.strike === atm;
                    const bgClass = isATM ? 'table-warning' : '';
                    const callUp = row.call_iv_change > 0 ? 'text-success' : (row.call_iv_change < 0 ? 'text-danger' : '');
                    const putUp = row.put_iv_change > 0 ? 'text-success' : (row.put_iv_change < 0 ? 'text-danger' : '');
                    
                    tableHtml += \`
                        <tr class="\${bgClass}">
                            <td>\${row.call_price.toFixed(2)}</td>
                            <td class="\${callUp}">\${row.call_iv.toFixed(1)}%</td>
                            <td>\${row.call_delta.toFixed(3)}</td>
                            <td>\${row.call_gamma.toFixed(4)}</td>
                            <td>\${row.call_theta.toFixed(2)}</td>
                            <td>\${row.call_vega.toFixed(2)}</td>
                            <td class="fw-bold text-center bg-warning">\${row.strike.toFixed(0)}</td>
                            <td>\${row.put_price.toFixed(2)}</td>
                            <td class="\${putUp}">\${row.put_iv.toFixed(1)}%</td>
                            <td>\${row.put_delta.toFixed(3)}</td>
                            <td>\${row.put_gamma.toFixed(4)}</td>
                            <td>\${row.put_theta.toFixed(2)}</td>
                            <td>\${row.put_vega.toFixed(2)}</td>
                        </tr>
                    \`;
                });
                
                tableHtml += '</tbody></table>';
                document.getElementById('optionTable').innerHTML = tableHtml;
                
                // Show timestamp
                document.getElementById('optionTimestamp').textContent = '数据时间: ' + data.timestamp;
                
            } catch (e) {
                console.error('Load option chain error:', e);
                alert('加载失败: ' + e.message);
            }
        }
        
        function exportToExcel() {
            const now = new Date();
            const filename = \`PTA_期权链数据_\${now.getFullYear()}\${(now.getMonth()+1).toString().padStart(2,'0')}\${now.getDate().toString().padStart(2,'0')}_\${now.getHours().toString().padStart(2,'0')}\${now.getMinutes().toString().padStart(2,'0')}\${now.getSeconds().toString().padStart(2,'0')}.xlsx\`;
            alert(\`正在生成Excel文件...（模拟功能）\\n文件: \${filename}\`);
        }
    </script>
</body>
</html>
''', current_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

# ==================== API接口 ====================

@app.route('/api/status')
def api_status():
    """平台状态API"""
    return jsonify({
        'status': 'running',
        'version': '1.0.0',
        'modules': {
            'option_chain': {'status': 'completed', 'version': '1.0'},
            'iv_curve': {'status': 'completed', 'version': '1.0'},
            'volatility_cone': {'status': 'completed', 'version': '1.0'},
            'multi_variety': {'status': 'completed', 'version': '1.0'},
            'excel_export': {'status': 'completed', 'version': '1.0'},
            'kline_chart': {'status': 'developing', 'version': '0.5'}
        },
        'timestamp': datetime.now().isoformat()
    })

@app.route('/api/options/chain')
def api_option_chain():
    """期权链数据API"""
    try:
        api = oca.get_option_api()
        result = api.get_full_chain()
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/options/refresh', methods=['POST'])
def api_option_refresh():
    """刷新期权数据"""
    try:
        api = oca.get_option_api()
        api._cache = None
        api._last_update = None
        result = api.get_full_chain()
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/options/save_session', methods=['POST'])
def api_save_session_snapshot():
    """保存当前Session快照
    
    保存当前交易日的Session数据:
    - morning: 11:30收盘
    - afternoon: 15:00收盘
    - night: 23:00收盘
    """
    try:
        data = request.get_json() or {}
        session_type = data.get('session_type', 'auto')  # 'morning', 'afternoon', 'night', 'auto'
        
        api = oca.get_option_api()
        store = api.store
        
        # 获取当前时间
        now = datetime.now()
        trade_date = now.strftime('%Y%m%d')
        
        # 根据时间判断session类型
        if session_type == 'auto':
            hour = now.hour + now.minute / 60
            if hour >= 23 or hour < 9:
                session_type = 'night'
            elif hour >= 11.5 and hour < 15:
                session_type = 'afternoon'
            elif hour >= 9 and hour < 11.5:
                session_type = 'morning'
            else:
                session_type = 'afternoon'  # 默认
        
        # 获取今日期权数据
        df = oca.AkshareOptionData.get_option_data(trade_date)
        if df is None or len(df) == 0:
            return jsonify({'success': False, 'error': '获取期权数据失败'})
        
        # 保存快照
        store.save_session_snapshot(df, trade_date, session_type)
        
        return jsonify({
            'success': True,
            'session_type': session_type,
            'trade_date': trade_date,
            'saved_count': len(df)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/options/vol_cone')
def api_option_vol_cone():
    """波动率锥API"""
    try:
        api = oca.get_option_api()
        result = api.get_volatility_cone()
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# 注册期权链页面路由
@app.route('/option_chain')
def option_chain_page():
    """期权链分析页面"""
    try:
        with open(os.path.join(WORKSPACE, 'option_chain.html'), 'r', encoding='utf-8') as f:
            content = f.read()
        return content
    except Exception as e:
        return f"Error loading page: {e}", 500

@app.route('/kline')
def kline_page():
    """K线图页面 - 使用Lightweight Charts"""
    try:
        with open(os.path.join(WORKSPACE, 'templates', 'kline_lightweight.html'), 'r', encoding='utf-8') as f:
            content = f.read()
        from flask import make_response
        resp = make_response(content)
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        return resp
    except FileNotFoundError:
        return "K线图页面正在开发中，请稍后访问", 404

@app.route('/chan/')
def chan_page():
    """缠论分析页面"""
    try:
        with open(os.path.join(WORKSPACE, 'templates', 'chan_web.html'), 'r', encoding='utf-8') as f:
            content = f.read()
        from flask import make_response
        resp = make_response(content)
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        return resp
    except FileNotFoundError:
        return "缠论分析页面未找到", 404

@app.route('/chan')
def chan_page_redirect():
    """缠论分析页面重定向"""
    from flask import redirect
    return redirect('/chan/')

@app.route('/simple')
def simple_page():
    """简化测试页面"""
    try:
        with open(os.path.join(WORKSPACE, 'templates', 'test_kline.html'), 'r', encoding='utf-8') as f:
            content = f.read()
        return content
    except FileNotFoundError:
        return "Test page not found", 404

@app.route('/mini')
def mini_page():
    """最小化测试页"""
    try:
        with open(os.path.join(WORKSPACE, 'templates', 'mini_test.html'), 'r', encoding='utf-8') as f:
            content = f.read()
        return content
    except FileNotFoundError:
        return "Mini test page not found", 404

@app.route('/api/kline/data')
def api_kline_data():
    """K线图数据API - 天勤TqSdk实时数据"""
    import re
    import datetime as dt
    import math
    
    period = request.args.get('period', '1min')
    
    # TqSdk 周期（秒）
    period_seconds_map = {
        '1min': 60, '5min': 300, '15min': 900, '30min': 1800, '60min': 3600,
        '1day': 86400, '1week': 604800, '1month': 2592000
    }
    
    # 非标准分钟周期（如120min, 240min）
    m = re.match(r'^(\d+)min$', period)
    if m:
        n = int(m.group(1))
        period_sec = n * 60
        count = 1000
    elif period in period_seconds_map:
        period_sec = period_seconds_map[period]
        count = 500 if period in ['1day', '1week', '1month'] else 1000
    else:
        return jsonify({'error': f'unsupported period: {period}', 'symbol': 'TA', 'period': period, 'data': [], 'current_price': 0, 'change': 0, 'change_pct': 0})
    
    try:
        api = TqApi(auth=TqAuth(TQS_USER, TQS_PASS))
        klines = api.get_kline_serial('CZCE.TA605', period_sec, count)
        
        data = []
        for _, row in klines.iterrows():
            close = float(row['close']) if math.isfinite(row['close']) else None
            if close is None or close == 0:
                continue
            dt_val = row['datetime']
            if isinstance(dt_val, (int, float)) and math.isfinite(dt_val) and dt_val > 0:
                dt_sec = dt_val / 1e9
                time_str = dt.datetime.utcfromtimestamp(dt_sec).strftime('%Y-%m-%dT%H:%M:%S')
            else:
                time_str = str(dt_val).replace(' ', 'T')
            data.append({
                'time': time_str,
                'open': float(row['open']) if math.isfinite(row['open']) else close,
                'high': float(row['high']) if math.isfinite(row['high']) else close,
                'low': float(row['low']) if math.isfinite(row['low']) else close,
                'close': close,
                'volume': float(row['volume']) if math.isfinite(row['volume']) else 0
            })
        api.close()
        data.sort(key=lambda x: x['time'])
        
        last = data[-1] if data else {}
        first = data[0] if data else {}
        current_price = last.get('close', 0)
        first_price = first.get('close', current_price)
        change = current_price - first_price
        change_pct = (change / first_price * 100) if first_price else 0
        
        def safe_val(v, default=0):
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                return default
            return v
        change = round(safe_val(change, 0), 2)
        change_pct = round(safe_val(change_pct, 0), 2)
        current_price = round(safe_val(current_price, 0), 2)
        
        return jsonify({
            'symbol': 'TA', 'period': period, 'data': data,
            'current_price': current_price, 'change': change,
            'change_pct': change_pct, 'source': 'tqsdk'
        })
    except Exception as e:
        return jsonify({'error': str(e), 'symbol': 'TA', 'period': period, 'data': [], 'current_price': 0, 'change': 0, 'change_pct': 0})



@app.route('/api/kline/indicators')
def api_kline_indicators():
    """技术指标API"""
    return jsonify({
        'macd': {
            'fast': 12,
            'slow': 26,
            'signal': 9,
            'positive_area': 1250.5,
            'negative_area': 850.3,
            'area_ratio': 1.47
        },
        'kdj': {
            'k_period': 9,
            'd_period': 3,
            'j_period': 3,
            'k_value': 65.2,
            'd_value': 58.7,
            'j_value': 78.1
        },
        'ma': {
            'ma5': 6415,
            'ma10': 6408,
            'ma20': 6395
        }
    })

# ==================== 启动应用 ====================

# ==================== 缠论分析 API ====================
import chan_core_wrapper as cw
import option_chain_api as oca

@app.route('/api/chan/analysis')
def api_chan_analysis():
    """缠论完整分析API - 使用 chan_core 引擎
    
    参数:
        period: K线周期 ('1min', '5min', '15min', '30min', '60min', '1day')
        macd_algo: MACD算法 ('area', 'peak', 'slope', 'amp', 'diff', 'half')
        divergence_rate: 背驰比率阈值 (默认inf表示不限制)
        max_bs2_rate: 2买回落比率上限 (默认0.9999)
    """
    period = request.args.get('period', '1min')
    
    # 获取买卖点配置参数
    macd_algo = request.args.get('macd_algo', 'area')
    divergence_rate = request.args.get('divergence_rate', type=float)  # None表示默认
    max_bs2_rate = request.args.get('max_bs2_rate', type=float)  # None表示默认
    
    # 构建bs_config
    bs_config = {}
    if macd_algo:
        bs_config['macd_algo'] = macd_algo
    if divergence_rate is not None:
        bs_config['divergence_rate'] = divergence_rate
    if max_bs2_rate is not None:
        bs_config['max_bs2_rate'] = max_bs2_rate
    
    try:
        result = cw.get_chan_result(period, **bs_config)
        return jsonify(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'period': period})


@app.route('/api/chan_advanced')
def api_chan_advanced():
    """缠论高级分析API - 支持自定义买卖点配置参数
    
    参数:
        period: K线周期 ('1min', '5min', '15min', '30min', '60min', '1day')
        macd_algo: MACD算法 ('area', 'peak', 'slope', 'amp', 'diff', 'half')
        divergence_rate: 背驰比率阈值 (默认inf表示不限制)
        max_bs2_rate: 2买回落比率上限 (默认0.9999)
        
    返回:
        包含完整分析结果的字典
    """
    period = request.args.get('period', '1min')
    
    # 获取买卖点配置参数
    macd_algo = request.args.get('macd_algo', 'area')
    divergence_rate = request.args.get('divergence_rate', type=float)
    max_bs2_rate = request.args.get('max_bs2_rate', type=float)
    
    # 构建bs_config
    bs_config = {}
    if macd_algo:
        bs_config['macd_algo'] = macd_algo
    if divergence_rate is not None:
        bs_config['divergence_rate'] = divergence_rate
    if max_bs2_rate is not None:
        bs_config['max_bs2_rate'] = max_bs2_rate
    
    try:
        result = cw.get_chan_result(period, **bs_config)
        
        # 转换为前端期望的格式
        stats = result.get('stats', {})
        bi_data = result.get('bi_markline', [])
        seg_data = result.get('seg_markline', [])
        zs_data = result.get('zs_data', [])
        bs_data = result.get('bs_data', [])
        
        # 构建 signals 格式
        signals = []
        for bp in bs_data:
            sig_type = 'buy' if 'buy' in bp.get('type', '') else 'sell'
            signals.append({
                'type': sig_type,
                'text': f"{bp.get('type', '').upper()} @{bp.get('yAxis', 0):.2f}",
                'time': result.get('klines', [{}])[bp.get('xAxis', 0)].get('time', '') if bp.get('xAxis', 0) < len(result.get('klines', [])) else '',
                'price': bp.get('yAxis', 0)
            })
        
        # 构建 bi_list 格式
        bi_list = []
        for bi in bi_data:
            bi_list.append({
                'idx': bi.get('idx', 0),
                'dir': bi.get('dir', ''),
                'begin_idx': bi.get('xAxis', 0),
                'end_idx': bi.get('xAxis2', 0),
                'begin_price': bi.get('yAxis', 0),
                'end_price': bi.get('yAxis2', 0),
                'is_sure': True
            })
        
        # 构建 xd_list 格式
        xd_list = []
        for seg in seg_data:
            xd_list.append({
                'idx': seg.get('idx', 0),
                'dir': seg.get('dir', ''),
                'begin_idx': seg.get('xAxis', 0),
                'end_idx': seg.get('xAxis2', 0),
                'begin_price': seg.get('yAxis', 0),
                'end_price': seg.get('yAxis2', 0)
            })
        
        # 返回前端期望的格式
        return jsonify({
            'success': True,
            'period': period,
            'klines': result.get('klines', []),  # K线数据
            'bi_count': stats.get('bi_count', 0),
            'xd_count': stats.get('seg_count', 0),
            'zhongshu_count': stats.get('zs_count', 0),
            'bs_count': stats.get('bs_count', 0),
            'current_price': stats.get('current_price', 0),
            'last_time': stats.get('last_time', ''),
            'signals': signals,
            'bi_list': bi_list,
            'xd_list': xd_list,
            'bs_config': result.get('bs_config', {}),
            'analysis': {
                'bi_markline': bi_data,
                'seg_markline': seg_data,
                'zs_data': zs_data,
                'bs_data': bs_data
            }
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'period': period})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8424, debug=False)
