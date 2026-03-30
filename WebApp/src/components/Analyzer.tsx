"use client";

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, Cpu, Clock, RefreshCw, AlertCircle, BarChart3, X } from 'lucide-react';

interface AnalysisResult {
    success: boolean;
    symbol: string;
    lv: string;
    url: string;
    metrics?: {
        calculation_s: number;
        plotting_s: number;
        total_s: number;
    };
}

export default function Analyzer() {
    const [symbol, setSymbol] = useState('');
    const [timeframe, setTimeframe] = useState('30M');
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState<AnalysisResult | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [isExpanded, setIsExpanded] = useState(false);

    const handleAnalyze = async () => {
        if (!symbol) return;
        
        setLoading(true);
        setError(null);
        try {
            const res = await fetch(`http://localhost:8000/api/analyze/${symbol}?lv=${timeframe}`);
            const data = await res.json();
            
            if (data.success) {
                setResult(data);
            } else {
                setError(data.error || '分析失败');
            }
        } catch {
            setError('无法连接后端服务');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="min-h-full pb-20 px-6">
            {/* Header Control Panel - Now scrolls with page */}
            <div className="glass-pro rounded-[32px] p-6 border-white/[0.05] mb-8">
                <div className="flex items-center justify-between mb-6">
                    <div className="flex flex-col gap-1">
                        <h2 className="text-[18px] font-black italic uppercase tracking-tighter text-white flex items-center gap-3">
                            <BarChart3 size={20} className="text-indigo-400" />
                            策略分析中心
                        </h2>
                        <p className="text-[9px] font-black uppercase tracking-[0.2em] text-slate-500">回测报告 / 模拟指标 / 优势分析</p>
                    </div>
                    {result && (
                         <div className="flex items-center gap-4 text-[10px] font-black uppercase tracking-widest text-indigo-400/60 bg-indigo-500/5 px-4 py-2 rounded-full border border-indigo-500/10">
                            <div className="w-2 h-2 rounded-full bg-indigo-500 animate-pulse" />
                            {result.symbol} • {result.lv}
                         </div>
                    )}
                </div>
                
                <div className="flex items-center gap-4">
                    <div className="relative group flex-1">
                        <Search className="absolute left-5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-600 group-focus-within:text-indigo-500 transition-colors" />
                        <input 
                            type="text" 
                            placeholder="输入代码搜索（如 HK.00700）..."
                            className="bg-[#050507] border border-white/[0.05] rounded-xl pl-14 pr-6 py-4 text-[13px] font-bold text-white placeholder:text-slate-800 focus:outline-none focus:border-indigo-500/30 w-full transition-all"
                            value={symbol}
                            onChange={(e) => setSymbol(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && handleAnalyze()}
                        />
                    </div>

                    <div className="relative">
                        <select 
                            className="bg-[#050507] border border-white/[0.05] rounded-xl pl-6 pr-12 py-4 text-[13px] font-black text-slate-400 focus:outline-none focus:border-indigo-500/30 transition-all appearance-none cursor-pointer uppercase tracking-widest"
                            value={timeframe}
                            onChange={(e) => setTimeframe(e.target.value)}
                        >
                            <option value="5M">5分钟</option>
                            <option value="30M">30分钟</option>
                            <option value="DAY">日线</option>
                        </select>
                        <Clock className="absolute right-5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-600 pointer-events-none" />
                    </div>

                    <button 
                        onClick={handleAnalyze}
                        disabled={loading || !symbol}
                        className="bg-indigo-500 hover:bg-indigo-600 disabled:bg-slate-900 disabled:text-slate-700 text-white font-black py-4 px-10 rounded-xl transition-all flex items-center gap-3 uppercase text-[11px] tracking-widest shadow-[0_0_20px_rgba(99,102,241,0.2)]"
                    >
                        {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Cpu className="w-4 h-4" />}
                        {loading ? '分析中' : '开始分析'}
                    </button>
                </div>
            </div>

            {/* Content Display - Dynamic Height */}
            <div className="relative">
                <AnimatePresence mode="wait">
                    {error && (
                        <motion.div 
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            className="bg-rose-500/5 border border-rose-500/10 p-10 rounded-3xl flex flex-col gap-6"
                        >
                             <div className="flex items-center gap-4 text-rose-500">
                                <AlertCircle size={24} />
                                <span className="text-[14px] font-black uppercase tracking-widest">{error}</span>
                             </div>
                             <p className="text-slate-600 text-[12px] font-bold">分析引擎无法解析当前标的结构，请检查代码格式是否正确，或确认后端与数据源连接状态。</p>
                        </motion.div>
                    )}

                    {!result && !loading && !error && (
                        <motion.div className="border-2 border-dashed border-white/[0.03] rounded-[40px] flex flex-col items-center justify-center opacity-20 py-40">
                            <BarChart3 size={64} className="text-slate-700 mb-8" />
                            <p className="text-[12px] font-black uppercase tracking-[0.4em] text-slate-600">等待输入标的后开始分析</p>
                        </motion.div>
                    )}

                    {loading && (
                        <motion.div className="flex flex-col items-center justify-center gap-10 py-40 grayscale opacity-50">
                             <div className="w-12 h-12 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
                             <p className="text-[10px] font-black uppercase tracking-[0.3em] text-indigo-400 animate-pulse">正在构建分析图谱...</p>
                        </motion.div>
                    )}

                    {result && !loading && (
                        <motion.div 
                            initial={{ opacity: 0, scale: 0.99 }}
                            animate={{ opacity: 1, scale: 1 }}
                            className="flex flex-col gap-10"
                        >
                            {/* Analytics Detail Card */}
                            {result.metrics && (
                                <div className="grid grid-cols-3 gap-6">
                                    <div className="glass-pro rounded-2xl p-6 border-white/[0.03] flex flex-col gap-2">
                                        <span className="text-[9px] font-black text-slate-600 tracking-[0.2em] uppercase">计算耗时</span>
                                        <span className="text-white font-mono font-black text-lg">{result.metrics.calculation_s}s</span>
                                    </div>
                                    <div className="glass-pro rounded-2xl p-6 border-white/[0.03] flex flex-col gap-2">
                                        <span className="text-[9px] font-black text-slate-600 tracking-[0.2em] uppercase">绘图耗时</span>
                                        <span className="text-white font-mono font-black text-lg">{result.metrics.plotting_s}s</span>
                                    </div>
                                    <div className="glass-pro rounded-2xl p-6 border-white/[0.03] flex flex-col gap-2 relative group overflow-hidden">
                                        <div className="absolute top-0 right-0 p-2 opacity-50"><BarChart3 size={12} /></div>
                                        <span className="text-[9px] font-black text-indigo-400/80 tracking-[0.2em] uppercase">总耗时</span>
                                        <span className="text-indigo-400 font-mono font-black text-lg">{result.metrics.total_s}s</span>
                                    </div>
                                </div>
                            )}

                            {/* Main Chart Card - No height clipping */}
                            <div className="bg-[#0a0a0c] p-10 rounded-[48px] border border-white/[0.05] group relative shadow-2xl transition-all duration-500 hover:border-indigo-500/20">
                                <div className="absolute inset-x-0 top-0 h-40 bg-gradient-to-b from-black/20 to-transparent pointer-events-none z-10 rounded-t-[48px]" />
                                <div className="absolute inset-0 bg-indigo-500/[0.01] pointer-events-none rounded-[48px]" />
                                
                                <img 
                                    src={`http://localhost:8000${result.url}?t=${Date.now()}`} 
                                    alt="缠论分析图"
                                    className="w-full h-auto rounded-[32px] shadow-3xl"
                                />

                                <div className="mt-12 flex items-center justify-between opacity-50 border-t border-white/[0.05] pt-8">
                                     <p className="text-[9px] font-black uppercase tracking-[0.5em] text-slate-600">多周期结构映射管线 v2.4.0</p>
                                     <button 
                                        onClick={() => setIsExpanded(true)}
                                        className="text-[10px] font-black text-indigo-400 uppercase tracking-widest hover:text-white transition-colors"
                                     >
                                         [ 全屏查看 ]
                                     </button>
                                </div>
                            </div>
                        </motion.div>
                    )}
                </AnimatePresence>
            </div>

            {/* KEEP MODAL AS OPTIONAL BACKUP */}
            <AnimatePresence>
                {isExpanded && result && (
                    <motion.div 
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 z-[1000] bg-black/98 backdrop-blur-3xl flex flex-col p-10"
                    >
                        <div className="flex items-center justify-between mb-8 opacity-80">
                            <div className="flex items-center gap-8">
                                <div className="flex flex-col gap-1">
                                    <span className="text-label text-slate-400">高清查看模式</span>
                                    <span className="text-white font-black text-2xl tracking-tighter uppercase italic">{result.symbol} • {result.lv}</span>
                                </div>
                            </div>
                            <button 
                                onClick={() => setIsExpanded(false)}
                                className="w-16 h-16 bg-white/5 hover:bg-rose-500 text-white rounded-2xl flex items-center justify-center transition-all group"
                            >
                                <X className="w-8 h-8 group-hover:scale-110 transition-transform" />
                            </button>
                        </div>
                        
                        <div className="flex-1 overflow-y-auto custom-scrollbar flex flex-col items-center p-10 bg-slate-900/30 rounded-[64px] border border-white/[0.03]">
                            <img 
                                src={`http://localhost:8000${result.url}?t=${Date.now()}`} 
                                alt="全屏缠论分析图"
                                className="w-full h-auto shadow-[0_40px_100px_rgba(0,0,0,0.8)] rounded-2xl border border-white/[0.05]"
                            />
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}
