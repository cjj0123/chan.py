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
                await ctx.send("⚠️ **接收到清仓指令，正在执行...**")
                # 触发 controller 的一键清仓
                try:
                    # 获取事件循环以执行异步任务（如果 controller 的方法是异步的）
                    if hasattr(self.controller, 'close_all_positions'):
                        self.controller.close_all_positions()
                        await ctx.send("✅ **一键清仓指令已下发**")
                except Exception as e:
                    await ctx.send(f"❌ 执行失败: {str(e)}")
            else:
                await ctx.send("❌ 未连接到交易控制器")

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
