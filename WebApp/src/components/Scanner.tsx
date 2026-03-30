"use client";

import React, { useState, useEffect } from 'react';
import { 
  Search,
  Activity,
  AlertCircle,
  BrainCircuit,
  Eye
} from 'lucide-react';
import { motion } from 'framer-motion';

interface Signal {
  unique_key?: string;
  stock_code?: string;
  bstype?: string;
  add_date?: string;
  lv?: string;
  open_price?: number;
  ml_score?: number;
  ml_prob?: number;
  model_score_before?: number;
  visual_score?: number;
  status?: string;
}

export default function Scanner() {
  const [signals, setSignals] = useState<Signal[]>([]);
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

  // 🔥 [Phase 12] 过滤掉缺少关键字段的信号，防止渲染崩溃
  const validSignals = signals.filter(s => s.stock_code && s.bstype);
  const filteredSignals = validSignals.filter(s => 
    (s.stock_code && s.stock_code.toLowerCase().includes(filter.toLowerCase())) ||
    (s.bstype && s.bstype.toLowerCase().includes(filter.toLowerCase()))
  );

  return (
    <div className="h-full glass-pro rounded-[32px] p-10 flex flex-col overflow-hidden relative">
      <div className="flex items-center justify-between mb-8 border-b border-white/[0.05] pb-8">
        <div className="flex flex-col gap-2">
            <h2 className="text-[20px] font-black italic uppercase tracking-tighter text-white flex items-center gap-4">
                <Activity size={24} className="text-emerald-500" />
                信号扫描总线
            </h2>
            <p className="text-[10px] font-black uppercase tracking-[0.2em] text-slate-500">跨市场实时扫描 / 智能评分排序</p>
        </div>
        
        <div className="relative w-72 group">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-600 group-focus-within:text-emerald-500 transition-colors" size={16} />
            <input 
                type="text" 
                placeholder="筛选信号..."
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                className="w-full bg-[#050507] border border-white/[0.05] rounded-xl py-3 pl-12 pr-4 text-[13px] font-bold text-slate-200 placeholder:text-slate-800 focus:outline-none focus:border-emerald-500/30 focus:shadow-[0_0_20px_rgba(16,185,129,0.05)] transition-all"
            />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto custom-scrollbar pr-2">
        {loading ? (
            <div className="flex flex-col items-center justify-center h-80 gap-6 grayscale opacity-50">
                <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin shadow-[0_0_15px_rgba(16,185,129,0.1)]" />
                <p className="text-[10px] font-black uppercase tracking-widest text-slate-500">正在索引信号流...</p>
            </div>
        ) : filteredSignals.length > 0 ? (
            <table className="w-full text-left border-separate border-spacing-y-1.5">
                <thead className="text-label opacity-40">
                    <tr>
                        <th className="px-6 py-2">时间</th>
                        <th className="px-6 py-2">标的</th>
                        <th className="px-6 py-2 text-center">周期</th>
                        <th className="px-6 py-2 text-center">信号类型</th>
                        <th className="px-6 py-2 text-right">价格</th>
                        <th className="px-6 py-2 text-center">评分矩阵</th>
                        <th className="px-6 py-2 text-center">状态</th>
                    </tr>
                </thead>
                <tbody>
                    {filteredSignals.map((signal, i: number) => {
                        const bstype = signal.bstype || '未知';
                        const isBuy = !bstype.startsWith('S') && !bstype.startsWith('s');
                        let mlScore = signal.ml_score ?? signal.ml_prob ?? 0;
                        if (mlScore <= 1.0 && mlScore > 0) mlScore = Math.round(mlScore * 100);
                        const visualScore = Math.round(signal.visual_score ?? signal.model_score_before ?? 0);
                        const priceLabel = typeof signal.open_price === 'number' && signal.open_price > 0
                          ? `¥${signal.open_price.toFixed(2)}`
                          : '--';
                        
                        return (
                            <motion.tr 
                                initial={{ opacity: 0, y: 5 }}
                                animate={{ opacity: 1, y: 0 }}
                                transition={{ delay: i * 0.03 }}
                                key={signal.unique_key || `${signal.stock_code}-${signal.add_date}-${signal.bstype}-${i}`}
                                className="group hover:bg-white/[0.03] transition-all"
                            >
                                <td className="px-6 py-4 bg-white/[0.015] rounded-l-xl border-y border-l border-white/[0.05] text-[11px] font-mono text-slate-600">
                                    {signal.add_date}
                                </td>
                                <td className="px-6 py-4 bg-white/[0.015] border-y border-white/[0.05] font-black text-white text-[14px] font-mono tracking-tight">
                                    {signal.stock_code}
                                </td>
                                <td className="px-6 py-4 bg-white/[0.015] border-y border-white/[0.05] text-center">
                                    <span className="px-2.5 py-1 bg-[#050507] border border-white/[0.05] text-slate-400 text-[10px] font-black rounded-lg uppercase">
                                        {signal.lv || '30M'}
                                    </span>
                                </td>
                                <td className="px-6 py-4 bg-white/[0.015] border-y border-white/[0.05] text-center">
                                    <span className={`px-4 py-1.5 rounded-lg text-[10px] font-black tracking-widest ${isBuy ? 'bg-emerald-500/10 text-emerald-500 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-500 border border-rose-500/20'}`}>
                                        {bstype}
                                    </span>
                                </td>
                                <td className="px-6 py-4 bg-white/[0.015] border-y border-white/[0.05] text-right font-mono text-slate-300 font-bold text-[13px]">
                                    {priceLabel}
                                </td>
                                <td className="px-6 py-4 bg-white/[0.015] border-y border-white/[0.05] text-center">
                                    <div className="flex items-center gap-6 justify-center">
                                        <div className="flex flex-col items-center gap-1.5">
                                            <div className="flex items-center gap-1.5">
                                                <Eye size={10} className={visualScore >= 80 ? 'text-emerald-500' : 'text-slate-600'} />
                                                <span className={`text-[11px] font-mono font-black ${visualScore >= 80 ? 'text-emerald-500' : 'text-slate-400'}`}>{visualScore}</span>
                                            </div>
                                            <div className="w-12 h-1 bg-[#050507] rounded-full overflow-hidden border border-white/[0.03]">
                                                <div className={`h-full ${visualScore >= 80 ? 'bg-emerald-500' : visualScore >= 60 ? 'bg-indigo-500' : 'bg-slate-800'}`} style={{ width: `${visualScore}%` }} />
                                            </div>
                                        </div>
                                        <div className="flex flex-col items-center gap-1.5">
                                            <div className="flex items-center gap-1.5">
                                                <BrainCircuit size={10} className={mlScore >= 80 ? 'text-emerald-500' : 'text-slate-600'} />
                                                <span className={`text-[11px] font-mono font-black ${mlScore >= 80 ? 'text-emerald-500' : 'text-slate-400'}`}>{mlScore}</span>
                                            </div>
                                            <div className="w-12 h-1 bg-[#050507] rounded-full overflow-hidden border border-white/[0.03]">
                                                <div className={`h-full ${mlScore >= 80 ? 'bg-emerald-500' : mlScore >= 60 ? 'bg-indigo-500' : 'bg-slate-800'}`} style={{ width: `${mlScore}%` }} />
                                            </div>
                                        </div>
                                    </div>
                                </td>
                                <td className="px-6 py-4 bg-white/[0.015] rounded-r-xl border-y border-r border-white/[0.05] text-center">
                                    <span className="text-[10px] font-black text-slate-600 uppercase italic opacity-60 tracking-[0.2em]">
                                        {signal.status === 'active' ? '推送中' : signal.status === 'executed' ? '已成交' : signal.status === 'pending' ? '待补全' : '已验证'}
                                    </span>
                                </td>
                            </motion.tr>
                        );
                    })}
                </tbody>
            </table>
        ) : (
            <div className="flex flex-col items-center justify-center py-40 gap-8 bg-white/[0.01] rounded-[32px] border border-dashed border-white/[0.05]">
                <AlertCircle size={48} className="text-slate-800" />
                <div className="text-center">
                    <p className="text-[12px] font-black uppercase tracking-[0.4em] text-slate-700">当前广播缓冲区没有活动信号</p>
                </div>
            </div>
        )}
      </div>
    </div>
  );
}
