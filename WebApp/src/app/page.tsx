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
  Globe,
  PieChart,
  Power,
  RotateCcw
} from 'lucide-react';
import Terminal from '../components/Terminal';
import Scanner from '../components/Scanner';
import Analyzer from '../components/Analyzer';
import TradingPanel from '../components/TradingPanel';
import { motion, AnimatePresence } from 'framer-motion';

type RiskExposure = 'LOW' | 'MED' | 'HIGH';

interface Position {
  market?: string;
  currency?: string;
  name?: string;
  code: string;
  qty?: number;
  avg_cost?: number;
  cost_price?: number;
  mkt_price?: number;
  last_price?: number;
}

interface FundsStatus {
  available: number;
  total: number;
  positions: Position[];
}

interface SystemSummary {
  daily_pnl: number;
  daily_pnl_pct: number;
  active_symbols: number;
  compute_load: number;
  risk_exposure: RiskExposure;
}

interface MetricCardProps {
  label: string;
  value: string;
  subValue: string;
  trend: 'up' | 'down' | 'neutral';
}

interface StockRowProps {
  pos: Position;
}

interface PortfolioTableProps {
  positions: Position[];
  market: string;
}

export default function Dashboard() {
  const [activeNav, setActiveNav] = useState('终端概览');
  const [hkFunds, setHkFunds] = useState<FundsStatus>({ available: 0, total: 0, positions: []});
  const [cnFunds, setCnFunds] = useState<FundsStatus>({ available: 0, total: 0, positions: []});
  const [usFunds, setUsFunds] = useState<FundsStatus>({ available: 0, total: 0, positions: []});
  const [systemSummary, setSystemSummary] = useState<SystemSummary>({ 
    daily_pnl: 0, 
    daily_pnl_pct: 0, 
    active_symbols: 0, 
    compute_load: 0, 
    risk_exposure: 'LOW',
  });
  const [isRestarting, setIsRestarting] = useState(false);
  const riskExposureLabelMap: Record<string, string> = {
    LOW: '低',
    MED: '中',
    HIGH: '高',
  };

  useEffect(() => {
    const fetchFunds = async () => {
      try {
        const res = await fetch('http://localhost:8000/api/portfolio');
        const data = await res.json();
        if (data.hk) setHkFunds(data.hk);
        if (data.cn) setCnFunds(data.cn);
        if (data.us) setUsFunds(data.us);
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
        if (data.update_type === 'US_FUNDS') setUsFunds(data.data);
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
    <div className="flex h-screen bg-[#050507] text-slate-200 overflow-hidden font-sans selection:bg-indigo-500/30">
      {/* Sidebar - Precision Edition */}
      <aside className="w-[260px] border-r border-white/[0.05] bg-[#0a0a0c] flex flex-col p-6 box-border z-50 overflow-y-auto custom-scrollbar">
        
        {/* Core Control Center */}
        <div className="mb-10 flex-shrink-0">
           <button 
              onClick={handleRestart}
              disabled={isRestarting}
              className={`w-full group relative flex items-center justify-center gap-3 py-4 rounded-xl transition-all border overflow-hidden ${
                isRestarting 
                ? 'bg-rose-500/5 border-rose-500/10 text-rose-500/30' 
                : 'bg-rose-500/10 border-rose-500/20 text-rose-500 hover:bg-rose-500 hover:text-black hover:border-rose-500 hover:shadow-[0_0_30px_rgba(244,63,94,0.3)]'
              }`}
           >
              {isRestarting && <div className="absolute inset-0 bg-rose-500/10 animate-pulse" />}
              <Power size={18} className={isRestarting ? 'animate-spin' : 'group-hover:rotate-12 transition-transform'} />
              <span className="text-[12px] font-black uppercase tracking-[0.15em] relative z-10">
                 {isRestarting ? '正在重启...' : '重启引擎'}
              </span>
           </button>
        </div>

        <div className="mb-10 flex items-center gap-3 px-2 flex-shrink-0">
          <div className="w-10 h-10 bg-emerald-500 rounded-xl flex items-center justify-center shadow-[0_0_20px_rgba(16,185,129,0.2)]">
            <Activity className="text-black w-6 h-6" />
          </div>
          <div className="flex flex-col">
            <span className="text-[16px] font-black tracking-tighter text-white uppercase italic leading-none">Chanlun <span className="text-emerald-500">Pro</span></span>
            <span className="text-label mt-1 opacity-50">v2.4.0 稳定版</span>
          </div>
        </div>

        <nav className="flex-1 space-y-1">
          {navItems.map((item) => (
            <button
              key={item.id}
              onClick={() => setActiveNav(item.id)}
              className={`w-full flex items-center gap-4 px-4 py-3.5 rounded-xl transition-all relative group ${
                activeNav === item.id 
                ? 'bg-emerald-500/10 text-emerald-400' 
                : 'text-slate-500 hover:text-slate-200 hover:bg-white/[0.03]'
              }`}
            >
              {activeNav === item.id && (
                <motion.div 
                  layoutId="active-nav"
                  className="absolute left-0 w-1 h-2/3 bg-emerald-500 rounded-full"
                />
              )}
              <item.icon size={18} className={activeNav === item.id ? 'text-emerald-400' : 'group-hover:text-slate-300 transition-colors'} />
              <span className="text-[13px] font-bold tracking-tight">{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="mt-10 space-y-4 flex-shrink-0">
          <div className="glass-pro rounded-2xl p-5 border-emerald-500/10 bg-emerald-500/[0.02]">
            <div className="flex items-center justify-between mb-3">
               <span className="text-[10px] font-black uppercase text-emerald-500/60">节点状态</span>
               <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></div>
            </div>
            <p className="text-[12px] font-bold text-white mb-0.5">主账本同步中</p>
            <p className="text-[9px] font-mono text-slate-600 uppercase">延迟：0.12ms / 本机</p>
          </div>
          
          <button className="flex items-center gap-4 px-4 py-3 text-slate-500 hover:text-white transition-colors w-full group">
            <Settings size={18} className="group-hover:rotate-90 transition-transform duration-500" />
            <span className="text-[13px] font-bold">终端设置</span>
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col overflow-hidden relative">
        <header className="h-[72px] border-b border-white/[0.05] flex items-center justify-between px-8 bg-[#050507]/60 backdrop-blur-xl flex-shrink-0">
          <div className="flex items-center gap-10">
            <div className="flex flex-col">
               <h1 className="text-[20px] font-black italic uppercase tracking-tighter text-white">{activeNav}</h1>
               <div className="flex items-center gap-1.5 mt-0.5">
                  <div className="w-1.5 h-1.5 rounded-full bg-emerald-500"></div>
                  <span className="text-label opacity-40">实时市场监控</span>
               </div>
            </div>

            <div className="h-8 w-[1px] bg-white/[0.05]"></div>

            <div className="flex gap-8">
               <div className="flex flex-col">
                  <span className="text-label text-slate-600 font-bold mb-0.5">港股资产（港币）</span>
                  <span className="text-data text-[16px] tracking-tight">¥{hkFunds.total?.toLocaleString(undefined, {minimumFractionDigits: 2})}</span>
               </div>
               <div className="flex flex-col">
                  <span className="text-label text-slate-600 font-bold mb-0.5">A股资产（人民币）</span>
                  <span className="text-data text-[16px] tracking-tight">¥{cnFunds.total?.toLocaleString(undefined, {minimumFractionDigits: 2})}</span>
               </div>
               <div className="flex flex-col">
                  <span className="text-label text-slate-600 font-bold mb-0.5">美股资产（美元）</span>
                  <span className="text-data text-[16px] tracking-tight">${usFunds.total?.toLocaleString(undefined, {minimumFractionDigits: 2})}</span>
               </div>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <div className="bg-white/[0.02] p-1 rounded-xl flex gap-1 border border-white/[0.05]">
               <button className="px-4 py-1.5 rounded-lg bg-indigo-500 text-white text-[11px] font-black uppercase tracking-wider transition-all">股票</button>
               <button className="px-4 py-1.5 rounded-lg text-slate-500 text-[11px] font-black uppercase tracking-wider hover:text-slate-300 transition-all">衍生品</button>
            </div>
            
            <div className="h-8 w-[1px] bg-white/[0.05] mx-1"></div>
            
            <div className="flex items-center gap-3">
               <button className="w-10 h-10 rounded-xl bg-white/[0.03] border border-white/[0.05] flex items-center justify-center hover:bg-white/[0.08] transition-all group">
                  <RotateCcw size={16} className="text-slate-400 group-hover:rotate-180 transition-transform duration-700" />
               </button>
               <button className="w-10 h-10 rounded-xl bg-white/[0.03] border border-white/[0.05] flex items-center justify-center hover:bg-white/[0.08] transition-all relative">
                  <Bell size={16} className="text-slate-400" />
                  <div className="absolute top-2 right-2 w-2 h-2 bg-rose-500 rounded-full border-2 border-[#050507]"></div>
               </button>
               <div className="w-10 h-10 rounded-xl bg-slate-800 border border-white/[0.1] flex items-center justify-center">
                  <User size={20} className="text-slate-400" />
               </div>
            </div>
          </div>
        </header>

        {/* Dynamic Display Grid */}
        <div className="flex-1 overflow-y-auto p-10 custom-scrollbar bg-[#050507]">
          <AnimatePresence mode="wait">
            {activeNav === '终端概览' && (
              <motion.div 
                key="summary"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="grid grid-cols-12 gap-8 h-full"
              >
                {/* Statistics Overlay */}
                <div className="col-span-12 flex gap-6 mb-2">
                  <MetricCard 
                    label="当日浮动盈亏" 
                    value={`${systemSummary.daily_pnl >= 0 ? '+' : ''}¥${systemSummary.daily_pnl?.toLocaleString(undefined, {minimumFractionDigits: 2})}`} 
                    subValue={`${systemSummary.daily_pnl_pct >= 0 ? '+' : ''}${systemSummary.daily_pnl_pct}%`} 
                    trend={systemSummary.daily_pnl >= 0 ? 'up' : 'down'} 
                  />
                  <MetricCard 
                    label="活跃监控数" 
                    value={systemSummary.active_symbols.toString()} 
                    subValue="覆盖全部市场" 
                    trend="neutral" 
                  />
                  <MetricCard 
                    label="计算负载" 
                    value={`${systemSummary.compute_load}%`} 
                    subValue="策略计算引擎" 
                    trend={systemSummary.compute_load > 80 ? 'up' : 'down'} 
                  />
                  <MetricCard 
                    label="风险敞口" 
                    value={riskExposureLabelMap[systemSummary.risk_exposure] || systemSummary.risk_exposure} 
                    subValue="安全边际指数" 
                    trend={systemSummary.risk_exposure === 'HIGH' ? 'up' : 'neutral'} 
                  />
                </div>
                
                {/* Console & Positions */}
                <div className="col-span-8 h-[820px]">
                  <Terminal />
                </div>
                <div className="col-span-4 flex flex-col gap-6 h-[820px]">
                  <div className="h-[460px] shrink-0">
                    <TradingPanel />
                  </div>
                  <div className="flex-1 glass-pro rounded-[24px] p-6 overflow-hidden flex flex-col">
                    <div className="flex items-center justify-between mb-4">
                       <h3 className="text-[12px] font-black uppercase tracking-wider text-white">实时持仓</h3>
                       <div className="flex items-center gap-2">
                          <span className="text-[9px] font-black text-emerald-400 uppercase tracking-widest">实时推送</span>
                          <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 shadow-[0_0_10px_#10b981]"></div>
                       </div>
                    </div>
                    <div className="space-y-1 overflow-y-auto pr-2 custom-scrollbar">
                       {[...hkFunds.positions, ...cnFunds.positions, ...usFunds.positions].slice(0, 15).map((pos, i) => (
                         <StockRow key={i} pos={pos} />
                       ))}
                       {[...hkFunds.positions, ...cnFunds.positions, ...usFunds.positions].length === 0 && (
                         <div className="py-20 text-center text-slate-600 text-[11px] font-black uppercase tracking-widest italic opacity-30">当前没有持仓敞口</div>
                       )}
                    </div>
                  </div>
                </div>
              </motion.div>
            )}

            {activeNav === 'Alpha扫描' && (
              <motion.div 
                key="scan"
                initial={{ opacity: 0, scale: 0.99 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 1.01 }}
                className="h-full"
              >
                <Scanner />
              </motion.div>
            )}

            {activeNav === '策略分析' && (
              <motion.div 
                key="analyze"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
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
                className="flex flex-col gap-8"
              >
                <div className="grid grid-cols-3 gap-8">
                  <div className="glass-pro rounded-[32px] p-10">
                    <div className="flex items-center gap-4 mb-8">
                        <div className="w-10 h-10 rounded-xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400">
                           <Globe size={18} />
                        </div>
                        <h3 className="text-header">港股持仓</h3>
                    </div>
                    <PortfolioTable positions={hkFunds.positions} market="HK" />
                  </div>
                  <div className="glass-pro rounded-[32px] p-10">
                    <div className="flex items-center gap-4 mb-8">
                        <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
                           <PieChart size={18} />
                        </div>
                        <h3 className="text-header">A股持仓</h3>
                    </div>
                    <PortfolioTable positions={cnFunds.positions} market="CN" />
                  </div>
                  <div className="glass-pro rounded-[32px] p-10">
                    <div className="flex items-center gap-4 mb-8">
                        <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
                           <Briefcase size={18} />
                        </div>
                        <h3 className="text-header">美股持仓</h3>
                    </div>
                    <PortfolioTable positions={usFunds.positions} market="US" />
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

function MetricCard({ label, value, subValue, trend }: MetricCardProps) {
  return (
    <div className="flex-1 glass-pro rounded-2xl p-6 border-white/[0.03] relative overflow-hidden group hover:border-white/[0.08] transition-all">
       <div className="absolute top-0 right-0 w-24 h-24 bg-white/[0.02] blur-3xl rounded-full" />
       <p className="text-label mb-2.5 opacity-40">{label}</p>
       <div className="flex items-baseline justify-between mb-3">
          <span className="text-[24px] font-mono font-black text-white tracking-tighter">{value}</span>
          <span className={`text-[11px] font-mono font-black italic tracking-tight ${trend === 'up' ? 'text-emerald-400' : trend === 'down' ? 'text-rose-400' : 'text-slate-500'}`}>
            {trend === 'up' && '▲'} {trend === 'down' && '▼'} {subValue}
          </span>
       </div>
       <div className="w-full h-1 bg-white/[0.03] rounded-full overflow-hidden">
          <motion.div 
            initial={{ width: 0 }}
            animate={{ width: trend === 'down' ? '30%' : '70%' }}
            className={`h-full ${trend === 'down' ? 'bg-rose-500/50' : trend === 'up' ? 'bg-emerald-500/50' : 'bg-slate-500/30'}`} 
          />
       </div>
    </div>
  );
}

function StockRow({ pos }: StockRowProps) {
  const cost = pos.avg_cost ?? pos.cost_price ?? 0;
  const price = pos.mkt_price ?? pos.last_price ?? 0;
  const isProfit = (price / cost - 1) >= 0;
  const currencySymbol = pos.market === 'US' || pos.currency === 'USD' ? '$' : '¥';

  return (
    <div className="flex items-center justify-between p-3.5 rounded-xl hover:bg-white/[0.03] transition-all group border border-transparent hover:border-white/[0.05]">
      <div className="flex items-center gap-4">
         <div className="w-9 h-9 rounded-lg bg-slate-900 flex items-center justify-center text-[9px] font-black text-slate-600 border border-white/[0.03] group-hover:text-white group-hover:border-white/[0.1] transition-all uppercase">
            {pos.market || '股票'}
         </div>
         <div className="flex flex-col">
            <span className="text-[13px] font-black text-slate-200 group-hover:text-white transition-colors">{pos.name || pos.code}</span>
            <span className="text-[9px] font-mono font-bold text-slate-600 uppercase tracking-widest">{pos.code}</span>
         </div>
      </div>
      <div className="flex flex-col items-end">
         <span className={`text-[13px] font-mono font-black ${isProfit ? 'text-emerald-400' : 'text-rose-400'}`}>
            {cost > 0 ? (isProfit ? '+' : '') + (((price / cost) - 1) * 100).toFixed(2) + '%' : '0.00%'}
         </span>
         <span className="text-[9px] font-mono text-slate-600 font-bold uppercase tracking-widest font-bold">{currencySymbol}{price?.toFixed(2)}</span>
      </div>
    </div>
  );
}

function PortfolioTable({ positions, market }: PortfolioTableProps) {
  const currencySymbol = market === 'US' ? '$' : '¥';

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left border-separate border-spacing-y-2">
        <thead>
          <tr className="text-label opacity-40">
            <th className="pb-3 pl-4">资产 / 代码</th>
            <th className="pb-3 text-center">数量</th>
            <th className="pb-3 text-right">成本 / 现价</th>
            <th className="pb-3 text-right pr-4">实时盈亏</th>
          </tr>
        </thead>
        <tbody>
          {positions.length > 0 ? positions.map((pos, i: number) => {
            const cost = pos.avg_cost ?? pos.cost_price ?? 0;
            const price = pos.mkt_price ?? pos.last_price ?? 0;
            const profitVal = (price - cost) * pos.qty;
            const profitPct = cost > 0 ? (price / cost - 1) * 100 : 0;
            const isProfit = profitVal >= 0;

            return (
              <tr key={i} className="group hover:bg-white/[0.02] transition-all">
                <td className="py-4 pl-5 bg-white/[0.015] rounded-l-xl border-y border-l border-white/[0.05]">
                  <div className="flex flex-col">
                    <span className="text-[14px] font-black text-slate-200 group-hover:text-white transition-colors">
                        {pos.name || '未知'}
                    </span>
                    <span className="text-[10px] font-mono font-bold text-slate-600 tracking-widest mt-0.5">
                        {pos.code}
                    </span>
                  </div>
                </td>
                <td className="py-4 bg-white/[0.015] border-y border-white/[0.05] text-center">
                  <span className="text-[13px] font-mono font-bold text-slate-400">{pos.qty?.toLocaleString()}</span>
                </td>
                <td className="py-4 bg-white/[0.015] border-y border-white/[0.05] text-right">
                  <div className="flex flex-col items-end">
                    <span className="text-[13px] font-mono font-bold text-slate-300">{currencySymbol}{cost?.toFixed(3)}</span>
                    <span className="text-[10px] font-mono text-slate-600 font-bold">{currencySymbol}{price?.toFixed(3)}</span>
                  </div>
                </td>
                <td className="py-4 pr-5 bg-white/[0.015] rounded-r-xl border-y border-r border-white/[0.05] text-right">
                  <div className="flex flex-col items-end">
                    <span className={`text-[13px] font-mono font-black ${isProfit ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {isProfit ? '+' : ''}{profitVal?.toLocaleString(undefined, {minimumFractionDigits: 2})}
                    </span>
                    <span className={`text-[10px] font-mono font-bold ${isProfit ? 'text-emerald-500/50' : 'text-rose-500/50'}`}>
                      {isProfit ? '+' : ''}{profitPct?.toFixed(2)}%
                    </span>
                  </div>
                </td>
              </tr>
            );
          }) : (
            <tr>
                <td colSpan={4} className="py-20 text-center text-slate-700 text-[10px] font-black uppercase tracking-widest italic opacity-20">{market} 暂无可用数据</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
