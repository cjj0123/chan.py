import pandas as pd
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
import os
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Model Definitions ---
class MLPModel(nn.Module):
    def __init__(self, input_size):
        super(MLPModel, self).__init__()
        self.net = nn.Sequential(
            nn.Linear(input_size, 64),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 1)
        )

    def forward(self, x):
        return self.net(x)

def train_standalone(target_label="label_7p_30d"):
    data_dir = "stock_cache/ml_data"
    csv_path = os.path.join(data_dir, "train_samples.csv")
    
    logger.info(f"Loading data from {csv_path}...")
    df = pd.read_csv(csv_path).fillna(0)
    
    # Sort by time
    logger.info("Parsing dates...")
    df['time'] = pd.to_datetime(df['time'], format='mixed')
    df = df.sort_values('time')
    
    label_cols = [c for c in df.columns if c.startswith("label_")]
    X = df.drop(columns=label_cols + ["code", "time"])
    y = df[target_label]
    
    split_idx = int(len(df) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
    
    logger.info(f"Train: {X_train.shape}, Test: {X_test.shape}")
    
    mean = X_train.mean()
    std = X_train.std() + 1e-7
    X_train_norm = (X_train - mean) / std
    X_test_norm = (X_test - mean) / std
    
    # Save norm params
    norm_params = {"mean": mean.to_dict(), "std": std.to_dict()}
    with open(os.path.join(data_dir, "mlp_norm.json"), 'w') as f:
        json.dump(norm_params, f)

    device = torch.device("cpu")
    logger.info(f"Device: {device}")
    
    # Tensors
    X_tensor = torch.tensor(X_train_norm.values, dtype=torch.float32)
    y_tensor = torch.tensor(y_train.values, dtype=torch.float32).unsqueeze(1)
    
    dataset = TensorDataset(X_tensor, y_tensor)
    loader = DataLoader(dataset, batch_size=64, shuffle=True)
    
    model = MLPModel(X_train.shape[1]).to(device)
    criterion = nn.BCEWithLogitsLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)
    
    logger.info("Starting training loop...")
    for epoch in range(100):
        model.train()
        total_loss = 0
        for batch_x, batch_y in loader:
            optimizer.zero_grad()
            outputs = model(batch_x)
            loss = criterion(outputs, batch_y)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
        
        if epoch % 10 == 0:
            logger.info(f"Epoch {epoch}/100, Loss: {total_loss:.4f}")
            
    # Save
    torch.save(model.state_dict(), os.path.join(data_dir, "model_mlp.pth"))
    logger.info("✅ Standalone MLP training complete.")

    # --- Evaluation ---
    logger.info("📊 Starting Evaluation on Test Set...")
    model.eval()
    with torch.no_grad():
        X_test_tensor = torch.tensor(X_test_norm.values, dtype=torch.float32).to(device)
        logits = model(X_test_tensor)
        y_prob = torch.sigmoid(logits).cpu().numpy().flatten()
    
    y_true = y_test.values
    
    from sklearn.metrics import roc_auc_score, precision_score
    
    threshold = 0.5
    y_pred = (y_prob >= threshold).astype(int)
    
    auc = roc_auc_score(y_true, y_prob) if len(np.unique(y_true)) > 1 else 0.5
    win_rate = precision_score(y_true, y_pred, zero_division=0)
    trade_count = int(sum(y_pred))
    
    # Calculate CalScore
    profits = []
    for yt, yp in zip(y_true, y_pred):
        if yp == 1:
            if yt == 1: profits.append(0.03)
            else: profits.append(-0.015)
            
    net_profit = sum(profits)
    real_win_rate = sum([1 for p in profits if p > 0]) / len(profits) if profits else 0.0
    
    cum_profit = np.cumsum(profits)
    peak = np.maximum.accumulate(cum_profit) if len(cum_profit) > 0 else np.array([0])
    drawdown = peak - cum_profit if len(cum_profit) > 0 else np.array([0])
    max_dd = np.max(drawdown) if len(drawdown) > 0 else 0
    
    cal_score = (net_profit * real_win_rate) / (1 + max_dd) if profits else 0.0
    
    logger.info(f"📈 [MLP 评估] AUC: {auc:.4f} | 胜率: {win_rate:.2%} | 触发次数: {trade_count} | CalScore: {cal_score:.4f}")

if __name__ == "__main__":
    train_standalone()
