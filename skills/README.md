# StockAI Skills 插件系统

每个 Skill 是一个独立的模块目录，包含以下文件：

```
skills/
├── financial-report/       # 财报分析
│   ├── skill.json          # 元数据
│   ├── prompt.md           # 系统提示词
│   └── index.js            # 主逻辑（可选）
├── technical-indicator/    # 技术指标
│   ├── skill.json
│   └── prompt.md
├── dragon-tiger/           # 龙虎榜分析
│   ├── skill.json
│   └── prompt.md
└── ...
```

## skill.json 格式

```json
{
  "id": "financial-report",
  "name": "财报分析",
  "version": "1.2.0",
  "description": "爬取并分析上市公司财报数据",
  "author": "StockAI",
  "capabilities": ["web_crawl", "data_analysis"],
  "prompt": "prompt.md",
  "config_schema": {
    "deep_analysis": { "type": "boolean", "default": false }
  }
}
```

## Skill 加载机制

1. 用户点击"安装" → 写入 `installed_skills` 表
2. AI 对话时 → 根据已安装的 Skills 动态组合 system prompt
3. 如果 Skill 有 `index.js` → 可作为 MCP Server 独立运行
