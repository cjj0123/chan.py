# API 配置安全指南

## 安全最佳实践

为了保护您的API密钥安全，请遵循以下最佳实践：

### 1. 使用环境变量（推荐）

最安全的方式是使用环境变量来存储API密钥，而不是在文件中存储。

**设置环境变量：**

```bash
# 在 ~/.bashrc, ~/.zshrc 或其他 shell 配置文件中添加
export DASHSCOPE_API_KEY="your_actual_dashscope_api_key"
export GOOGLE_API_KEY="your_actual_google_api_key"
```

然后重新加载配置文件：
```bash
source ~/.bashrc  # 或 source ~/.zshrc
```

### 2. 使用独立的配置文件（次选）

如果您必须使用配置文件，请创建一个独立的配置文件并确保它被添加到 `.gitignore` 中。

**创建配置文件：**
```bash
cp api_config.env.example api_config.env
```

**编辑 `api_config.env` 文件：**
```env
DASHSCOPE_API_KEY=your_actual_dashscope_api_key
GOOGLE_API_KEY=your_actual_google_api_key
```

**确保 `.gitignore` 包含：**
```
api_config.env
```

### 3. 邮件配置

邮件配置文件 `email_config.env` 现在只包含邮件相关的配置，不包含API密钥。

## 重要提醒

- **永远不要**将包含真实API密钥的文件提交到版本控制系统
- **定期轮换**您的API密钥
- **限制API密钥的权限**，只授予必要的最小权限
- 如果怀疑密钥泄露，立即在相应的服务提供商处撤销并生成新的密钥

## 验证配置

程序会自动从环境变量中读取API密钥。如果环境变量未设置，程序会显示警告但继续运行（可能降级到mock模式）。