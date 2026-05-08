# Fortune Agent（八字多模型分析）

一个“排盘与解读分离”的八字分析 Agent：

- **排盘**由确定性工具完成（`lunar_python`），避免模型自行排盘误差。
- **解读**由多模型协作完成（先定格局/用神，再看大运流年并验证前事）。
- **冲突处理**采用“短 prompt 仲裁”，不整轮回滚，控制成本与稳定性。

---

## 方法总览

当前核心方法在 `workflow.py`，是一个 5 步流水线：

1. **Step 0 排盘 Tool（确定性）**
   - 输入：公历出生年月日时分 + 性别
   - 输出：四柱、起运信息、大运表、流年表
   - 约束：干支以 tool 为准，LLM 不做排盘

2. **Step 1 多模型 Round 1：确定格局 + 用神候选**
   - 模型角色参考 `_agents()`（GPT / Gemini / Qwen / DeepSeek）
   - 每个模型独立给出：格局判断、用神候选、证据与不确定点

3. **Step 1.5 合并共识**
   - 使用整合模型把 Round 1 的输出收敛为：
     - 主格局结论
     - 用神候选列表
     - 主候选 `primary_hypothesis_id`

4. **Step 2 Round 2：大运/流年解读 + 前事验证**
   - 基于 tool 的大运/流年表进行解读
   - 将用户三条前事逐条对齐到年份干支
   - 若发现“前事 ↔ 用神 ↔ 流年解释”不一致，写入 `conflicts`

5. **Step 3 冲突仲裁（局部修复）**
   - 对每条 conflict 发起短 prompt 仲裁（`reconcile_one`）
   - 仲裁四种结果：
     - `update_use_gods`
     - `patch_year_interpretation`
     - `needs_user_clarification`
     - `accept_as_low_confidence`
   - 仅在 `update_use_gods` 时重跑 Step 2，一般不回到 Step 1

6. **Step 4 最终报告**
   - 输出用户可读报告，包含维度分析、前事对照、评分与未来提醒

---

## 评分与分析策略（当前版本）

`prompts.py` 已强化为：

- 分维度分析：**事业、财运、婚恋、健康、学业、贵人、子女、综合**
- 严格百分位映射（1~10 分对应人群区间）
- 反集中化规则（避免评分全部集中在 5/6）

> 说明：这部分主要通过提示词控制，后续可在 `workflow.py` 再加“评分后校验器”做二次修正。

---

## 项目结构

```text
fortune_agent/
├── streamlit_app.py      # Web 入口（Streamlit）
├── workflow.py           # 核心方法流程
├── prompts.py            # 全部提示词与输出 schema
├── tools/
│   └── paipan.py         # 确定性排盘工具
├── openrouter_client.py  # OpenRouter 调用封装
├── config.py             # 模型与默认配置
├── main.py               # 命令行示例入口
├── requirements.txt
└── V1/                   # 历史版本代码
```

---

## 快速开始

### 1) 安装依赖

```bash
pip install -r requirements.txt
```

### 2) 配置 API Key

先复制模板，再填写你自己的 key：

```bash
cp .env.example .env
```

然后编辑 `.env`：

```env
OPENROUTER_API_KEY=your_key_here
```

### 3) 运行 Web 版（推荐）

```bash
streamlit run streamlit_app.py
```

### 4) 运行命令行版（示例）

```bash
python main.py
```

---

## Streamlit 输入约定

网页端当前要求：

- 出生信息（公历）：
  - 出生日期
  - 出生小时（0-23）
  - 出生分钟（0-59）
  - 性别
- 前事：固定 3 条
  - 事件描述
  - 年份（4 位）
  - 体感（吉/凶/动/平）
- 模型设置：
  - 整合/第二轮模型（下拉）
  - 终稿模型（下拉）

API Key 不在网页中手动输入，默认只从 `.env` 读取。

---

## 输出文件

每次运行会在 `results_v2/<timestamp>/` 生成：

- `step0_inputs.json`：排盘与输入
- `step1_round1_raw.json`：多模型原始结果
- `step1_round1_consensus.json`：Round 1 共识
- `step2_round2.json`：大运流年与前事对齐
- `step3_reconcile.json`：冲突仲裁日志
- `final_report.md`：最终报告

---

## 设计原则

1. **排盘与解读解耦**：用工具负责“算”，模型负责“解释”
2. **先定命局，再看时序**：先格局/用神，再大运流年
3. **前事用于验算，不用于倒推编造**
4. **冲突局部修复优先**：避免整轮重跑与结果震荡
5. **结果可追溯**：每步产物落盘，方便复盘与调参

---

## 注意事项

- 本项目用于研究与体验，不构成现实决策建议。
- `.env`、`results/`、`results_v2/` 已在 `.gitignore` 中忽略，避免把密钥和个人案例数据提交到仓库。
- 若要提升稳定性，建议增加：
  - 评分分布后校验器（程序层）
  - 更严格的输出 schema 校验与自动重试
  - 大运/流年边界规则（真太阳时、子时口径）参数化

