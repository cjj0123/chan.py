"use client";

import React, { useState, useEffect } from 'react';
import { 
  ShieldCheck, 
  Zap, 
  AlertTriangle, 
  ArrowUpCircle, 
  ArrowDownCircle, 
  CheckCircle2, 
  XCircle,
  TrendingUp,
  RefreshCw,
  Wallet,
  Settings2,
  Lock,
  Unlock,
  ChevronRight,
  Target
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

interface MarketConfig {
  auto_trade: boolean;
  live_mode: boolean;
}

interface TradingConfig {
  HK: MarketConfig;
  CN: MarketConfig;
}

export default function TradingPanel() {
  const [activeMarket, setActiveMarket] = useState<'HK' | 'CN'>('HK');
  const [configs, setConfigs] = useState<TradingConfig | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isUnlocked, setIsUnlocked] = useState(false);
  
  // Manual Order State
  const [symbol, setSymbol] = useState('');
  const [action, setAction] = useState<'BUY' | 'SELL'>('BUY');
  const [price, setPrice] = useState('');
  const [qty, setQty] = useState('');

  const fetchConfig = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/trading/config');
      const data = await res.json();
      setConfigs(data);
    } catch (e) {
      console.error("Failed to fetch trading config", e);
    }
  };

  useEffect(() => {
    fetchConfig();
    const interval = setInterval(fetchConfig, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleToggle = async (type: 'auto_trade' | 'live_mode') => {
    if (!configs) return;
    setIsLoading(true);
    
    const currentMarketConfig = configs[activeMarket];
    const newConfig = {
      market: activeMarket,
      [type]: !currentMarketConfig[type]
    };

    try {
      const res = await fetch('http://localhost:8000/api/trading/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConfig)
      });
      const data = await res.json();
      setConfigs(prev => prev ? { ...prev, [activeMarket]: data } : null);
    } catch (e) {
      console.error("Failed to toggle trading", e);
    } finally {
      setIsLoading(false);
    }
  };

  const handleOrder = async () => {
    if (!isUnlocked) return;
    if (!symbol || !price || !qty) return;

    setIsLoading(true);
    try {
      const res = await fetch('http://localhost:8000/api/trading/order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          market: activeMarket,
          symbol,
          action,
          price: parseFloat(price),
          qty: parseInt(qty)
        })
      });
      const data = await res.json();
      if (data.success) {
        setSymbol('');
        setPrice('');
        setQty('');
      }
    } catch (e) {
      console.error("Failed to place order", e);
    } finally {
      setIsLoading(false);
    }
  };

  const handleEmergencyStop = async () => {
    if (!confirm(`确定要立即停止并清空 ${activeMarket} 市场的所有挂单吗？`)) return;
    
    setIsLoading(true);
    try {
      await fetch(`http://localhost:8000/api/trading/emergency_stop?market=${activeMarket}`, {
        method: 'POST'
      });
    } catch (e) {
      console.error("Emergency stop failed", e);
    } finally {
      setIsLoading(false);
    }
  };

  if (!configs) return <div className="animate-pulse bg-white/5 rounded-3xl h-full w-full"></div>;

  const currentCfg = configs[activeMarket];

  return (
    <div className="flex flex-col h-full glass-pro rounded-[32px] overflow-hidden border border-white/[0.05] bg-[#0a0a0c]/40 backdrop-blur-3xl">
      {/* Header Tabs */}
      <div className="flex p-2 bg-white/[0.02] border-b border-white/[0.05]">
        {(['HK', 'CN'] as const).map((market) => (
          <button
            key={market}
            onClick={() => setActiveMarket(market)}
            className={`flex-1 py-3 rounded-2xl text-[11px] font-black uppercase tracking-[0.2em] transition-all flex items-center justify-center gap-2 ${
              activeMarket === market 
              ? 'bg-indigo-500 text-white shadow-[0_0_20px_rgba(99,102,241,0.3)]' 
              : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            <Target size={14} className={activeMarket === market ? 'animate-spin-slow' : ''} />
            {market === 'HK' ? 'Hong Kong' : 'China A'}
          </button>
        ))}
      </div>

      <div className="p-8 flex-1 overflow-y-auto custom-scrollbar space-y-8">
        {/* Status Indicators */}
        <div className="grid grid-cols-2 gap-4">
          <StatusCard 
            label="Auto Strategy" 
            isActive={currentCfg.auto_trade} 
            icon={Zap} 
            color="emerald" 
            onClick={() => handleToggle('auto_trade')}
            disabled={isLoading}
          />
          <StatusCard 
            label="Live Trading" 
            isActive={currentCfg.live_mode} 
            icon={ShieldCheck} 
            color="rose" 
            onClick={() => handleToggle('live_mode')}
            disabled={isLoading}
          />
        </div>

        {/* Manual Order Core */}
        <div className="space-y-6">
          <div className="flex items-center justify-between">
             <h4 className="text-[11px] font-black uppercase tracking-[0.2em] text-slate-500">Manual Execution Unit</h4>
             <button 
                onClick={() => setIsUnlocked(!isUnlocked)}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border transition-all ${
                    isUnlocked 
                    ? 'bg-amber-500/10 border-amber-500/20 text-amber-500 shadow-[0_0_15px_rgba(245,158,11,0.1)]' 
                    : 'bg-white/5 border-white/10 text-slate-500'
                }`}
             >
                {isUnlocked ? <Unlock size={14} /> : <Lock size={14} />}
                <span className="text-[10px] font-black uppercase tracking-widest">{isUnlocked ? 'Unlocked' : 'Locked'}</span>
             </button>
          </div>

          <div className={`space-y-4 transition-all duration-500 ${isUnlocked ? 'opacity-100 scale-100' : 'opacity-20 scale-[0.98] pointer-events-none grayscale'}`}>
             <div className="grid grid-cols-2 gap-4">
                <button 
                    onClick={() => setAction('BUY')}
                    className={`py-4 rounded-2xl border transition-all flex flex-col items-center gap-1 ${
                        action === 'BUY' 
                        ? 'bg-emerald-500 border-emerald-400 text-black shadow-[0_0_30px_rgba(16,185,129,0.2)]' 
                        : 'bg-white/5 border-white/5 text-slate-500 hover:border-white/20'
                    }`}
                >
                    <ArrowUpCircle size={20} />
                    <span className="text-[10px] font-black uppercase tracking-widest">Long Position</span>
                </button>
                <button 
                    onClick={() => setAction('SELL')}
                    className={`py-4 rounded-2xl border transition-all flex flex-col items-center gap-1 ${
                        action === 'SELL' 
                        ? 'bg-rose-500 border-rose-400 text-black shadow-[0_0_30px_rgba(244,63,94,0.2)]' 
                        : 'bg-white/5 border-white/5 text-slate-500 hover:border-white/20'
                    }`}
                >
                    <ArrowDownCircle size={20} />
                    <span className="text-[10px] font-black uppercase tracking-widest">Short Position</span>
                </button>
             </div>

             <div className="space-y-3">
                <InputGroup label="Symbol" value={symbol} onChange={setSymbol} placeholder="e.g. HK.00700 or SH.600519" />
                <div className="grid grid-cols-2 gap-3">
                    <InputGroup label="Price" value={price} onChange={setPrice} placeholder="Auto" type="number" />
                    <InputGroup label="Quantity" value={qty} onChange={setQty} placeholder="Min Lot" type="number" />
                </div>
             </div>

             <button 
                onClick={handleOrder}
                disabled={isLoading}
                className={`w-full py-5 rounded-2xl bg-indigo-500 text-white font-black uppercase tracking-[0.2em] text-[12px] shadow-lg hover:bg-indigo-400 transition-all flex items-center justify-center gap-3 active:scale-[0.97]`}
             >
                <TrendingUp size={18} />
                Transmit Order to Exchange
             </button>
          </div>
        </div>

        {/* Emergency Stop */}
        <div className="pt-4 border-t border-white/[0.05]">
          <button 
            onClick={handleEmergencyStop}
            className="w-full flex items-center justify-between p-5 rounded-2xl bg-rose-500/5 border border-rose-500/20 text-rose-500 hover:bg-rose-500 hover:text-black hover:border-rose-500 transition-all group"
          >
            <div className="flex items-center gap-4">
                <AlertTriangle size={20} className="group-hover:animate-bounce" />
                <div className="flex flex-col items-start">
                    <span className="text-[11px] font-black uppercase tracking-widest">Emergency Liquidate</span>
                    <span className="text-[9px] opacity-60 font-medium">Cancel all orders & exit positions</span>
                </div>
            </div>
            <ChevronRight size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}

function StatusCard({ label, isActive, icon: Icon, color, onClick, disabled }: any) {
  const colorMap: any = {
    emerald: isActive ? 'bg-emerald-500 text-black' : 'bg-white/5 text-slate-500 border-white/5',
    rose: isActive ? 'bg-rose-500 text-black' : 'bg-white/5 text-slate-500 border-white/5'
  };

  return (
    <button 
      onClick={onClick}
      disabled={disabled}
      className={`p-5 rounded-3xl border transition-all flex flex-col items-start gap-4 h-[120px] relative overflow-hidden group ${colorMap[color]}`}
    >
      <div className={`p-2 rounded-xl ${isActive ? 'bg-black/10' : 'bg-white/5'} transition-colors`}>
        <Icon size={20} className={isActive ? 'animate-pulse' : ''} />
      </div>
      <div className="flex flex-col items-start">
        <span className="text-[10px] font-black uppercase tracking-[0.1em] opacity-60">{label}</span>
        <span className="text-[13px] font-black uppercase tracking-widest">{isActive ? 'Active' : 'Standby'}</span>
      </div>
      {isActive && (
        <div className={`absolute -right-2 -bottom-2 w-12 h-12 ${color === 'emerald' ? 'bg-emerald-400/20' : 'bg-rose-400/20'} blur-2xl rounded-full`} />
      )}
    </button>
  );
}

function InputGroup({ label, value, onChange, placeholder, type = 'text' }: any) {
  return (
    <div className="space-y-1.5 flex-1">
      <label className="text-[9px] font-black uppercase tracking-[0.2em] text-slate-600 pl-2">{label}</label>
      <input 
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full bg-white/[0.03] border border-white/[0.05] rounded-xl px-4 py-3 text-[13px] text-white placeholder:text-slate-700 outline-none focus:border-indigo-500/50 focus:bg-white/[0.05] transition-all font-mono"
      />
    </div>
  );
}
