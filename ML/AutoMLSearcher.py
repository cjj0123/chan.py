import os
import sys
import json
import logging
import argparse

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ML.ModelTrainer import ModelTrainer

import optuna

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

class AutoMLSearcher:
    def __init__(self, target_label="label_3p_15d"):
        self.trainer = ModelTrainer()
        self.target_label = target_label
        self.results_dir = "stock_cache/ml_data/optuna"
        os.makedirs(self.results_dir, exist_ok=True)

    def optimize_xgboost(self, n_trials=50):
        if n_trials <= 0: return {}
        logger.info(f"🚀 Starting XGBoost optimization for {self.target_label}...")
        
        def objective(trial):
            params = {
                'objective': 'binary:logistic',
                'eval_metric': 'auc',
                'max_depth': trial.suggest_int('max_depth', 3, 10),
                'eta': trial.suggest_float('eta', 0.01, 0.3, log=True),
                'subsample': trial.suggest_float('subsample', 0.5, 1.0),
                'colsample_bytree': trial.suggest_float('colsample_bytree', 0.5, 1.0),
                'min_child_weight': trial.suggest_int('min_child_weight', 1, 10),
                'gamma': trial.suggest_float('gamma', 0, 1.0),
                'nthread': 4
            }
            threshold = trial.suggest_float('threshold', 0.4, 0.8)
            # 训练时不保存，仅获取分数
            score = self.trainer.train_xgboost(self.target_label, params=params, threshold=threshold, save=False)
            return score

        study = optuna.create_study(direction='maximize')
        study.optimize(objective, n_trials=n_trials)
        
        logger.info(f"✅ XGBoost Optimization Complete!")
        logger.info(f"Best Score: {study.best_value}")
        logger.info(f"Best Params: {study.best_params}")
        
        self._save_results("xgb", study)
        return study.best_params

    def optimize_lightgbm(self, n_trials=50):
        if n_trials <= 0: return {}
        logger.info(f"🚀 Starting LightGBM optimization for {self.target_label}...")
        
        def objective(trial):
            params = {
                'objective': 'binary',
                'metric': 'auc',
                'boosting_type': 'gbdt',
                'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3, log=True),
                'num_leaves': trial.suggest_int('num_leaves', 20, 150),
                'feature_fraction': trial.suggest_float('feature_fraction', 0.5, 1.0),
                'bagging_fraction': trial.suggest_float('bagging_fraction', 0.5, 1.0),
                'bagging_freq': trial.suggest_int('bagging_freq', 1, 10),
                'min_data_in_leaf': trial.suggest_int('min_data_in_leaf', 5, 50),
                'is_unbalance': True,
                'verbose': -1
            }
            threshold = trial.suggest_float('threshold', 0.4, 0.8)
            score = self.trainer.train_lightgbm(self.target_label, params=params, threshold=threshold, save=False)
            return score

        study = optuna.create_study(direction='maximize')
        study.optimize(objective, n_trials=n_trials)
        
        logger.info(f"✅ LightGBM Optimization Complete!")
        logger.info(f"Best Score: {study.best_value}")
        logger.info(f"Best Params: {study.best_params}")
        
        self._save_results("lgb", study)
        return study.best_params

    def finalize_models(self):
        """加载最优参数并重新训练保存模型"""
        logger.info("🎯 Finalizing models with best parameters...")
        for m_type in ["xgb", "lgb"]:
            param_file = os.path.join(self.results_dir, f"best_params_{m_type}.json")
            if not os.path.exists(param_file): continue
            
            with open(param_file, 'r') as f:
                data = json.load(f)
                best_params = data["best_params"]
                threshold = best_params.pop("threshold", 0.5)
                
                if m_type == "xgb":
                    self.trainer.train_xgboost(self.target_label, params=best_params, threshold=threshold, save=True)
                else:
                    self.trainer.train_lightgbm(self.target_label, params=best_params, threshold=threshold, save=True)

    def _save_results(self, model_type, study):
        result_file = os.path.join(self.results_dir, f"best_params_{model_type}.json")
        with open(result_file, 'w') as f:
            json.dump({
                "best_params": study.best_params,
                "best_score": study.best_value
            }, f, indent=4)
        logger.info(f"📊 Best params saved to {result_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default="all", choices=["xgb", "lgb", "all"], help="Choose model to optimize")
    parser.add_argument("--trials", type=str, default="50", help="Number of trials per model")
    parser.add_argument("--label", type=str, default="label_3p_15d", help="Target label")
    args = parser.parse_args()
    
    searcher = AutoMLSearcher(target_label=args.label)
    n_trials = int(args.trials)
    
    if args.model in ["xgb", "all"]:
        searcher.optimize_xgboost(n_trials=n_trials)
    if args.model in ["lgb", "all"]:
        searcher.optimize_lightgbm(n_trials=n_trials)
        
    searcher.finalize_models()
