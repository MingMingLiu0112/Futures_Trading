"""
飞书推送模块
"""

import requests
import json
import os
from datetime import datetime
from typing import Dict, List, Optional


class FeishuPusher:
    """飞书机器人 Webhook 推送"""
    
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
    
    def send_text(self, text: str) -> bool:
        """发送纯文本消息"""
        payload = {
            "msg_type": "text",
            "content": {"text": text}
        }
        return self._send(payload)
    
    def send_rich_text(self, title: str, content: List[Dict]) -> bool:
        """
        发送富文本消息
        
        Args:
            title: 标题
            content: 内容列表，每项包含 tag 和 text
        """
        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": title,
                        "content": [
                            [
                                {"tag": "text", "text": item.get("text", "")}
                            ] for item in content
                        ]
                    }
                }
            }
        }
        return self._send(payload)
    
    def send_card(self, card_content: Dict) -> bool:
        """发送卡片消息"""
        payload = {
            "msg_type": "interactive",
            "card": card_content
        }
        return self._send(payload)
    
    def send_analysis_report(self, report_data: Dict) -> bool:
        """
        发送分析报告卡片
        """
        card = {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"📊 {report_data.get('title', '期货期权分析报告')}"
                },
                "template": report_data.get("template", "blue")
            },
            "elements": []
        }
        
        # 基础信息
        card["elements"].append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**品种**: {report_data.get('symbol', 'N/A')}\n"
                          f"**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            }
        })
        
        # IV信号
        if "iv_signal" in report_data:
            iv = report_data["iv_signal"]
            card["elements"].append({
                "tag": "hr"
            })
            card["elements"].append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**📈 波动率信号**\n"
                              f"• IV Rank: {iv.get('iv_rank', 'N/A')}%\n"
                              f"• IV Skew: {iv.get('skew', 'N/A')}\n"
                              f"• 市场情绪: {iv.get('sentiment', 'N/A')}"
                }
            })
        
        # 综合信号
        if "composite" in report_data:
            comp = report_data["composite"]
            card["elements"].append({
                "tag": "hr"
            })
            card["elements"].append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**🎯 综合信号**\n"
                              f"• 建议: **{comp.get('recommendation', 'N/A')}**\n"
                              f"• 置信度: {comp.get('confidence', 'N/A')}\n"
                              f"• 评分: {comp.get('score', 0):+d}"
                }
            })
        
        # 信号详情
        if "signals" in report_data and report_data["signals"]:
            signals_text = "\n".join([f"• {s}" for s in report_data["signals"]])
            card["elements"].append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**📋 信号列表**\n{signals_text}"
                }
            })
        
        # 风险提示
        card["elements"].append({
            "tag": "note",
            "elements": [
                {"tag": "plain_text", "content": "⚠️ 本分析仅供参考，不构成投资建议。"}
            ]
        })
        
        return self.send_card(card)
    
    def _send(self, payload: Dict) -> bool:
        """发送请求"""
        try:
            response = requests.post(
                self.webhook_url,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=10
            )
            result = response.json()
            if result.get("code") == 0 or result.get("StatusCode") == 0:
                return True
            else:
                print(f"飞书推送失败: {result}")
                return False
        except Exception as e:
            print(f"推送异常: {e}")
            return False


# 全局推送器实例（需初始化）
pusher: Optional[FeishuPusher] = None

# 默认飞书 Webhook（从 memory 获取）
DEFAULT_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/8148922b-04f5-469f-994e-ae3e17d6b256"


def init_pusher(webhook_url: str = None):
    """初始化全局推送器"""
    global pusher
    url = webhook_url or os.getenv("FEISHU_WEBHOOK") or DEFAULT_WEBHOOK
    pusher = FeishuPusher(url)
    return pusher


def send_report(report_data: Dict) -> bool:
    """快捷发送报告"""
    if pusher is None:
        print("⚠️ 飞书推送器未初始化")
        return False
    return pusher.send_analysis_report(report_data)
