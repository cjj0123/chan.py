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
    let ws: WebSocket;

    // Fetch historical logs first
    fetch('http://localhost:8000/api/logs')
      .then(res => res.json())
      .then(data => {
        if (data.logs && Array.isArray(data.logs)) {
          const historicalLogs = data.logs.map((log: any) => ({
            source: log.source === 'HK' ? '港股' : 'A股',
            message: log.message,
            timestamp: log.time_str || new Date(log.timestamp * 1000).toLocaleTimeString('zh-CN', { hour12: false }),
            type: determineLogType(log.message)
          })).slice(-300);
          setLogs(historicalLogs);
        }

        // Start WebSocket after fetching historical logs
        ws = new WebSocket('ws://localhost:8000/ws/logs');
        ws.onmessage = (event) => {
          const wsData = JSON.parse(event.data);
          if (wsData.type === 'log') {
            const timestamp = wsData.time_str || new Date().toLocaleTimeString('zh-CN', { hour12: false });
            setLogs(prev => [...prev, {
              source: wsData.source === 'HK' ? '港股' : 'A股',
              message: wsData.message,
              timestamp: timestamp,
              type: determineLogType(wsData.message)
            }].slice(-300));
          }
        };
      })
      .catch(err => console.error("Failed to fetch historical logs:", err));

    return () => {
      if (ws) {
        ws.close();
      }
    };
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
    <div className="flex flex-col h-full bg-[#0a0a0c] rounded-2xl border border-white/[0.05] overflow-hidden shadow-2xl relative">
      <div className="scan-line-overlay pointer-events-none"></div>
      <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.05] bg-white/[0.02]">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
            <Cpu size={16} className="text-emerald-400" />
          </div>
          <span className="text-[11px] font-black uppercase tracking-[0.2em] text-white italic">Core Live Execution Shell</span>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 px-3 py-1 bg-emerald-500/5 rounded-full border border-emerald-500/10">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></div>
            <span className="text-[9px] text-emerald-500/80 font-mono font-bold">STREAM_STABLE</span>
          </div>
        </div>
      </div>
      
      <div 
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-6 font-mono text-[13px] leading-relaxed custom-scrollbar bg-[#050507]/30 selection:bg-emerald-500/20"
      >
        {logs.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-5 opacity-20 transition-opacity duration-1000 grayscale">
             <Activity size={48} className="animate-breath text-emerald-500" />
             <div className="flex flex-col items-center gap-2">
                <p className="text-[11px] font-black uppercase tracking-[0.4em] italic">Awaiting Signal Stream</p>
                <div className="flex items-center gap-2">
                   <div className="w-8 h-[1px] bg-emerald-500/30"></div>
                   <p className="text-[8px] font-mono uppercase tracking-widest">Connection: NOMINAL</p>
                   <div className="w-8 h-[1px] bg-emerald-500/30"></div>
                </div>
             </div>
          </div>
        )}
        {logs.map((log, i) => (
          <div key={i} className="mb-1.5 flex gap-5 group hover:bg-white/[0.02] transition-all py-1 rounded-lg px-3 -mx-3 border border-transparent hover:border-white/[0.03]">
            <span className="text-slate-600 shrink-0 text-[10px] font-bold font-mono pt-1">
              {log.timestamp}
            </span>
            <div className="shrink-0 flex items-center gap-2 w-14">
               <div className={`w-[2px] h-3 rounded-full ${log.source === '港股' ? 'bg-blue-500' : 'bg-orange-500'}`} />
               <span className={`font-black text-[9px] uppercase tracking-tighter ${log.source === '港股' ? 'text-blue-500' : 'text-orange-500'}`}>
                 {log.source === '港股' ? 'HK_MKT' : 'CN_MKT'}
               </span>
            </div>
            <span className={`flex-1 break-all tracking-tight font-medium ${
               log.type === 'trade' ? 'text-emerald-400 font-bold' : 
               log.type === 'error' ? 'text-rose-400 font-bold' : 
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
