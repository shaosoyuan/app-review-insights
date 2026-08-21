# App Review Insights

将真实的 App Store 用户评论转化为可执行的产品方案 —— 从数据采集到 PRD 和测试用例，由 LLM 驱动的语义分析引擎完成。

## 功能特性

- **数据采集**：通过 iTunes RSS Feed API 获取评论（公开接口，无需 API Key）
- **评论清洗**：去重（精确匹配 + 模糊匹配）、文本归一化、语言检测
- **LLM 驱动分析**：动态话题发现、问题聚合、基于证据的发现
- **PRD 生成**：产品需求文档，包含版本规划、优先级和可追溯性
- **测试用例生成**：测试用例与需求和源用户评论关联
- **可追溯性验证**：完整链路 评论 -> 发现 -> 需求 -> 测试用例
- **文件导入**：支持上传 JSON 和 CSV 格式的评论数据
- **降级模式**：未配置 LLM 时自动使用基于规则的分析

## 快速开始

### 前置条件

- Python 3.10+
- 一个 OpenAI 兼容的 API Key（可选，但推荐用于完整的 LLM 驱动分析）

### 安装

```bash
git clone https://github.com/shaosoyuan/app-review-insights.git
cd app-review-insights

python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# 编辑 .env 填入你的 API Key
```

### 启动

```bash
cd backend
python main.py
```

应用将在 `http://127.0.0.1:8000` 启动。

## 使用方法

1. **输入 App Store 链接**：粘贴任意美区 App Store 应用链接
2. **设置分析目标**（可选）：例如"订阅转化"、"低分评论"
3. **点击"开始分析"**：实时查看执行进度
4. **查看结果**：浏览评论、发现、PRD、测试用例、可追溯性等标签页

### 上传自定义数据

点击上传区域导入 `.json` 或 `.csv` 格式的评论数据。

**JSON 格式：**
```json
[
  {
    "review_id": "12345",
    "author": "JohnDoe",
    "rating": 4,
    "title": "Great app",
    "content": "Really helpful for workouts...",
    "version": "7.3.1",
    "date": "2024-01-15"
  }
]
```

**CSV 格式：** 列名 `review_id, author, rating, title, content, version, date`

## 项目结构

```
app-review-insights/
├── backend/
│   ├── main.py          # FastAPI 服务器，SSE 流式推送
│   ├── models.py        # Pydantic 数据模型
│   ├── collector.py     # iTunes RSS Feed API 采集器
│   ├── cleaner.py       # 评论清洗与去重
│   └── analyzer.py      # LLM 驱动的分析引擎
├── frontend/
│   ├── index.html       # 单页应用 UI
│   └── sample_reviews.json  # 静态样本数据
├── data/
│   ├── cache/           # 运行时评论缓存
│   └── sample/          # 样本数据（规范副本）
├── requirements.txt
├── .env.example
├── run.sh               # 快速启动脚本
└── README.md
```

## 数据采集方式

评论通过 **iTunes RSS Customer Reviews Feed** 获取：

```
https://itunes.apple.com/{country}/rss/customerreviews/page={n}/id={appId}/sortby=mostrecent/json
```

- **数据源**：Apple 公开 RSS Feed（无需认证）
- **限制**：最多获取最近 ~500 条评论（10 页 x 每页约 50 条）
- **覆盖范围**：默认美区 App Store
- **频率控制**：内置请求间隔，避免触发限流

应用元数据通过 iTunes Lookup API 获取：
```
https://itunes.apple.com/lookup?id={appId}
```

## LLM 配置

支持任意 OpenAI 兼容的 API：

| 服务商 | Base URL | 模型示例 |
|--------|----------|----------|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |

在 `.env` 中配置：
```env
OPENAI_API_KEY=sk-your-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```

### 防幻觉措施

- LLM 被要求仅使用提供的评论 ID 和摘录
- 每条发现都包含来源评论 ID 以供验证
- 必须给出置信度分数和不确定性标记
- 明确标注存在矛盾的证据
- LLM 不可用或失败时自动降级为规则分析

## 技术栈

- **后端**：Python、FastAPI、httpx、OpenAI SDK
- **前端**：HTML、CSS、JavaScript（原生，无构建步骤）
- **数据源**：iTunes RSS Feed API
- **LLM**：任意 OpenAI 兼容 API

## 许可证

MIT
