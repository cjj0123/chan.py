"use client";

import React, { useState, useEffect } from 'react';
import { 
  BarChart3, 
  LayoutDashboard, 
  Activity, 
  Terminal as TerminalIcon, 
  Search, 
  Briefcase,
  Settings,
  Bell,
  User,
  ExternalLink,
  ChevronRight,
  RefreshCw,
  Globe,
  PieChart,
  Power,
  RotateCcw
} from 'lucide-react';
import Terminal from '../components/Terminal';
import Scanner from '../components/Scanner';
import Analyzer from '../components/Analyzer';
import { motion, AnimatePresence } from 'framer-motion';

export default function Dashboard() {
  const [activeNav, setActiveNav] = useState('终端概览');
  const [hkFunds, setHkFunds] = useState<any>({ available: 0, total: 0, positions: []});
  const [cnFunds, setCnFunds] = useState<any>({ available: 0, total: 0, positions: []});
  const [systemSummary, setSystemSummary] = useState<any>({ 
    daily_pnl: 0, 
    daily_pnl_pct: 0, 
    active_symbols: 0, 
    compute_load: 0, 
    risk_exposure: 'LOW' 
  });
  const [isRestarting, setIsRestarting] = useState(false);

  useEffect(() => {
    const fetchFunds = async () => {
      try {
        const res = await fetch('http://localhost:8000/api/portfolio');
        const data = await res.json();
        if (data.hk) setHkFunds(data.hk);
        if (data.cn) setCnFunds(data.cn);
      } catch (e) {
        console.error("Fetch portfolio failed", e);
      }
    };

    fetchFunds();
    const interval = setInterval(fetchFunds, 5000);

    const ws = new WebSocket('ws://localhost:8000/ws/logs');
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'status_update') {
        if (data.update_type === 'HK_FUNDS') setHkFunds(data.data);
        if (data.update_type === 'CN_FUNDS') setCnFunds(data.data);
        if (data.update_type === 'SYSTEM_SUMMARY') setSystemSummary(data.data);
      }
    };

    return () => {
        clearInterval(interval);
        ws.close();
    };
  }, []);

  const handleRestart = async () => {
    if (!confirm('确定要强制重启后端交易系统吗？(用于修复 [Errno 5] 渲染错误或进程挂起)')) return;
    
    setIsRestarting(true);
    try {
      await fetch('http://localhost:8000/api/system/restart', { method: 'POST' });
    } catch (e) {
      console.error("Restart failed", e);
    } finally {
      setTimeout(() => {
        setIsRestarting(false);
        window.location.reload();
      }, 3000);
    }
  };

  const navItems = [
    { id: '终端概览', icon: LayoutDashboard, label: '终端概览' },
    { id: 'Alpha扫描', icon: Search, label: 'Alpha扫描' },
    { id: '策略分析', icon: BarChart3, label: '策略分析' },
    { id: '执行日志', icon: TerminalIcon, label: '执行日志' },
    { id: '持仓组合', icon: Briefcase, label: '持仓组合' },
  ];

  return (
    <div className="flex h-screen bg-[#0a0b10] text-slate-200 overflow-hidden font-sans">
      {/* Sidebar - Pro Version with Absolute Visibility Restart */}
      <aside className="w-[300px] border-r border-white/5 bg-[#0f1117]/50 backdrop-blur-2xl flex flex-col p-8 box-border z-50 overflow-y-auto custom-scrollbar shadow-[20px_0_40px_rgba(0,0,0,0.5)]">
        
        {/* CRITICAL: RESTORE BUTTON AT THE VERY TOP */}
        <div className="mb-8 flex-shrink-0">
           <button 
              onClick={handleRestart}
              disabled={isRestarting}
              className={`w-full group relative flex items-center justify-center gap-4 py-5 rounded-2xl transition-all border-2 overflow-hidden ${
                isRestarting 
                ? 'bg-rose-500/10 border-rose-500/20 text-rose-400 opacity-50 cursor-not-allowed' 
                : 'bg-rose-500/20 border-rose-500/40 text-rose-500 hover:bg-rose-500 hover:text-black hover:border-rose-500 hover:shadow-[0_0_40px_rgba(244,63,94,0.4)]'
              }`}
           >
              {/* Pulsing Glow Background */}
              <div className="absolute inset-0 bg-rose-500/10 animate-pulse" />
              
              <Power size={22} className={isRestarting ? 'animate-spin' : 'group-hover:rotate-12 transition-transform'} />
              <span className="text-[14px] font-black uppercase tracking-[0.2em] relative z-10">
                 {isRestarting ? '正在重启核心...' : '重启交易系统'}
              </span>
           </button>
        </div>

        <div className="mb-14 flex items-center gap-4 px-2 flex-shrink-0">
          <div className="w-12 h-12 bg-emerald-500 rounded-2xl flex items-center justify-center shadow-[0_0_20px_rgba(16,185,129,0.3)]">
            <Activity className="text-black w-7 h-7" />
          </div>
          <div className="flex flex-col">
            <span className="text-[18px] font-black tracking-tighter text-white uppercase italic">Chanlun Pro</span>
            <span className="text-[10px] text-emerald-500 font-black tracking-[0.2em] uppercase opacity-80 uppercase leading-none mt-1">Elite Terminal</span>
          </div>
        </div>

        <nav className="flex-1 space-y-3">
          {navItems.map((item) => (
            <button
              key={item.id}
              onClick={() => setActiveNav(item.id)}
              className={`w-full flex items-center gap-5 px-6 py-4.5 rounded-2xl transition-all group ${
                activeNav === item.id 
                ? 'bg-emerald-500 text-black shadow-lg shadow-emerald-500/10' 
                : 'text-slate-500 hover:text-white hover:bg-white/5'
              }`}
            >
              <item.icon size={20} className={activeNav === item.id ? 'text-black' : 'group-hover:text-emerald-400 transition-colors'} />
              <span className="text-[14px] font-black tracking-wide uppercase">{item.label}</span>
              {activeNav === item.id && <ChevronRight size={16} className="ml-auto" />}
            </button>
          ))}
        </nav>

        <div className="mt-12 space-y-6 flex-shrink-0">
          <div className="glass-pro rounded-2xl p-6 border-emerald-500/20 bg-emerald-500/[0.02]">
            <div className="flex items-center justify-between mb-4">
               <span className="text-label text-emerald-500/80">核心引擎状态</span>
               <div className="flex gap-1">
                  <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></div>
               </div>
            </div>
            <p className="text-[13px] font-bold text-white mb-1 uppercase tracking-tight italic">System Active</p>
            <p className="text-[10px] text-slate-600 font-mono">LATENCY: 14ms / STATUS: NOMINAL</p>
          </div>
          
          <button className="flex items-center gap-4 px-6 py-4 text-slate-500 hover:text-white transition-colors w-full group">
            <Settings size={20} className="group-hover:rotate-45 transition-transform" />
            <span className="text-[14px] font-black uppercase">终端设置</span>
          </button>
        </div>
      </aside>

      {/* Main Framework */}
      <main className="flex-1 flex flex-col overflow-hidden relative">
        <header className="h-[100px] border-b border-white/5 flex items-center justify-between px-12 glass-pro-header flex-shrink-0">
          <div className="flex items-center gap-12">
            <div className="flex flex-col">
               <h1 className="text-header uppercase italic">{activeNav}</h1>
               <div className="flex items-center gap-2 mt-1">
                  <div className="w-2 h-2 rounded-full bg-emerald-500"></div>
                  <span className="text-label opacity-60">实时全市场监控模式</span>
               </div>
            </div>

            <div className="h-10 w-[1px] bg-white/10"></div>

            <div className="flex gap-10 text-white">
               <div className="flex flex-col">
                  <span className="text-[10px] font-black uppercase text-slate-600 tracking-widest leading-none mb-1.5 font-bold">港股资产 (HKD)</span>
                  <span className="text-data text-[18px] tracking-tighter">¥{hkFunds.total?.toLocaleString(undefined, {minimumFractionDigits: 2})}</span>
               </div>
               <div className="flex flex-col border-r border-white/5 pr-10">
                  <span className="text-[10px] font-black uppercase text-slate-600 tracking-widest leading-none mb-1.5 font-bold">A股资产 (CNY)</span>
                  <span className="text-data text-[18px] tracking-tighter">¥{cnFunds.total?.toLocaleString(undefined, {minimumFractionDigits: 2})}</span>
               </div>
            </div>
          </div>

          <div className="flex items-center gap-6">
            <div className="bg-slate-900/50 p-1.5 rounded-2xl flex gap-1 border border-white/5 shadow-inner">
               <button className="px-5 py-2.5 rounded-xl bg-emerald-500 text-black text-[11px] font-black uppercase tracking-widest transition-all">CN/HK 全局</button>
               <button className="px-5 py-2.5 rounded-xl text-slate-500 text-[11px] font-black uppercase tracking-widest hover:text-white transition-all">美股(BETA)</button>
            </div>
            
            <div className="h-10 w-[1px] bg-white/10 mx-2"></div>
            
            <div className="flex items-center gap-4">
               <button className="w-12 h-12 rounded-2xl bg-white/5 flex items-center justify-center hover:bg-emerald-500/10 hover:text-emerald-400 transition-all group">
                  <RotateCcw size={20} className="group-hover:rotate-180 transition-transform duration-500" />
               </button>
               <button className="w-12 h-12 rounded-2xl bg-white/5 flex items-center justify-center hover:bg-emerald-500/10 hover:text-emerald-400 transition-all">
                  <Bell size={20} />
               </button>
               <div className="w-12 h-12 rounded-2xl bg-slate-800 flex items-center justify-center border border-white/10 overflow-hidden shadow-xl">
                  <User size={24} className="text-slate-400" />
               </div>
            </div>
          </div>
        </header>

        {/* Dynamic Display Grid */}
        <div className="flex-1 overflow-y-auto p-12 custom-scrollbar">
          <AnimatePresence mode="wait">
            {activeNav === '终端概览' && (
              <motion.div 
                key="summary"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                className="grid grid-cols-12 gap-10 h-full"
              >
                {/* Statistics Overlay */}
                <div className="col-span-12 flex gap-8 mb-4 font-bold">
                  <MetricCard 
                    label="当日实时收益" 
                    value={`${systemSummary.daily_pnl >= 0 ? '+' : ''}¥${systemSummary.daily_pnl?.toLocaleString(undefined, {minimumFractionDigits: 2})}`} 
                    subValue={`${systemSummary.daily_pnl_pct >= 0 ? '+' : ''}${systemSummary.daily_pnl_pct}%`} 
                    trend={systemSummary.daily_pnl >= 0 ? 'up' : 'down'} 
                  />
                  <MetricCard 
                    label="活跃监控品种" 
                    value={systemSummary.active_symbols.toString()} 
                    subValue="Multi-Market Favorites" 
                    trend="neutral" 
                  />
                  <MetricCard 
                    label="缠论计算负载" 
                    value={`${systemSummary.compute_load}%`} 
                    subValue="Edge Compute Active" 
                    trend={systemSummary.compute_load > 80 ? 'up' : 'down'} 
                  />
                  <MetricCard 
                    label="风控敞口系数" 
                    value={systemSummary.risk_exposure} 
                    subValue="Equity/Asset Ratio" 
                    trend={systemSummary.risk_exposure === 'HIGH' ? 'up' : 'neutral'} 
                  />
                </div>
                
                {/* Split View Console */}
                <div className="col-span-7 h-[850px]">
                  <Terminal />
                </div>
                <div className="col-span-5 flex flex-col gap-10">
                  <div className="flex-1 glass-pro rounded-[32px] p-10 overflow-hidden">
                    <div className="flex items-center justify-between mb-8">
                       <h3 className="text-header italic">实时持仓监控</h3>
                       <div className="flex items-center gap-3">
                          <span className="text-xs font-black text-emerald-400 uppercase tracking-widest uppercase">Live Sync</span>
                          <div className="w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_10px_#10b981]"></div>
                       </div>
                    </div>
                    <div className="space-y-4">
                       {[...hkFunds.positions, ...cnFunds.positions].slice(0, 10).map((pos, i) => (
                         <StockRow key={i} pos={pos} />
                       ))}
                    </div>
                  </div>
                </div>
              </motion.div>
            )}

            {activeNav === 'Alpha扫描' && (
              <motion.div 
                key="scan"
                initial={{ opacity: 0, scale: 0.98 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 1.02 }}
                className="h-full"
              >
                <Scanner />
              </motion.div>
            )}

            {activeNav === '策略分析' && (
              <motion.div 
                key="analyze"
                initial={{ opacity: 0, filter: 'blur(10px)' }}
                animate={{ opacity: 1, filter: 'blur(0px)' }}
                exit={{ opacity: 0 }}
                className="h-full"
              >
                <Analyzer />
              </motion.div>
            )}

            {activeNav === '执行日志' && (
               <motion.div className="h-full">
                 <Terminal />
               </motion.div>
            )}

            {activeNav === '持仓组合' && (
              <motion.div 
                key="portfolio"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex flex-col gap-10"
              >
                {/* 组合详情布局优化 */}
                <div className="grid grid-cols-2 gap-10">
                  <div className="glass-pro rounded-[32px] p-12">
                    <div className="flex items-center gap-5 mb-10">
                        <div className="p-3 rounded-2xl bg-blue-500/10 border border-blue-500/20 text-blue-400">
                           <Globe size={24} />
                        </div>
                        <h3 className="text-header italic">HK 港股组合详细</h3>
                    </div>
                    <PortfolioTable positions={hkFunds.positions} market="HK" />
                  </div>
                  <div className="glass-pro rounded-[32px] p-12">
                    <div className="flex items-center gap-5 mb-10">
                        <div className="p-3 rounded-2xl bg-orange-500/10 border border-orange-500/20 text-orange-400">
                           <PieChart size={24} />
                        </div>
                        <h3 className="text-header italic">CN A股组合详细</h3>
                    </div>
                    <PortfolioTable positions={cnFunds.positions} market="CN" />
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </main>
    </div>
  );
}

function MetricCard({ label, value, subValue, trend }: any) {
  return (
    <div className="flex-1 glass-pro rounded-[28px] p-8 border-white/5 relative overflow-hidden group hover:border-emerald-500/30 transition-all font-bold">
       <div className="absolute top-0 right-0 w-32 h-32 bg-emerald-500/5 blur-[60px] rounded-full pointer-events-none group-hover:bg-emerald-500/10 transition-colors" />
       <p className="text-label mb-3 opacity-60 italic">{label}</p>
       <div className="flex items-baseline gap-4 mb-2">
          <span className="text-value-large text-[32px] tracking-tighter">{value}</span>
          <span className={`text-[12px] font-black italic tracking-widest ${trend === 'up' ? 'text-emerald-400' : trend === 'down' ? 'text-rose-400' : 'text-slate-500'}`}>
            {trend === 'up' && '▲'} {trend === 'down' && '▼'} {subValue}
          </span>
       </div>
       <div className="w-full h-[3px] bg-slate-900 rounded-full mt-4 overflow-hidden">
          <div className={`h-full bg-emerald-500 w-2/3 shadow-[0_0_10px_#10b981] ${trend === 'down' && 'bg-rose-500 w-1/3 shadow-[0_0_10px_#f43f5e]'}`} />
       </div>
    </div>
  );
}

function StockRow({ pos }: any) {
  const cost = pos.avg_cost ?? pos.cost_price ?? 0;
  const price = pos.mkt_price ?? pos.last_price ?? 0;
  const isProfit = (price / cost - 1) >= 0;

  return (
    <div className="flex items-center justify-between p-5 rounded-2xl hover:bg-white/[0.03] transition-all group border border-transparent hover:border-white/5">
      <div className="flex items-center gap-5">
         <div className="w-10 h-10 rounded-xl bg-slate-900 flex items-center justify-center text-[10px] font-black text-slate-500 border border-white/5 group-hover:text-emerald-400 group-hover:border-emerald-500/20 transition-all uppercase">
           {pos.market || 'STK'}
         </div>
         <div className="flex flex-col">
            <span className="text-[14px] font-black text-white tracking-tight">{pos.name || pos.code}</span>
            <span className="text-[10px] font-mono font-bold text-slate-600 uppercase tracking-widest">{pos.code}</span>
         </div>
      </div>
      <div className="flex flex-col items-end">
         <span className={`text-[14px] font-mono font-black ${isProfit ? 'text-emerald-400' : 'text-rose-400'}`}>
            {cost > 0 ? (isProfit ? '+' : '') + (((price / cost) - 1) * 100).toFixed(2) + '%' : '0.00%'}
         </span>
         <span className="text-[10px] font-mono text-slate-600 font-bold uppercase tracking-widest font-bold">¥{price?.toFixed(2)}</span>
      </div>
    </div>
  );
}

function PortfolioTable({ positions, market }: any) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left border-separate border-spacing-y-4">
        <thead>
          <tr className="text-label">
            <th className="pb-4 pl-4 w-1/3">证券名称及代码</th>
            <th className="pb-4 text-center">持仓量</th>
            <th className="pb-4 text-right">成本/现价</th>
            <th className="pb-4 text-right pr-4">实时盈亏</th>
          </tr>
        </thead>
        <tbody>
          {positions.length > 0 ? positions.map((pos: any, i: number) => {
            const cost = pos.avg_cost ?? pos.cost_price ?? 0;
            const price = pos.mkt_price ?? pos.last_price ?? 0;
            const profitVal = (price - cost) * pos.qty;
            const profitPct = cost > 0 ? (price / cost - 1) * 100 : 0;
            const isProfit = profitVal >= 0;

            return (
              <tr key={i} className="group hover:bg-white/[0.03] transition-all">
                <td className="py-6 pl-6 bg-white/[0.015] rounded-l-2xl border-y border-l border-white/5">
                  <div className="flex flex-col max-w-[240px]">
                    <span className="text-[15px] font-black text-white truncate group-hover:text-emerald-400 transition-colors font-bold" title={pos.name || pos.code}>
                        {pos.name || '未知品种'}
                    </span>
                    <span className="text-[11px] font-mono font-bold text-slate-600 tracking-widest uppercase mt-1">
                        {pos.code}
                    </span>
                  </div>
                </td>
                <td className="py-6 bg-white/[0.015] border-y border-white/5 text-center">
                  <span className="text-[14px] font-mono font-bold text-slate-300">{pos.qty?.toLocaleString()}</span>
                </td>
                <td className="py-6 bg-white/[0.015] border-y border-white/5 text-right">
                  <div className="flex flex-col items-end">
                    <span className="text-[14px] font-mono font-bold text-slate-300">¥{cost?.toFixed(3)}</span>
                    <span className="text-[11px] font-mono text-slate-600 font-bold italic">L: ¥{price?.toFixed(3)}</span>
                  </div>
                </td>
                <td className="py-6 pr-6 bg-white/[0.015] rounded-r-2xl border-y border-r border-white/5 text-right">
                  <div className="flex flex-col items-end">
                    <span className={`text-[14px] font-mono font-black ${isProfit ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {isProfit ? '+' : ''}{profitVal?.toLocaleString(undefined, {minimumFractionDigits: 2})}
                    </span>
                    <span className={`text-[11px] font-mono font-bold italic ${isProfit ? 'text-emerald-500/60' : 'text-rose-500/60'}`}>
                      {isProfit ? '+' : ''}{profitPct?.toFixed(2)}%
                    </span>
                  </div>
                </td>
              </tr>
            );
          }) : (
            <tr>
                <td colSpan={4} className="py-20 text-center opacity-30 italic font-black uppercase text-xs tracking-widest font-bold">No Active Positions in {market}</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
