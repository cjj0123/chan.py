'use client';

import React, { useState, useEffect } from 'react';
import { RefreshCw, Power, AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

export default function RestartButton() {
    const [status, setStatus] = useState<'idle' | 'confirming' | 'restarting' | 'restarting_done'>('idle');
    const [message, setMessage] = useState('');

    const handleRestart = async () => {
        setStatus('restarting');
        setMessage('指令已发送，正在关闭当前进程...');

        try {
            const res = await fetch('http://localhost:8000/api/system/restart', { method: 'POST' });
            const data = await res.json();
            
            if (data.success) {
                // Wait for backend to go down and come back up
                await checkBackendStatus();
            } else {
                setStatus('idle');
                alert('重启请求失败: ' + data.error);
            }
        } catch (err) {
            // Error is expected as the connection closes
            console.log('Backend connection closed for restart.');
            await checkBackendStatus();
        }
    };

    const checkBackendStatus = async () => {
        setMessage('后台程序正在重新载入，等待连接握手...');
        
        let attempts = 0;
        const maxAttempts = 30; // 30 seconds max
        
        const poll = async () => {
            try {
                const res = await fetch('http://localhost:8000/api/portfolio');
                if (res.ok) {
                    setStatus('restarting_done');
                    setMessage('系统已恢复，正在重载界面...');
                    setTimeout(() => {
                        window.location.reload();
                    }, 1000);
                    return;
                }
            } catch (e) {
                // Still down
            }
            
            attempts++;
            if (attempts < maxAttempts) {
                setTimeout(poll, 1000);
            } else {
                setStatus('idle');
                alert('重启超时，请手动检查后端窗口。');
            }
        };
        
        setTimeout(poll, 2500); // Give it a sec to actually shut down
    };

    return (
        <div className="w-full mt-4">
            <button 
                onClick={() => setStatus('confirming')}
                className="w-full flex items-center justify-center gap-3 p-4 bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/20 rounded-2xl transition-all group"
            >
                <Power className="w-4 h-4 group-hover:scale-110 transition-transform" />
                <span className="text-[10px] font-black uppercase tracking-[0.2em]">重启后端核心</span>
            </button>

            <AnimatePresence>
                {status !== 'idle' && (
                    <motion.div 
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 bg-black/80 backdrop-blur-md z-[100] flex items-center justify-center p-6"
                    >
                        <motion.div 
                            initial={{ scale: 0.9, y: 20 }}
                            animate={{ scale: 1, y: 0 }}
                            className="bg-[#0d0d0f] border border-white/10 p-8 rounded-[2.5rem] max-w-md w-full shadow-2xl"
                        >
                            {status === 'confirming' && (
                                <div className="text-center">
                                    <div className="w-20 h-20 bg-rose-500/20 rounded-full flex items-center justify-center mx-auto mb-6">
                                        <AlertTriangle className="w-10 h-10 text-rose-500" />
                                    </div>
                                    <h3 className="text-xl font-black text-white mb-2">确认重启系统？</h3>
                                    <p className="text-slate-400 text-sm mb-8">
                                        重启将中断所有当前监控任务，并重新加载底层 Python 环境（包括 API 路由修改）。通常需要 5-10 秒。
                                    </p>
                                    <div className="flex gap-4">
                                        <button 
                                            onClick={() => setStatus('idle')}
                                            className="flex-1 py-4 bg-white/5 hover:bg-white/10 text-white font-bold rounded-2xl transition-all"
                                        >
                                            取消
                                        </button>
                                        <button 
                                            onClick={handleRestart}
                                            className="flex-1 py-4 bg-rose-600 hover:bg-rose-500 text-white font-bold rounded-2xl transition-all shadow-lg shadow-rose-600/20"
                                        >
                                            立即重启
                                        </button>
                                    </div>
                                </div>
                            )}

                            {(status === 'restarting' || status === 'restarting_done') && (
                                <div className="text-center py-6">
                                    <div className="relative mb-10">
                                        <div className={`w-24 h-24 border-4 ${status === 'restarting_done' ? 'border-emerald-500/20' : 'border-rose-500/20 border-t-rose-500'} rounded-full animate-spin mx-auto transition-colors`} />
                                        <div className="absolute inset-0 flex items-center justify-center">
                                            {status === 'restarting_done' ? (
                                                <CheckCircle2 className="w-12 h-12 text-emerald-500" />
                                            ) : (
                                                <Loader2 className="w-10 h-10 text-rose-500 animate-pulse" />
                                            )}
                                        </div>
                                    </div>
                                    <h4 className="text-white font-black tracking-widest text-sm uppercase mb-3">
                                        {status === 'restarting_done' ? 'RESTART_SUCCESS' : 'SYSTEM_RESTARTING'}
                                    </h4>
                                    <p className="text-slate-500 text-xs font-mono italic animate-pulse">
                                        {message}
                                    </p>
                                </div>
                            )}
                        </motion.div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}
