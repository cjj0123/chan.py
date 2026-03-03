```python
def scan_and_trade(self):
    """
    批量扫描并交易：收集所有信号，按优先级执行
    """
    # 获取所有自选股
    watchlist_stocks = self.get_watchlist_stocks()
    if not watchlist_stocks:
        print("没有自选股数据")
        return
    
    print(f"开始扫描 {len(watchlist_stocks)} 只自选股...")
    
    # 收集所有有效信号
    all_signals = []
    
    for stock_info in watchlist_stocks:
        code = stock_info['code']
        name = stock_info['name']
        
        print(f"\n正在分析股票: {code} - {name}")
        
        try:
            # 获取当前持仓信息
            current_position = self.get_current_position(code)
            
            # 获取技术分析结果
            result = self.analyze_stock(code, name)
            if not result or not result.get('success'):
                print(f"分析失败: {code} - {result.get('error', '未知错误')}")
                continue
            
            visual_score = result.get('visual_score', 0)
            chan_result = result.get('chan_result')
            chart_paths = result.get('chart_paths', {})
            
            # 只处理评分达到阈值的信号
            if visual_score < 70:
                print(f"{code} 评分 {visual_score} 低于阈值 70，跳过")
                continue
            
            # 判断买卖信号
            has_position = current_position > 0
            can_sell = has_position and chan_result and chan_result.get('sell_signal')
            can_buy = not has_position and chan_result and chan_result.get('buy_signal')
            
            signal_data = {
                'code': code,
                'name': name,
                'score': visual_score,
                'chan_result': chan_result,
                'stock_info': stock_info,
                'chart_paths': chart_paths,
                'current_position': current_position
            }
            
            if can_sell:
                signal_data['is_buy'] = False
                all_signals.append(signal_data)
                print(f"收集到卖出信号: {code} - 评分 {visual_score}")
            elif can_buy:
                signal_data['is_buy'] = True
                all_signals.append(signal_data)
                print(f"收集到买入信号: {code} - 评分 {visual_score}")
            else:
                print(f"{code} 无有效买卖信号")
                
        except Exception as e:
            print(f"处理股票 {code} 时发生异常: {str(e)}")
            continue
    
    print(f"\n共收集到 {len(all_signals)} 个有效信号")
    
    if not all_signals:
        print("没有收集到任何有效信号，结束扫描")
        return
    
    # 分离买卖信号
    sell_signals = [sig for sig in all_signals if not sig['is_buy']]
    buy_signals = [sig for sig in all_signals if sig['is_buy']]
    
    # 按评分从高到低排序
    sell_signals.sort(key=lambda x: x['score'], reverse=True)
    buy_signals.sort(key=lambda x: x['score'], reverse=True)
    
    print(f"卖出信号 {len(sell_signals)} 个，买入信号 {len(buy_signals)} 个")
    
    # 获取初始可用资金
    available_funds = self.get_available_funds()
    print(f"初始可用资金: {available_funds:.2f}")
    
    # 执行卖出操作
    for signal in sell_signals:
        code = signal['code']
        name = signal['name']
        score = signal['score']
        current_position = signal['current_position']
        chan_result = signal['chan_result']
        chart_paths = signal['chart_paths']
        
        print(f"\n执行卖出操作: {code} - {name} (评分: {score})")
        
        try:
            # 执行卖出
            sell_success, sell_msg = self.execute_sell_order(
                code=code,
                quantity=current_position,
                reason=f"视觉评分 {score}, 卖出信号"
            )
            
            if sell_success:
                # 卖出成功，资金增加
                sell_amount = self.get_current_price(code) * current_position
                available_funds += sell_amount
                print(f"卖出成功: {code}, 数量: {current_position}, 金额: {sell_amount:.2f}")
                print(f"更新后可用资金: {available_funds:.2f}")
                
                # 记录交易日志
                self.log_trade({
                    'type': 'SELL',
                    'code': code,
                    'name': name,
                    'quantity': current_position,
                    'price': self.get_current_price(code),
                    'amount': sell_amount,
                    'score': score,
                    'reason': f"视觉评分 {score}",
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'chart_paths': chart_paths
                })
                
                # 发送通知
                self.send_notification(
                    title=f"卖出成功 - {code}",
                    message=f"{name}\n数量: {current_position}\n价格: {self.get_current_price(code):.2f}\n评分: {score}"
                )
                
            else:
                print(f"卖出失败: {code} - {sell_msg}")
                
        except Exception as e:
            print(f"执行卖出操作 {code} 时发生异常: {str(e)}")
    
    # 执行买入操作（在卖出完成后）
    for signal in buy_signals:
        code = signal['code']
        name = signal['name']
        score = signal['score']
        chan_result = signal['chan_result']
        chart_paths = signal['chart_paths']
        
        print(f"\n检查买入操作: {code} - {name} (评分: {score})")
        
        try:
            # 获取当前价格和建议购买数量
            current_price = self.get_current_price(code)
            suggested_quantity = int(available_funds * 0.1 / current_price)  # 建议使用10%资金
            
            # 如果建议数量为0，则至少买1股（如果资金够）
            if suggested_quantity == 0 and available_funds >= current_price:
                suggested_quantity = 1
            
            required_funds = current_price * suggested_quantity
            
            if required_funds > available_funds:
                print(f"资金不足，需要: {required_funds:.2f}, 可用: {available_funds:.2f}")
                continue
            
            # 执行买入
            buy_success, buy_msg = self.execute_buy_order(
                code=code,
                quantity=suggested_quantity,
                reason=f"视觉评分 {score}, 买入信号"
            )
            
            if buy_success:
                # 买入成功，资金减少
                available_funds -= required_funds
                print(f"买入成功: {code}, 数量: {suggested_quantity}, 金额: {required_funds:.2f}")
                print(f"更新后可用资金: {available_funds:.2f}")
                
                # 记录交易日志
                self.log_trade({
                    'type': 'BUY',
                    'code': code,
                    'name': name,
                    'quantity': suggested_quantity,
                    'price': current_price,
                    'amount': required_funds,
                    'score': score,
                    'reason': f"视觉评分 {score}",
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'chart_paths': chart_paths
                })
                
                # 发送通知
                self.send_notification(
                    title=f"买入成功 - {code}",
                    message=f"{name}\n数量: {suggested_quantity}\n价格: {current_price:.2f}\n评分: {score}"
                )
                
            else:
                print(f"买入失败: {code} - {buy_msg}")
                
        except Exception as e:
            print(f"执行买入操作 {code} 时发生异常: {str(e)}")
    
    print("\n扫描和交易完成")
```