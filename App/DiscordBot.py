#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Discord Bot Module
负责远程监控交易状态、推送信号图表以及接收控制指令。
"""

import discord
from discord.ext import commands
import logging
import asyncio
import os
import threading
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

class DiscordBot:
    def __init__(self, token, channel_id, allowed_user_ids: list, controller=None):
        self.token = token
        self.channel_id = int(channel_id) if channel_id else None
        self.allowed_user_ids = [int(uid) for uid in allowed_user_ids]
        self.controller = controller
        
        intents = discord.Intents.default()
        intents.message_content = True
        self.bot = commands.Bot(command_prefix='/', intents=intents)
        self.loop = None
        self._setup_events()
        self._setup_commands()

    def _is_allowed(self, ctx):
        return ctx.author.id in self.allowed_user_ids

    def _setup_events(self):
        @self.bot.event
        async def on_ready():
            logger.info(f"🤖 [Discord] 机器人已登录: {self.bot.user.name} (ID: {self.bot.user.id})")
            if self.channel_id:
                logger.info(f"📡 [Discord] 正在连接频道 ID: {self.channel_id}...")
                channel = self.bot.get_channel(self.channel_id)
                if not channel:
                    try:
                        channel = await self.bot.fetch_channel(self.channel_id)
                    except Exception as e:
                        logger.error(f"❌ [Discord] fetch_channel 失败: {e}")
                
                if channel:
                    logger.info(f"✅ [Discord] 找到频道: {channel.name}，正在发送上线通知...")
                    try:
                        await channel.send(f"✅ **交易助手已上线**\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                    except Exception as e:
                        logger.error(f"❌ [Discord] 上线通知发送失败: {e}")
                else:
                    logger.error(f"❌ [Discord] 无法找到频道 ID: {self.channel_id}")

    def _setup_commands(self):
        @self.bot.command(name='status')
        async def status(ctx):
            if not self._is_allowed(ctx): return
            if self.controller:
                # 简单状态获取，后续根据 controller 实际方法完善
                await ctx.send("📊 **当前状态**: 正在运行\n(具体盈亏数据待集成)")
            else:
                await ctx.send("❌ 未连接到交易控制器")

        @self.bot.command(name='pause')
        async def pause(ctx):
            if not self._is_allowed(ctx): return
            if self.controller:
                self.controller.toggle_pause(True)
                await ctx.send("⏸️ **自动化扫描已暂停**")
            else:
                await ctx.send("❌ 未连接到交易控制器")

        @self.bot.command(name='resume')
        async def resume(ctx):
            if not self._is_allowed(ctx): return
            if self.controller:
                self.controller.toggle_pause(False)
                await ctx.send("▶️ **自动化扫描已恢复**")
            else:
                await ctx.send("❌ 未连接到交易控制器")

        @self.bot.command(name='liquidate')
        async def liquidate(ctx):
            if not self._is_allowed(ctx): return
            if self.controller:
                # 先询问确认
                await ctx.send(
                    "⚠️ **确认清仓所有持仓？**\n"
                    "请在 30 秒内回复 `yes` 确认，或者无视此消息取消。"
                )
                def check(m):
                    return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content.lower() == 'yes'
                try:
                    await self.bot.wait_for('message', check=check, timeout=30.0)
                    await ctx.send("🚀 **正在执行一键清仓...**")
                    try:
                        if hasattr(self.controller, 'close_all_positions'):
                            self.controller.close_all_positions()
                            await ctx.send("✅ **一键清仓指令已下发，请查看 GUI 日志。**")
                    except Exception as e:
                        await ctx.send(f"❌ 执行失败: {str(e)}")
                except asyncio.TimeoutError:
                    await ctx.send("⏰ 超时取消，未执行清仓操作。")
            else:
                await ctx.send("❌ 未连接到交易控制器")

        @self.bot.command(name='buy')
        async def buy(ctx, code: Optional[str] = None, qty: Optional[int] = None):
            """买入指定股票: /buy <股票代码> <数量>  例: /buy 09988 1000"""
            if not self._is_allowed(ctx): return
            if not self.controller:
                await ctx.send("❌ 未连接到交易控制器")
                return
            if not code or qty is None or qty <= 0:
                await ctx.send(
                    "❓ **使用方法**: `/buy <股票代码> <数量>`\n"
                    "例: `/buy 09988 1000` 或 `/buy HK.09988 1000`"
                )
                return

            clean_code = code.upper().replace('HK.', '')
            full_code = f"HK.{clean_code}"

            # 先查询最新价格给用户确认
            await ctx.send(f"🔍 正在查询 {full_code} 最新价格...")
            info = self.controller.get_stock_info(full_code)
            if not info or info.get('current_price', 0) <= 0:
                await ctx.send(f"❌ 无法获取 {full_code} 的实时报价，请检查股票代码是否正确。")
                return

            price = info['current_price']
            lot_size = info.get('lot_size', 100)
            estimated_cost = price * qty

            await ctx.send(
                f"📊 **买入确认**\n"
                f"▸ 股票: `{full_code}`\n"
                f"▸ 数量: `{qty}` 股  (最小单位: {lot_size} 股)\n"
                f"▸ 参考价: `{price:.3f}` HKD\n"
                f"▸ 预估金额: `{estimated_cost:,.2f}` HKD\n\n"
                f"⚠️ 请在 **30 秒**内回复 `yes` 确认，或无视此消息取消。"
            )

            def check(m):
                return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content.lower() == 'yes'
            try:
                await self.bot.wait_for('message', check=check, timeout=30.0)
                await ctx.send(f"🚀 **正在提交买入订单: {full_code} × {qty} 股...**")
                result = self.controller.manual_trade(full_code, 'BUY', qty)
                await ctx.send(result['message'])
            except asyncio.TimeoutError:
                await ctx.send("⏰ 超时取消，**未**执行买入操作。")

        @self.bot.command(name='sell')
        async def sell(ctx, code: Optional[str] = None, qty: Optional[int] = None):
            """卖出指定股票: /sell <股票代码> <数量>  例: /sell 09988 1000"""
            if not self._is_allowed(ctx): return
            if not self.controller:
                await ctx.send("❌ 未连接到交易控制器")
                return
            if not code or qty is None or qty <= 0:
                await ctx.send(
                    "❓ **使用方法**: `/sell <股票代码> <数量>`\n"
                    "例: `/sell 09988 1000` 或 `/sell HK.09988 1000`"
                )
                return

            clean_code = code.upper().replace('HK.', '')
            full_code = f"HK.{clean_code}"

            await ctx.send(f"🔍 正在查询 {full_code} 最新价格...")
            info = self.controller.get_stock_info(full_code)
            if not info or info.get('current_price', 0) <= 0:
                await ctx.send(f"❌ 无法获取 {full_code} 的实时报价，请检查股票代码是否正确。")
                return

            price = info['current_price']
            lot_size = info.get('lot_size', 100)
            estimated_proceeds = price * qty

            await ctx.send(
                f"📊 **卖出确认**\n"
                f"▸ 股票: `{full_code}`\n"
                f"▸ 数量: `{qty}` 股  (最小单位: {lot_size} 股)\n"
                f"▸ 参考价: `{price:.3f}` HKD\n"
                f"▸ 预计回款: `{estimated_proceeds:,.2f}` HKD\n\n"
                f"⚠️ 请在 **30 秒**内回复 `yes` 确认，或无视此消息取消。"
            )

            def check(m):
                return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content.lower() == 'yes'
            try:
                await self.bot.wait_for('message', check=check, timeout=30.0)
                await ctx.send(f"🚀 **正在提交卖出订单: {full_code} × {qty} 股...**")
                result = self.controller.manual_trade(full_code, 'SELL', qty)
                await ctx.send(result['message'])
            except asyncio.TimeoutError:
                await ctx.send("⏰ 超时取消，**未**执行卖出操作。")

    async def send_notification(self, message: str, chart_path: str = None):
        """推送通知和图表到指定频道"""
        if not self.token or not self.channel_id:
            return

        try:
            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                channel = await self.bot.fetch_channel(self.channel_id)
            
            if channel:
                if chart_path and os.path.exists(chart_path):
                    file = discord.File(chart_path)
                    await channel.send(content=message, file=file)
                else:
                    await channel.send(content=message)
            else:
                logger.error(f"❌ [Discord] send_notification: 找不到频道 {self.channel_id}")
        except Exception as e:
            logger.error(f"Discord notification failed: {e}")

    def start(self):
        """在独立后台线程中启动机器人"""
        if not self.token:
            logger.warning("Discord Token not provided, Bot will not start.")
            return

        def _run_bot():
            # 为该线程创建独立的事件循环
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            logger.info("📡 [Discord] 机器人独立线程已启动")
            try:
                self.loop.run_until_complete(self.bot.start(self.token))
            except Exception as e:
                logger.error(f"❌ [Discord] 机器人线程异常崩溃: {e}")

        self.thread = threading.Thread(target=_run_bot, name="DiscordBotThread", daemon=True)
        self.thread.start()
        print(f"✅ [Discord] 机器人后台线程已启动")
        
    async def stop(self):
        await self.bot.close()
