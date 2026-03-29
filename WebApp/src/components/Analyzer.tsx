"use client";

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, LineChart, Cpu, Clock, Maximize2, RefreshCw, AlertCircle } from 'lucide-react';

export default function Analyzer() {
    const [symbol, setSymbol] = useState('');
    const [timeframe, setTimeframe] = useState('30M');
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState<any>(null);
    const [error, setError] = useState<string | null>(null);

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
                setError(data.error || '分析失败，请检查证券代码。');
            }
        } catch (err) {
            setError('无法连接到后端服务器。');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="flex flex-col gap-10">
            {/* Header Control Bar */}
            <div className="glass-pro rounded-[32px] p-10 flex flex-col xl:flex-row xl:items-center justify-between gap-8">
                <div className="flex items-center gap-6">
                    <div className="w-16 h-16 bg-emerald-500/10 rounded-[22px] flex items-center justify-center border border-emerald-500/20 shadow-inner">
                        <LineChart className="w-8 h-8 text-emerald-400" />
                    </div>
                    <div>
                        <h2 className="text-header uppercase italic">缠论深度策略分析 (Analyzer)</h2>
                        <p className="text-label tracking-[0.2em] font-black opacity-60">多级别几何结构映射与买卖点解析</p>
                    </div>
                </div>

                <div className="flex flex-wrap items-center gap-5">
                    {/* Symbol Search */}
                    <div className="relative group flex-1 min-w-[320px]">
                        <Search className="absolute left-5 top-1/2 -translate-y-1/2 w-5 h-5 text-slate-500 group-focus-within:text-emerald-400 transition-colors" />
                        <input 
                            type="text" 
                            placeholder="输入证券代码 (如 HK.00700)"
                            className="bg-slate-900 border border-white/5 rounded-2xl pl-14 pr-6 py-4 text-sm font-bold text-white placeholder:text-slate-700 focus:outline-none focus:ring-2 focus:ring-emerald-500/20 focus:border-emerald-500/40 w-full transition-all"
                            value={symbol}
                            onChange={(e) => setSymbol(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && handleAnalyze()}
                        />
                    </div>

                    {/* Timeframe Selector */}
                    <div className="relative">
                        <select 
                            className="bg-slate-900 border border-white/5 rounded-2xl pl-6 pr-12 py-4 text-sm font-black text-white focus:outline-none focus:ring-2 focus:ring-emerald-500/20 transition-all appearance-none cursor-pointer uppercase tracking-widest"
                            value={timeframe}
                            onChange={(e) => setTimeframe(e.target.value)}
                        >
                            <option value="5M" className="bg-slate-950 px-4 py-2">5分钟 (5M)</option>
                            <option value="30M" className="bg-slate-950 px-4 py-2">30分钟 (30M)</option>
                            <option value="DAY" className="bg-slate-950 px-4 py-2">日线 (DAY)</option>
                        </select>
                        <Clock className="absolute right-5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-600 pointer-events-none" />
                    </div>

                    <motion.button 
                        whileHover={{ scale: 1.02, backgroundColor: '#10b981' }}
                        whileTap={{ scale: 0.98 }}
                        onClick={handleAnalyze}
                        disabled={loading || !symbol}
                        className="bg-emerald-500/90 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-600 text-black font-black py-4 px-10 rounded-2xl transition-all flex items-center gap-3 uppercase text-xs tracking-widest shadow-xl"
                    >
                        {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Cpu className="w-4 h-4" />}
                        {loading ? '正在处理' : '执行缠论分析'}
                    </motion.button>
                </div>
            </div>

            {/* Main Content Area */}
            <div className="flex-1">
                <AnimatePresence mode="wait">
                    {error && (
                        <motion.div 
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: -10 }}
                            className="bg-rose-500/5 border border-rose-500/20 p-8 rounded-3xl flex flex-col gap-4 text-rose-400"
                        >
                            <div className="flex items-center gap-4 text-sm font-black uppercase tracking-wider">
                                <AlertCircle className="w-6 h-6 flex-shrink-0" />
                                {error}
                            </div>
                            {result?.traceback && (
                                <pre className="mt-4 p-6 bg-black/40 rounded-2xl text-[11px] font-mono overflow-x-auto border border-rose-500/10 text-rose-300/60 leading-relaxed max-h-[400px]">
                                    {result.traceback}
                                </pre>
                            )}
                        </motion.div>
                    )}

                    {!result && !loading && !error && (
                        <motion.div 
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            className="min-h-[600px] border-2 border-dashed border-white/5 rounded-[3rem] flex flex-col items-center justify-center text-slate-700 gap-6 opacity-40"
                        >
                            <div className="w-24 h-24 bg-white/[0.02] rounded-full flex items-center justify-center border border-white/5">
                                <Search className="w-10 h-10 opacity-20" />
                            </div>
                            <div className="text-center">
                                <p className="text-sm font-black uppercase tracking-[0.4em]">输入证券标识符以开始</p>
                                <p className="text-[11px] mt-2 font-bold uppercase italic tracking-widest leading-loose">支持 港股 / 美股 / A股 多数据源实时解析</p>
                            </div>
                        </motion.div>
                    )}

                    {loading && (
                        <motion.div 
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            className="min-h-[600px] glass-pro rounded-[3rem] flex flex-col items-center justify-center gap-10"
                        >
                            <div className="relative">
                                <div className="w-24 h-24 border-[6px] border-emerald-500/10 border-t-emerald-500 rounded-full animate-spin shadow-[0_0_30px_rgba(16,185,129,0.1)]" />
                                <div className="absolute inset-0 flex items-center justify-center">
                                    <div className="w-12 h-12 bg-emerald-500/20 rounded-full blur-2xl animate-pulse" />
                                </div>
                            </div>
                            <div className="text-center">
                                <p className="text-white font-black tracking-[0.3em] text-sm uppercase animate-pulse">正在构建神经绘图结构...</p>
                                <p className="text-slate-600 text-[10px] mt-4 font-black uppercase tracking-widest italic font-mono flex items-center justify-center gap-3">
                                   <RefreshCw size={12} className="animate-spin" />
                                   正在抓取 L1 高级行情管道
                                </p>
                            </div>
                        </motion.div>
                    )}

                    {result && !loading && (
                        <motion.div 
                            initial={{ opacity: 0, scale: 0.98 }}
                            animate={{ opacity: 1, scale: 1 }}
                            className="flex flex-col gap-8"
                        >
                            {/* Analysis Information Bar */}
                            <div className="flex items-center justify-between px-10 py-6 glass-pro rounded-3xl">
                                <div className="flex items-center gap-10">
                                    <div className="flex flex-col gap-1">
                                        <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">证券焦点</span>
                                        <span className="text-white font-mono font-black text-lg uppercase tracking-tighter">{result.symbol}</span>
                                    </div>
                                    <div className="h-10 w-[1px] bg-white/5" />
                                    <div className="flex flex-col gap-1">
                                        <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">分析级别</span>
                                        <span className="px-3 py-0.5 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-[12px] font-black rounded-lg uppercase">{result.lv}</span>
                                    </div>
                                    <div className="h-10 w-[1px] bg-white/5" />
                                    <div className="flex flex-col gap-1">
                                        <span className="text-[10px] font-black uppercase tracking-widest text-slate-500">计算时间戳</span>
                                        <span className="text-slate-300 text-[12px] font-mono font-bold tracking-tight"> {new Date(result.timestamp).toLocaleString()}</span>
                                    </div>
                                </div>
                                <button className="w-10 h-10 bg-slate-900 hover:bg-emerald-500/10 border border-white/5 rounded-xl flex items-center justify-center transition-all group">
                                    <Maximize2 className="w-5 h-5 text-slate-500 group-hover:text-emerald-400" />
                                </button>
                            </div>

                            {/* Chart Viewer */}
                            <div className="relative group bg-slate-950 rounded-[3rem] overflow-hidden border border-white/5 p-6 shadow-2xl">
                                <img 
                                    src={`http://localhost:8000${result.url}?t=${Date.now()}`} 
                                    alt="Chanlun Strategy Map"
                                    className="w-full h-auto rounded-[2rem] shadow-2xl transition-all duration-1000 group-hover:scale-[1.01]"
                                />
                                <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-700" />
                            </div>
                        </motion.div>
                    )}
                </AnimatePresence>
            </div>
        </div>
    );
}
