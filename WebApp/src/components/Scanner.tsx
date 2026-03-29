"use client";

import React, { useState, useEffect } from 'react';
import { 
  ShieldCheck, 
  Search,
  Activity,
  AlertCircle,
  BrainCircuit,
  Eye
} from 'lucide-react';
import { motion } from 'framer-motion';

export default function Scanner() {
  const [signals, setSignals] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');

  useEffect(() => {
    const fetchSignals = async () => {
      try {
        const res = await fetch('http://localhost:8000/api/signals');
        const data = await res.json();
        setSignals(data.signals || []);
      } catch (e) {
        console.error("Fetch signals failed", e);
      } finally {
        setLoading(false);
      }
    };
    fetchSignals();
    const interval = setInterval(fetchSignals, 10000); // 10s refresh
    return () => clearInterval(interval);
  }, []);

  const filteredSignals = signals.filter(s => 
    s.stock_code.toLowerCase().includes(filter.toLowerCase()) ||
    s.bstype.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <div className="h-full glass-pro rounded-[32px] p-12 flex flex-col overflow-hidden">
      <div className="flex items-center justify-between mb-10 border-b border-white/5 pb-10">
        <div className="flex flex-col gap-3">
            <h2 className="text-header italic uppercase flex items-center gap-5">
                <Activity size={28} className="text-emerald-500" />
                全市场 Alpha 信号监控流水线
            </h2>
            <p className="text-label tracking-[0.2em] font-black opacity-60">实时市场扫描 / Gemini 视觉验证 / 深度学习重排</p>
        </div>
        
        <div className="relative w-80 group">
            <Search className="absolute left-5 top-1/2 -translate-y-1/2 text-slate-500 group-focus-within:text-emerald-400 transition-colors" size={18} />
            <input 
                type="text" 
                placeholder="搜索代码或信号类型..."
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                className="w-full bg-slate-900 border border-white/5 rounded-2xl py-4 pl-14 pr-6 text-sm font-bold text-slate-200 placeholder:text-slate-700 focus:outline-none focus:border-emerald-500/50 focus:bg-emerald-500/5 transition-all shadow-inner"
            />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto terminal-scroll pr-4">
        {loading ? (
            <div className="flex flex-col items-center justify-center h-80 gap-6">
                <div className="w-10 h-10 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin shadow-[0_0_15px_rgba(16,185,129,0.2)]" />
                <p className="text-label text-slate-600">正在检索实时 Alpha 数据库...</p>
            </div>
        ) : filteredSignals.length > 0 ? (
            <table className="w-full text-left border-separate border-spacing-y-2">
                <thead className="text-label">
                    <tr>
                        <th className="px-6 py-2">触发时间</th>
                        <th className="px-6 py-2">证券代码</th>
                        <th className="px-6 py-2 text-center">级别</th>
                        <th className="px-6 py-2 text-center">信号</th>
                        <th className="px-6 py-2 text-right">触发价格</th>
                        <th className="px-6 py-2 text-center">评分矩阵 (Visual/ML)</th>
                        <th className="px-6 py-2 text-center">验证状态</th>
                    </tr>
                </thead>
                <tbody>
                    {filteredSignals.map((signal: any, i: number) => {
                        const isBuy = !signal.bstype.startsWith('S');
                        let mlScore = signal.ml_score ?? signal.ml_prob ?? 0;
                        if (mlScore <= 1.0 && mlScore > 0) mlScore = Math.round(mlScore * 100);
                        const visualScore = Math.round(signal.model_score_before ?? signal.visual_score ?? 0);
                        
                        return (
                            <motion.tr 
                                initial={{ opacity: 0, y: 10 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ delay: i * 0.05 }}
                                key={i} 
                                className="group hover:bg-white/[0.03] transition-all rounded-3xl"
                            >
                                <td className="px-6 py-3 bg-white/[0.015] rounded-l-[16px] border-y border-l border-white/5 text-[11px] font-mono text-slate-500">
                                    {signal.add_date}
                                </td>
                                <td className="px-6 py-3 bg-white/[0.015] border-y border-white/5 font-black text-white text-[14px] font-mono tracking-tight">
                                    {signal.stock_code}
                                </td>
                                <td className="px-6 py-3 bg-white/[0.015] border-y border-white/5 text-center">
                                    <span className="px-3 py-1 bg-slate-900 border border-white/10 text-slate-300 text-[10px] font-black rounded-lg uppercase tracking-wider">
                                        {signal.lv || '30M'}
                                    </span>
                                </td>
                                <td className="px-6 py-3 bg-white/[0.015] border-y border-white/5 text-center">
                                    <span className={`px-4 py-1.5 rounded-xl text-[10px] font-black tracking-[0.2em] leading-none ${isBuy ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'}`}>
                                        {signal.bstype}
                                    </span>
                                </td>
                                <td className="px-6 py-3 bg-white/[0.015] border-y border-white/5 text-right font-mono text-slate-300 font-bold text-[13px]">
                                    ¥{signal.open_price?.toFixed(2) || '0.00'}
                                </td>
                                <td className="px-6 py-3 bg-white/[0.015] border-y border-white/5 text-center">
                                    <div className="flex items-center gap-4 justify-center">
                                        <div className="flex flex-col items-center gap-1">
                                            <div className="flex items-center gap-2">
                                                <Eye size={10} className={visualScore >= 80 ? 'text-emerald-400' : 'text-slate-500'} />
                                                <span className={`text-[12px] font-mono font-black ${visualScore >= 80 ? 'text-emerald-400' : 'text-slate-200'}`}>{visualScore}</span>
                                            </div>
                                            <span className="text-[8px] font-black text-slate-600 uppercase tracking-widest">视觉</span>
                                            <div className="w-14 h-1 bg-slate-950 rounded-full overflow-hidden">
                                                <div className={`h-full ${visualScore >= 80 ? 'bg-emerald-500' : visualScore >= 60 ? 'bg-blue-500' : 'bg-slate-700'}`} style={{ width: `${visualScore}%` }} />
                                            </div>
                                        </div>
                                        <div className="flex flex-col items-center gap-1">
                                            <div className="flex items-center gap-2">
                                                <BrainCircuit size={10} className={mlScore >= 80 ? 'text-emerald-400' : 'text-slate-500'} />
                                                <span className={`text-[12px] font-mono font-black ${mlScore >= 80 ? 'text-emerald-400' : 'text-slate-200'}`}>{mlScore}</span>
                                            </div>
                                            <span className="text-[8px] font-black text-slate-600 uppercase tracking-widest">ML</span>
                                            <div className="w-14 h-1 bg-slate-950 rounded-full overflow-hidden">
                                                <div className={`h-full ${mlScore >= 80 ? 'bg-emerald-500' : mlScore >= 60 ? 'bg-blue-500' : 'bg-slate-700'}`} style={{ width: `${mlScore}%` }} />
                                            </div>
                                        </div>
                                    </div>
                                </td>
                                <td className="px-6 py-3 bg-white/[0.015] rounded-r-[16px] border-y border-r border-white/5 text-center">
                                    <span className="text-[10px] font-black text-slate-500 uppercase italic opacity-60 tracking-[0.2em]">
                                        {signal.status === 'active' ? '待命' : signal.status === 'executed' ? '已入' : '通过'}
                                    </span>
                                </td>
                            </motion.tr>
                        );
                    })}
                </tbody>
            </table>
        ) : (
            <div className="flex flex-col items-center justify-center py-40 gap-8 text-slate-700 bg-white/[0.01] rounded-[32px] border border-dashed border-white/5">
                <AlertCircle size={56} className="text-slate-800" />
                <div className="text-center">
                    <p className="text-sm font-black uppercase tracking-[0.3em] text-slate-600">暂无目标买卖信号</p>
                </div>
            </div>
        )}
      </div>
    </div>
  );
}
