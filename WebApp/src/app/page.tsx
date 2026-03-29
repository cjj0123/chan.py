"use client";

import React, { useState, useEffect } from 'react';
import { 
  TrendingUp, 
  Activity, 
  BarChart3, 
  ShieldCheck, 
  Globe, 
  User, 
  Settings, 
  ChevronRight,
  RefreshCw,
  Wallet,
  PieChart,
  Zap,
  LayoutDashboard
} from 'lucide-react';
import Terminal from '@/components/Terminal';
import { motion, AnimatePresence } from 'framer-motion';

export default function Dashboard() {
  const [portfolio, setPortfolio] = useState<any>(null);
  const [activeMarket, setActiveMarket] = useState('HK');
  const [activeNav, setActiveNav] = useState('实时监控');
  const [isSidebarOpen, setSidebarOpen] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const res = await fetch('http://localhost:8000/api/portfolio');
        const data = await res.json();
        setPortfolio(data);
      } catch (e) {
        console.error("Fetch failed", e);
      }
    };
    fetchStats();
    const interval = setInterval(fetchStats, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleRefresh = () => {
    setIsRefreshing(true);
    setTimeout(() => setIsRefreshing(false), 1200);
  };

  const currentData = activeMarket === 'HK' ? portfolio?.hk : portfolio?.cn;
  const positions = currentData?.positions || [];
  const availableCash = currentData?.available || 0;
  const totalAssets = currentData?.total || 0;

  return (
    <main className="flex min-h-screen bg-[#050507] text-slate-100 overflow-hidden font-sans selection:bg-emerald-500/30">
      {/* Sidebar Navigation */}
      <motion.aside 
        initial={false}
        animate={{ width: isSidebarOpen ? 240 : 80 }}
        className="relative bg-[#0d0d0f] border-r border-white/5 flex flex-col z-20 shadow-[-10px_0_40px_rgba(0,0,0,0.5)] transition-all h-screen overflow-hidden group/sidebar"
      >
        <div className="p-8 flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-emerald-500 flex items-center justify-center p-2 shadow-[0_0_25px_rgba(16,185,129,0.5)]">
            <LayoutDashboard className="text-black" />
          </div>
          {isSidebarOpen && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex flex-col">
              <h1 className="text-xs font-black tracking-[0.3em] bg-gradient-to-r from-white to-slate-400 bg-clip-text text-transparent uppercase">
                CHANLUN SYSTEM
              </h1>
              <span className="text-[9px] text-emerald-500 font-bold uppercase tracking-[.2em] mt-0.5">缠论级速终端 V4.0</span>
            </motion.div>
          )}
        </div>

        <nav className="flex-1 mt-6 px-4 space-y-1.5 overflow-y-auto terminal-scroll">
           <SidebarItem icon={<Activity size={20} />} label="系统实时监控" active={activeNav === '实时监控'} onClick={() => setActiveNav('实时监控')} showLabel={isSidebarOpen} />
           <SidebarItem icon={<TrendingUp size={20} />} label="缠论多維分析" active={activeNav === '策略分析'} onClick={() => setActiveNav('策略分析')} showLabel={isSidebarOpen} />
           <SidebarItem icon={<Globe size={20} />} label="全市场扫描仪" active={activeNav === '全市场扫描'} onClick={() => setActiveNav('全市场扫描')} showLabel={isSidebarOpen} />
           <SidebarItem icon={<PieChart size={20} />} label="投资组合概览" active={activeNav === '持仓组合'} onClick={() => setActiveNav('持仓组合')} showLabel={isSidebarOpen} />
           <SidebarItem icon={<Settings size={20} />} label="核心参数配置" active={activeNav === '系统设置'} onClick={() => setActiveNav('系统设置')} showLabel={isSidebarOpen} />
        </nav>

        <div className="p-6 mt-auto border-t border-white/5 bg-gradient-to-b from-transparent to-black/50 text-center">
            {isSidebarOpen ? (
                <div className="flex flex-col gap-1 items-center">
                    <p className="text-[9px] text-slate-600 uppercase tracking-widest font-black italic">System Core Ready</p>
                    <div className="flex items-center gap-2 mt-1 px-3 py-1 rounded-full bg-emerald-500/5 border border-emerald-500/20">
                        <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse shadow-[0_0_8px_rgba(16,185,129,1)]" />
                        <p className="text-[10px] font-bold text-emerald-400 uppercase tracking-tighter">Connected</p>
                    </div>
                </div>
            ) : (
                <div className="w-2 h-2 rounded-full bg-emerald-500 mx-auto animate-pulse" />
            )}
        </div>
        
        <button 
           onClick={() => setSidebarOpen(!isSidebarOpen)}
           className="absolute bottom-4 -right-3 w-7 h-7 rounded-full bg-[#1e1e21] border border-white/10 text-slate-400 flex items-center justify-center shadow-2xl hover:bg-emerald-500 hover:text-black hover:border-emerald-500 transition-all cursor-pointer z-30"
        >
           <ChevronRight size={16} className={`transform transition-transform duration-500 ${!isSidebarOpen ? '' : 'rotate-180'}`} />
        </button>
      </motion.aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col h-screen overflow-hidden">
        {/* Top Header Bar */}
        <header className="h-20 px-10 flex items-center justify-between border-b border-white/5 bg-[#050507]/90 backdrop-blur-3xl z-10 shrink-0">
          <div className="flex items-center gap-10">
             <div className="flex bg-[#111113]/80 p-1 rounded-xl border border-white/5 items-center gap-1 shadow-inner">
                <HeaderMarketTag label="香港市场" active={activeMarket === 'HK'} onClick={() => setActiveMarket('HK')} />
                <HeaderMarketTag label="全中国 A 股" active={activeMarket === 'CN'} onClick={() => setActiveMarket('CN')} />
                <HeaderMarketTag label="纳斯达克/美股" active={activeMarket === 'US'} onClick={() => setActiveMarket('US')} />
             </div>
          </div>
          
          <div className="flex items-center gap-8">
             <div className="flex flex-col items-end mr-2">
                <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest leading-none">实时引擎延迟</span>
                <span className="text-[11px] font-mono font-bold text-emerald-500 mt-1 uppercase tracking-tighter">24ms / RTT</span>
             </div>
             
             <motion.button 
                whileHover={{ rotate: 180 }}
                onClick={handleRefresh} 
                className={`p-3 rounded-xl bg-[#111113] border border-white/5 hover:border-emerald-500/40 hover:bg-emerald-500/[0.02] shadow-xl transition-all ${isRefreshing ? 'border-emerald-500' : ''}`}
             >
                <RefreshCw size={18} className={`text-slate-400 ${isRefreshing ? 'animate-spin text-emerald-400' : ''}`} />
             </motion.button>
          </div>
        </header>

        {/* Dynamic Content */}
        <div className="flex-1 p-10 grid grid-cols-12 gap-10 overflow-hidden min-h-0 bg-[radial-gradient(#1e1e21_0.8px,transparent_0.8px)] [background-size:32px_32px] overflow-y-auto terminal-scroll">
          <section className="col-span-12 md:col-span-8 flex flex-col gap-10">
             {/* Key Metrics */}
             <div className="grid grid-cols-3 gap-10">
                <MetricCard label="当前可用资金" value={(availableCash / 10000).toFixed(2)} unit="万" trend="+0.45%" symbol={activeMarket === 'HK' ? 'HK$' : '¥'} />
                <MetricCard label="资产净值总额" value={(totalAssets / 10000).toFixed(2)} unit="万" trend="+3.21%" trendUp={true} symbol={activeMarket === 'HK' ? 'HK$' : '¥'} />
                <MetricCard label="持仓标的总数" value={positions.length.toString()} unit="个" trend={`实时监控中 ${positions.length} 只`} />
             </div>
             
             {/* Main Viewer */}
             <div className="h-[500px] overflow-hidden shadow-2xl">
                {activeNav === '实时监控' ? <Terminal /> : (
                    <div className="h-full bg-[#0d0d0f]/90 rounded-3xl border border-white/10 p-12 overflow-hidden backdrop-blur-3xl shadow-2xl flex flex-col">
                        <div className="flex items-center justify-between mb-8 border-b border-white/5 pb-8">
                            <h2 className="text-xl font-black text-white italic tracking-tighter uppercase flex items-center gap-4">
                                <PieChart size={24} className="text-emerald-500" />
                                {activeMarket === 'HK' ? '港股投资组合详情' : 'A股投资组合详情'}
                            </h2>
                            <span className="px-4 py-2 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-[10px] font-black uppercase tracking-widest leading-none">
                                SECURED_ASSETS
                            </span>
                        </div>
                        
                        <div className="flex-1 overflow-y-auto terminal-scroll">
                            <table className="w-full text-left border-separate border-spacing-y-4">
                                <thead className="text-[10px] font-black text-slate-500 uppercase tracking-widest">
                                    <tr>
                                        <th className="px-6 py-4">股票名称 / 代码</th>
                                        <th className="px-6 py-4 text-center">持仓数量</th>
                                        <th className="px-6 py-4 text-right">成本均价</th>
                                        <th className="px-6 py-4 text-right">参考现价</th>
                                        <th className="px-6 py-4 text-right">持仓市值</th>
                                        <th className="px-6 py-4 text-right">累计盈亏</th>
                                        <th className="px-6 py-4 text-right">盈亏率</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {(positions || []).map((pos: any, i: number) => {
                                        const qtyVal = Number(pos.qty || 0);
                                        const avgCost = Number(pos.avg_cost || 0);
                                        const mktVal = Number(pos.mkt_value || 0);
                                        const pnlRatio = Number(pos.pnl_ratio || 0);
                                        const profitVal = mktVal - (avgCost * qtyVal);
                                        
                                        return (
                                            <tr key={i} className="group hover:bg-white/[0.02] transition-colors duration-500 rounded-2xl">
                                                <td className="px-6 py-6 bg-white/[0.02] rounded-l-2xl border-y border-l border-white/5">
                                                    <div className="flex flex-col">
                                                        <span className="text-sm font-black text-white mb-1">{pos.name || (activeMarket === 'HK' ? '港股持仓' : 'A股持仓')}</span>
                                                        <span className="text-[10px] font-mono text-slate-500 tracking-wider uppercase font-black">{pos.code}</span>
                                                    </div>
                                                </td>
                                                <td className="px-6 py-6 bg-white/[0.02] border-y border-white/5 font-black text-slate-300 text-sm text-center">{qtyVal.toLocaleString()}</td>
                                                <td className="px-6 py-6 bg-white/[0.02] border-y border-white/5 text-right font-mono text-slate-400 text-xs">{avgCost.toFixed(2)}</td>
                                                <td className="px-6 py-6 bg-white/[0.02] border-y border-white/5 text-right font-mono text-white text-sm font-black">
                                                    {(pos.mkt_price || (avgCost * (1 + pnlRatio/100))).toFixed(2)}
                                                </td>
                                                <td className="px-6 py-6 bg-white/[0.02] border-y border-white/5 text-right font-mono text-slate-300 text-sm">{mktVal.toFixed(0)}</td>
                                                <td className={`px-6 py-6 bg-white/[0.02] border-y border-white/5 text-right font-mono text-sm font-black ${profitVal >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                                    {profitVal >= 0 ? '+' : ''}{profitVal.toFixed(0)}
                                                </td>
                                                <td className={`px-6 py-6 bg-white/[0.02] rounded-r-2xl border-y border-r border-white/5 text-right font-mono text-sm font-black ${pnlRatio >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                                    {pnlRatio > 0 ? '+' : ''}{pnlRatio}%
                                                </td>
                                            </tr>
                                        )
                                    })}
                                    {(!positions || positions.length === 0) && (
                                        <tr>
                                            <td colSpan={7} className="py-32 text-center text-slate-600 font-black uppercase text-xs tracking-widest italic bg-white/[0.01] rounded-3xl border border-dashed border-white/5">
                                                当前市场无活跃持仓记录
                                            </td>
                                        </tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}
             </div>
          </section>

          <section className="col-span-12 md:col-span-4 flex flex-col gap-10 overflow-hidden">
             {/* Real Positions Table */}
             <div className="flex-1 bg-[#0d0d0f]/90 rounded-3xl border border-white/10 p-10 shadow-2xl flex flex-col overflow-hidden backdrop-blur-3xl group transition-all duration-500 hover:shadow-emerald-500/5">
                <div className="flex items-center justify-between mb-10">
                   <div className="flex flex-col gap-1.5">
                      <h2 className="text-xs font-black uppercase tracking-[0.3em] text-emerald-400 italic">实时持仓监控</h2>
                      <span className="text-[9px] text-slate-600 uppercase font-black tracking-widest">REALTIME_PORTFOLIO_SYNC</span>
                   </div>
                   <div className="p-3 rounded-xl bg-white/5 border border-white/5 shadow-inner">
                       <PieChart size={18} className="text-emerald-500/50" />
                   </div>
                </div>
                
                <div className="flex-1 overflow-y-auto space-y-6 pr-2 terminal-scroll">
                   {positions.length > 0 ? positions.map((pos: any, idx: number) => (
                      <StockRow 
                        key={idx}
                        symbol={pos.code} 
                        name={pos.name || (activeMarket === 'HK' ? '港股持仓' : 'A股持仓')} 
                        qty={pos.qty}
                        price={pos.mkt_price?.toFixed(2) || pos.avg_cost?.toFixed(2) || "0.00"} 
                        change={pos.pnl_ratio > 0 ? `+${pos.pnl_ratio}%` : `${pos.pnl_ratio}%`} 
                        profit={(pos.mkt_value - (pos.avg_cost * (pos.qty || 0))).toFixed(0)} 
                        profitUp={pos.pnl_ratio >= 0} 
                      />
                   )) : (
                     <div className="flex flex-col items-center justify-center h-full gap-4 text-slate-700 p-10 text-center">
                        <ShieldCheck size={40} className="text-emerald-500/10" />
                        <p className="text-[10px] uppercase font-black tracking-widest leading-loose">
                           无活跃持仓记录<br/>
                           <span className="text-slate-800 text-[8px] italic">No active ledger entry found for current market</span>
                        </p>
                     </div>
                   )}
                </div>
                
                <motion.button 
                   whileHover={{ scale: 1.01, backgroundColor: 'rgba(52, 211, 153, 0.9)' }}
                   whileTap={{ scale: 0.99 }}
                   onClick={() => alert("交易注入模块尚未就绪...")}
                   className="mt-10 w-full py-5 bg-emerald-500 text-black font-black uppercase tracking-[0.2em] text-[11px] rounded-2xl shadow-[0_15px_40px_rgba(16,185,129,0.3)] transition-all"
                >
                   手动调整持仓
                </motion.button>
             </div>
             
             {/* Security/Risk Card */}
             <div className="h-44 bg-gradient-to-br from-[#111113] to-black rounded-3xl border border-white/5 p-8 flex flex-col justify-center items-center text-center group relative overflow-hidden shadow-2xl">
                <div className="absolute inset-0 bg-emerald-500/[0.02] opacity-0 group-hover:opacity-100 transition-opacity duration-1000 blur-3xl" />
                <ShieldCheck size={36} className="text-emerald-500/40 mb-4 z-10 transition-transform duration-700 group-hover:rotate-12" />
                <div className="z-10">
                   <h3 className="text-xs font-black text-slate-200 uppercase tracking-[0.3em] italic">风险防卫矩阵</h3>
                   <p className="text-[10px] text-slate-500 mt-2 uppercase font-black tracking-[.2em] leading-loose italic">
                     核心风控: <span className="text-emerald-500/80 underline decoration-emerald-500/20">ATR TRAILING STOP</span><br/>
                     状态: <span className="text-emerald-400 font-mono tracking-tighter">SECURED_2.5X_MULT</span>
                   </p>
                </div>
             </div>
          </section>
        </div>
      </div>
    </main>
  );
}

function SidebarItem({ icon, label, active = false, showLabel = true, onClick }: any) {
  return (
    <button 
      onClick={onClick}
      className={`w-full flex items-center gap-5 p-4 rounded-2xl transition-all duration-300 relative group ${
        active ? 'bg-emerald-500/10 text-emerald-400 shadow-[inset_0_0_20px_rgba(16,185,129,0.05)] border border-emerald-500/20' : 'text-slate-500 hover:bg-white/[0.04] hover:text-slate-200'
      }`}
    >
      <span className={`shrink-0 transition-transform duration-500 ${active ? 'scale-110 drop-shadow-[0_0_12px_rgba(16,185,129,0.6)]' : 'group-hover:scale-110'}`}>{icon}</span>
      {showLabel && (
        <span className={`text-[11px] font-black tracking-[0.2em] text-left flex-1 transition-all duration-300 ${active ? 'opacity-100' : 'opacity-70 group-hover:opacity-100'}`}>
          {label}
        </span>
      )}
      {active && <div className="absolute left-[-1px] top-4 bottom-4 w-1 bg-emerald-500 rounded-full shadow-[0_0_15px_rgba(16,185,129,1)]" />}
    </button>
  );
}

function HeaderMarketTag({ label, active, onClick }: any) {
  return (
    <button 
      onClick={onClick} 
      className={`px-8 py-3 rounded-xl text-[11px] font-black uppercase tracking-[0.2em] transition-all duration-500 ${
        active ? 'bg-[#1e1e21] text-white shadow-[0_10px_30px_rgba(0,0,0,0.4)] border border-white/10 scale-[1.02]' : 'text-slate-500 hover:text-slate-300'
      }`}
    >
      {label}
    </button>
  );
}

function MetricCard({ label, value, unit, trend, trendUp = true, symbol = '' }: any) {
  return (
    <div className="bg-[#0d0d0f]/60 backdrop-blur-xl border border-white/5 p-8 rounded-3xl shadow-2xl hover:border-emerald-500/25 transition-all duration-700 flex flex-col items-start min-h-[160px] relative overflow-hidden group">
      <div className="absolute top-0 right-0 w-48 h-48 bg-emerald-500/5 blur-[100px] rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-1000" />
      <div className="flex items-center justify-between w-full mb-4">
         <span className="text-[10px] font-black text-slate-600 uppercase tracking-[0.4em] italic leading-none">{label}</span>
         <div className={`text-[10px] font-black tracking-widest px-2 py-0.5 rounded leading-none ${trendUp ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'}`}>
            {trend}
         </div>
      </div>
      <div className="flex items-baseline gap-2 mt-auto">
         <span className="text-[10px] font-black text-slate-500 mb-2">{symbol}</span>
         <span className="text-[34px] font-mono font-black text-white group-hover:text-emerald-400 transition-colors duration-500 drop-shadow-[0_4px_10px_rgba(0,0,0,0.5)]">{value}</span>
         <span className="text-[10px] font-black text-slate-600 uppercase mb-2">{unit}</span>
      </div>
    </div>
  );
}

function StockRow({ symbol, name, price, change, profit, profitUp, qty }: any) {
  return (
    <div className="flex items-center justify-between p-5 rounded-2xl bg-[#08080a] border border-white/5 hover:border-emerald-500/30 group transition-all duration-500 cursor-pointer overflow-hidden backdrop-blur-sm shadow-xl relative">
       <div className="absolute inset-0 bg-emerald-500/[0.01] opacity-0 group-hover:opacity-100 transition-opacity" />
       
       <div className="flex-1 min-w-0 mr-6 z-10">
          <div className="flex items-center gap-2 mb-1.5">
             <span className="text-sm font-black text-white group-hover:text-emerald-400 transition-colors tracking-tighter">{symbol}</span>
             <span className={`text-[9px] font-black px-1.5 py-0.5 rounded ${change.startsWith('+') ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'}`}>
               {change}
             </span>
          </div>
          <div className="flex flex-col gap-0.5">
            <p className="text-[10px] text-white font-black uppercase tracking-wider truncate">{name}</p>
            <div className="flex items-center gap-2">
                <span className="text-[9px] text-slate-500 font-black uppercase tracking-widest">QTY</span>
                <span className="text-[10px] text-slate-300 font-mono font-black">{qty.toLocaleString()}</span>
            </div>
          </div>
       </div>

       <div className="text-right shrink-0 flex flex-col items-end z-10">
          <div className="flex flex-col items-end mb-2">
             <span className="text-[8px] text-slate-600 font-black uppercase tracking-widest mb-0.5">AVG_COST</span>
             <div className="text-xs font-mono font-black text-white group-hover:text-emerald-400 transition-colors tracking-tighter">¥{price}</div>
          </div>
          <div className={`text-[10px] font-black px-3 py-1 rounded-lg border ${profitUp ? 'bg-emerald-500/5 text-emerald-400 border-emerald-500/20' : 'bg-rose-500/5 text-rose-400 border-rose-500/20'}`}>
             {profitUp ? '+' : ''}{profit}
          </div>
       </div>
    </div>
  );
}
