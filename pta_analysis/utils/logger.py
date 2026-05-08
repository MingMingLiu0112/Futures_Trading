#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志工具模块
提供统一的日志配置和管理
"""

import logging
import logging.handlers
import os
from typing import Optional


def setup_logger(
    name: str = 'trading_system',
    log_level: str = 'INFO',
    log_file: Optional[str] = None,
    console_output: bool = True
) -> logging.Logger:
    """
    配置日志记录器
    
    :param name: 日志记录器名称
    :param log_level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    :param log_file: 日志文件路径，为None时不输出到文件
    :param console_output: 是否输出到控制台
    :return: 配置好的日志记录器
    """
    # 创建日志记录器
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # 避免重复添加处理器
    if logger.handlers:
        return logger
    
    # 定义日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s'
    )
    
    # 控制台处理器
    if console_output:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, log_level.upper()))
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    # 文件处理器
    if log_file:
        # 确保日志目录存在
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        # 使用 RotatingFileHandler 限制文件大小
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,  # 保留5个备份
            encoding='utf-8'
        )
        file_handler.setLevel(getattr(logging, log_level.upper()))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


def get_logger(name: str = 'trading_system') -> logging.Logger:
    """
    获取日志记录器
    
    :param name: 日志记录器名称
    :return: 日志记录器
    """
    return logging.getLogger(name)


# 预配置的日志记录器
logger = setup_logger()
