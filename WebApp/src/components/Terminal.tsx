"use client";

import React, { useEffect, useRef, useState } from 'react';
import { Terminal as TerminalIcon, ShieldCheck, Activity, Cpu } from 'lucide-react';

interface LogEntry {
  source: string;
  message: string;
  timestamp: string;
  type?: 'info' | 'trade' | 'error' | 'warning';
}

export default function Terminal() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8000/ws/logs');
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'log') {
        const timestamp = new Date().toLocaleTimeString('zh-CN', { hour12: false });
        setLogs(prev => [...prev, {
          source: data.source === 'HK' ? '港股' : 'A股',
          message: data.message,
          timestamp: timestamp,
          type: determineLogType(data.message)
        }].slice(-300));
      }
    };
    return () => ws.close();
  }, []);

  useEffect(() => {
    if (scrollRef.current) {
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  const determineLogType = (msg: string): any => {
    if (msg.includes('成交') || msg.includes('买入') || msg.includes('卖出')) return 'trade';
    if (msg.includes('错误') || msg.includes('失败')) return 'error';
    if (msg.includes('警告') || msg.includes('提醒')) return 'warning';
    return 'info';
  };

  return (
    <div className="flex flex-col h-full bg-[#0d0d0f]/80 backdrop-blur-xl rounded-xl border border-white/10 overflow-hidden shadow-[0_20px_50px_rgba(0,0,0,0.5)]">
      <div className="flex items-center justify-between px-5 py-3 border-b border-white/5 bg-gradient-to-r from-[#161618] to-[#0d0d0f]">
        <div className="flex items-center gap-3">
          <div className="p-1.5 rounded-md bg-emerald-500/10 border border-emerald-500/20">
            <Cpu size={14} className="text-emerald-400" />
          </div>
          <span className="text-[11px] font-bold uppercase tracking-[0.2em] text-slate-300">实时交易控制台</span>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex gap-1.5">
            <div className="w-1.5 h-1.5 rounded-full bg-slate-800"></div>
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)] animate-pulse"></div>
          </div>
          <span className="text-[10px] text-emerald-500/70 font-mono tracking-tighter italic">SYS_LINK_STABLE</span>
        </div>
      </div>
      
      <div 
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-5 font-mono text-[13px] leading-relaxed terminal-scroll bg-[#080809]/50"
      >
        {logs.length === 0 && (
          <div className="text-slate-700 flex flex-col items-center justify-center h-full gap-4 opacity-40">
             <Activity size={32} className="animate-pulse text-emerald-500/20" />
             <div className="flex flex-col items-center">
                <p className="text-xs uppercase tracking-[0.3em] font-bold italic">等待指令流中...</p>
                <p className="text-[9px] mt-1 font-mono uppercase">Neural Engine Connection Established / Standby</p>
             </div>
          </div>
        )}
        {logs.map((log, i) => (
          <div key={i} className="mb-2 flex gap-4 group hover:bg-white/[0.02] transition-colors py-0.5 rounded px-2 -mx-2">
            <span className="text-slate-600 shrink-0 text-[10px] font-medium pt-1">[{log.timestamp}]</span>
            <div className={`shrink-0 flex items-center gap-1.5 w-12`}>
               <div className={`w-1 h-3 rounded-full ${log.source === '港股' ? 'bg-blue-500' : 'bg-orange-500'}`} />
               <span className={`font-bold text-[10px] ${log.source === '港股' ? 'text-blue-400' : 'text-orange-400'}`}>
                 {log.source}
               </span>
            </div>
            <span className={`flex-1 break-all tracking-tight ${
               log.type === 'trade' ? 'text-emerald-400 drop-shadow-[0_0_5px_rgba(52,211,153,0.3)]' : 
               log.type === 'error' ? 'text-rose-400' : 
               log.type === 'warning' ? 'text-amber-400' : 'text-slate-300'
            }`}>
              {log.message}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
