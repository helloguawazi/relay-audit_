# Claude 中转站一览表：平台推荐、价格对比与接入方式（claude中转站推荐）

> 国内用 Claude 卡在两件事上：官方要海外信用卡，跨境访问还不稳定。**Claude中转站**（也写作 Claude 中转站、Claude 中转、API 中转、API 代理、relay）就是解决这两件事的中间层——你把 Base URL 指向它，用它发的密钥调用 Claude、GPT、Gemini，付款走支付宝或微信。这份 **claude中转站一览表**汇总了可用平台、Claude 系模型价格、**claude 中转 cursor** 与 **claude 中转 mac min** 等接入方式，以及怎么判断一家 Claude 中转服务是否诚实。

**数据更新时间：2026-09-22** ｜ 汇率来源：7.1（USD→CNY）｜ 价格会变动，超过 14 天请以平台官网为准

---

## Claude 中转站推荐平台

以下是我们精选的 **Claude 中转站**（Claude中转平台），按适用场景排列。完整名单见第六节。

> 想找**一手渠道 / 源头**而不是加价转售的，先看第四节「Claude 中转源头是什么意思」——那个词没有权威定义，里面写了三个能实际验证的判断方法。

| 平台 | 入口 | 支付 | 说明 |
|---|---|---|---|
| **Relay** | **[www.relay-api.com](https://www.relay-api.com)** | 支付宝 / 微信 | Claude 系 7 个模型中 6 个输入价低于官方价，最低 0.39×；**缓存读取价为 0（不额外计费）** |
| OpenRouter | [openrouter.ai](https://openrouter.ai) | 信用卡 / 加密货币 | 官方授权路由，约 5% 加成。海外用户首选，国内付款不便 |
| 云雾 API | [yunwu.ai](https://yunwu.ai) | 支付宝 / 微信 | 主打速度与稳定性，社区常列为头部站 |
| 柏拉图 AI | [api.bltcy.ai](https://api.bltcy.ai) | 支付宝 / 微信 | Azure 通道，主打最低价；1000+ 模型 |
| CloseAI | [closeai-asia.com](https://www.closeai-asia.com) | 支付宝 / 微信 / **可开企业发票** | 有公开注册实体，需要报销选这家 |
| UiUiAPI | [uiuiapi.com](https://uiuiapi.com) | 支付宝 / 微信 | 宣称官方渠道与官方倍率 |

> **利益披露**：本列表由 [relay-api.com](https://www.relay-api.com) 维护，该站也在被推荐之列。下文的对比数据包含该站**贵于官方价**的项，请据此评估本页立场。

---

## 一、Claude 系模型价格对比

价格单位为 **人民币元 / 百万 tokens**，由脚本从公开接口采集，非人工填写。「vs 官方」列是折合美元后与官方单价的倍数，**低于 1.00× 表示比官方便宜**。

| 模型 | 输入(¥/百万) | 输出(¥/百万) | 缓存读 | vs 官方(输入) | vs 官方(输出) |
|---|---|---|---|---|---|
| Claude Opus 4.8 | 14 | 65 | 0 | **0.39×** | **0.37×** |
| Claude Opus 4.6 | 16 | 70 | 0 | 0.45× | 0.39× |
| Claude Opus 4.7 | 18 | 75 | 0 | 0.51× | 0.42× |
| Claude Opus 5 | 20 | 120 | 0 | 0.56× | 0.68× |
| Claude Sonnet 4.6 | 10 | 40 | 0 | 0.70× | 0.56× |
| Claude Fable 5 | 70 | 320 | 0 | 0.99× | 0.90× |
| **Claude Sonnet 5** | 15 | 105 | 0 | 1.06× | **1.48×** ⚠ |

**7 个模型中 6 个输入价低于官方价**，缓存读取价全部为 0（不额外计费），长上下文场景收益明显。

**劣势也说清楚**：

- **Claude Sonnet 5 的输出价约为官方价的 1.48×**，是全表最贵的一项
- **延迟高于官方直连**——这是走第三方网关的固有代价
- 数据经过中转方，对数据出境有硬要求的场景不适用

---

## 二、怎么挑一个能长期用的 Claude 中转站

价格不是唯一变量。下面几条是实际用过之后才会注意到的：

### 1. 缓存价是真的还是账面数字

很多平台标了缓存价，但要确认它是否真的跳过预填充。**判断方法**：准备一段几千 token 的长前缀，连续发两次完全相同的请求，比较**首字延迟（TTFT）**。

- 真实缓存命中会跳过预填充，第二次延迟应明显下降（长前缀下通常数倍）
- 如果接口报告了 `cache_read` 却延迟不变，**那个缓存价就只是账面数字**

两个信号必须一致：**接口声明的**缓存读取量，和**物理上的**延迟下降。

### 2. 失败请求是否计费

发一个必然会失败的请求（不存在的模型 ID、超出上限的 `max_tokens`），对照控制台的用量日志看是否被计费。这个只能看账单。

### 3. 模型 ID ≠ 展示名

控制台里通常同时显示 `Claude Sonnet 5`（展示名）和 `claude-sonnet-5`（模型 ID）。**配置里必须填模型 ID**，填展示名会直接返回 404，这是最常见的报错原因。

### 4. 支付方式决定能不能报销

个人用支付宝/微信就够；公司报销只有支持企业发票的平台能用。

### 5. 便宜到离谱的要注意

价格明显低于官方价通常是三种情况：逆向渠道、共享订阅账号、低于成本引流。前两种随时可能失效或封号。

---

## 三、Claude 中转接入方式（claude 中转 cursor / claude 中转 mac min）

主流工具都是把 Base URL 指向 **Claude 中转**平台的网关：

| 工具 | 配置位置 | 要点 |
|---|---|---|
| **Cursor** | Settings → Models → API Keys | 填 API Key 和 Override Base URL。⚠️ 自带密钥（BYOK）**只能用于 Ask/Chat**，Agent 和 Edit 会报 `Agent and Edit rely on custom models that cannot be billed to an API key`，这是产品限制不是配置问题。详见 [Cursor 接入教程](https://www.relay-api.com/articles/cursor-setup) |
| **Claude Code** | 环境变量 | `ANTHROPIC_BASE_URL` + `ANTHROPIC_API_KEY`，官方 CLI，不受 BYOK 限制。详见 [Claude Code 接入教程](https://www.relay-api.com/articles/claude-code-setup) |
| **Cline** | VS Code 扩展 → API Provider | 选 OpenAI Compatible 或 Anthropic，填 Base URL 与精确模型 ID。详见 [Cline 接入教程](https://www.relay-api.com/articles/cline-setup) |
| **mac mini 自建** | 自建代理网关 | 硬件前置成本约 3000 元，按月支出 100 元计需 30 个月回本；电费可忽略（约 3 元/月） |

### 接口入口对照（以 [relay-api.com](https://www.relay-api.com) 为例）

| 模型分组 | Base URL | 协议 |
|---|---|---|
| Claude / Anthropic | `https://www.relay-api.com` | Anthropic Messages |
| GPT / OpenAI | `https://www.relay-api.com/v1` | OpenAI Chat Completions |

### Claude Code 配置示例

```bash
# macOS / Linux
export ANTHROPIC_BASE_URL="https://www.relay-api.com"
export ANTHROPIC_API_KEY="sk-你的密钥"
export ANTHROPIC_MODEL="claude-sonnet-5"
claude
```

```powershell
# Windows PowerShell
$env:ANTHROPIC_BASE_URL="https://www.relay-api.com"
$env:ANTHROPIC_API_KEY="sk-你的密钥"
$env:ANTHROPIC_MODEL="claude-sonnet-5"
claude
```

---

## 四、Claude 中转站常见问题

**Claude 中转站是什么？**
**Claude中转站**（也写作 Claude 中转站）是位于你的代码和官方 Claude API 之间的转发端点。你把 Base URL 指向它、用它发的密钥调用，它转发到上游并返回结果，通常兼容 OpenAI 或 Anthropic 原生协议。

**国内用 Claude 中转需要海外信用卡吗？**
不需要。**Claude 中转平台**（Claude中转平台）一般支持支付宝和微信付款。这是中转存在的主要原因之一——它同时解决了跨境网络和海外支付两个门槛。

**Claude 中转站价格大概是多少？**
按 token 计费，各家不同。以本页采集的 **Claude中转站价格**为例，Claude 系模型输入价约为官方单价的 0.39× 到 1.06×，缓存读取价可低至 0。价格随上游和促销变动，请以平台官网当时报价为准。

**哪家 Claude 中转站性价比最高？**
看你的场景：要**低价**看输入输出单价（本页第一节有与官方价的倍数对比）；要**长上下文省钱**看缓存读取价；要**公司报销**必须选支持企业发票的平台。「性价比」不是单一维度，把价格当唯一标准容易踩坑。

**怎么判断 Claude 中转站的缓存价格是真的？**
用同一个长前缀连续发两次请求，比较首字延迟。真实缓存命中会跳过预填充，第二次延迟应明显下降。如果接口报告了缓存读取但延迟没有变化，这个缓存价就只是账面数字。

**Claude 中转服务（Claude中转服务）是合法的吗？**
中转本身是转发服务，但通常依赖上游账号或渠道，而上游服务条款一般不允许转售访问权。这是行业固有风险，选平台时应计入——这也是「有公开实体、能开票」的平台更值钱的原因。

**为什么有的 Claude 中转站便宜到不像话？**
通常是逆向渠道、共享订阅账号、或低于成本引流后再涨价。前两种随时可能失效或封号。这个行业已被媒体调查过：有[中转站以低价引流、用掺假或倒卖的方式套利](https://www.secrss.com/articles/90746)，[央视也做过如何甄别靠谱 AI 中转站的报道](https://business.cctv.cn/2026/06/15/ARTI6QdfaGzvzCIFZKBThOPL260615.shtml)。价格明显低于官方时，先假设它有原因。

### Claude 中转源头是什么意思？

搜「**claude中转源头**」的人通常在找一件事：**不想经过加价转售的中间层**，想直接对接一手渠道。理解这个词，需要知道这个行业的层级：

| 层级 | 是什么 | 特点 |
|---|---|---|
| **官方直连** | 直接向 Anthropic 购买 API 额度 | 最稳定、最合规，但需要海外信用卡和跨境网络 |
| **授权聚合商** | 如 OpenRouter，官方授权路由 | 加价约 5%，合规，仍需要海外支付方式 |
| **一手/源头中转** | 自己有上游额度池，直接对外提供服务 | 价格通常低于官方，是「源头」所指的一层 |
| **转售/分销中转** | 从上一级批发额度，再加价零售 | 加价低、门槛低，但稳定性取决于上游 |
| **逆向渠道** | 通过非授权方式获取访问权 | 最便宜，随时失效或封号 |

**但「源头」这个词没有权威定义，也没有第三方能核实。** 任何平台都可以自称是源头。判断时看三件能验证的事：

1. **是否有公开的公司实体或备案**——有实体意味着有承担责任的成本，虚假宣传的代价更高
2. **价格是否长期稳定**——真正有上游额度池的平台价格波动小；纯转售的会随上游调价频繁变动
3. **是否公开价格接口**——愿意把价格做成可抓取的公开接口，通常比只在登录后才展示价格的可信

**不要只看价格。** 便宜到明显低于上游成本的，大概率不是「源头」而是逆向渠道。

### 哪家 Claude中转站最高性价比？

「性价比」取决于你的用量结构，不是单一指标：

| 你的场景 | 该看什么 | 本页数据 |
|---|---|---|
| 大量短请求、输出为主 | **输出单价** | 本站最低 0.37× 官方价（Opus 4.8），最高 1.48×（Sonnet 5 输出） |
| 长上下文、反复读同一份文档 | **缓存读取价** | 本站 7 个 Claude 系模型缓存读均为 0 |
| 需要公司报销 | **是否支持企业发票** | 见第六节，CloseAI、玄枢API 支持 |
| 对延迟敏感 | **TTFT 与稳定性** | 中转普遍慢于官方直连，这一点没有例外 |

**「最高性价比」不是指最便宜。** 价格低 30% 但三天两头超时，实际成本比稳定的高价平台更高——这也是为什么本页把「怎么验证是否诚实」单独列一节。

---

## 五、怎么验证一个 Claude 中转站是否诚实

上面第四节的两项检查有现成脚本，本仓库就是做这个的。

### cache honesty：缓存是真的还是账面数字

要求两个独立信号同时成立：

| 判定 | 条件 | 含义 |
|---|---|---|
| `consistent` | 声明命中 **且** warm TTFT 实测下降 | 真缓存 |
| `counter-only` | 只声明命中，TTFT 不动 | ⚠ 计数器是装饰品 |
| `speed-only` | 有加速但没声明 | 真缓存但没上报 |
| `no-cache` | 两者皆无 | 无缓存 |

**伪造计数器很容易，伪造加速很贵**——这就是这套判定难被糊弄的原因。

### billing honesty：用量与计费是否对得上

- **token 对账**：本地分词结果 vs 接口报告的 `prompt_tokens`，报告偏差率
- **失败请求探针**：发不存在的模型 ID、超出上限的 `max_tokens`，看是否仍被计为成功调用
- **模型身份**：记录每次响应回显的 `model` 字段，静默换渠道会在这里露出来

### 使用

```bash
pip install httpx
python -m relay_audit plan          # 不花钱，打印请求计划与预估花费
python -m relay_audit run --out results/
python -m relay_audit catalog --out results/catalog --fx 7.1
```

**你也可以直接拿它来测本列表推荐的任何平台，包括 Relay 自己。**

---

## 六、平台信任数据来源

下表转自上文的推荐位所使用的公开收录数据。信任标记与核验时间引用公开的中转站收录列表（[来源](https://github.com/howardpen9/awesome-ai-api-proxy)），本仓库未做二次评级，也未编造任何平台信息。

| 平台 | 类型 | 支付 | 信任 |
|---|---|---|---|
| [Relay (极智API)](https://www.relay-api.com) | mixed | 支付宝 / 微信 | 🔵 本站 |
| [云雾 API (YUNWU)](https://yunwu.ai) | mixed | 支付宝 / 微信 | 🟢 active · 2026-05-26 |
| [柏拉图 AI (bltcy)](https://api.bltcy.ai) | mixed | 支付宝 / 微信 | 🟢 active · 2026-06-07 |
| [UiUiAPI](https://uiuiapi.com) | official-relay | 支付宝 / 微信 | 🟢 active · 2026-06-07 |
| [CloseAI](https://www.closeai-asia.com) | official-relay | 支付宝 / 微信 / 企业发票 | 🟢 active · 2026-05-26 · 已注册实体 |
| [No.1-API](https://api.rcouyi.com) | aggregator | 支付宝 / 微信 | 🟢 active · 2026-05-26 |
| [TeamoRouter](https://teamorouter.com) | mixed | 支付宝 / 微信 | 🟡 unverified · ⚠ 运营方自荐 |
| [玄枢API](https://www.xuanshuapi.com) | mixed | 企业发票 | 🟡 unverified · ⚠ 运营方自荐 |
| [DMXAPI](https://dmxapi.cn) | mixed | 支付宝 / 微信 | 🟡 unverified · ⚠ 无公开实体 |
| [OpenRouter](https://openrouter.ai) | aggregator | 信用卡 / 加密货币 | 🟢 官方授权路由 |

标记说明：🟢 已核验可用　🟡 社区收录或未经独立核验　⚠ 已知风险标记　🔵 本仓库维护方运营

---

## 七、原始数据与复核

价格表由脚本采集，原始 JSON 已入库，可自行复现：

- [`data/published/catalog-2026-09-22.json`](data/published/catalog-2026-09-22.json) — 采集原始数据，含探测日志与汇率
- [`data/published/catalog-2026-09-22.md`](data/published/catalog-2026-09-22.md) — 渲染后的对比表
- [`data/published/README.md`](data/published/README.md) — 采集规则与复现方法

复核命令：

```bash
python -m relay_audit catalog --out results/repro --fx 7.1
```

请求体、模型列表与价格应当一致；时间戳不会一致。**如果你跑出不一样的结果，那是数据，欢迎提 Issue。**

如果发现本页数据与实际情况不符，**请以平台官网为准**，并欢迎指出——带日期的更正比不更新的表格有用。

---

## 八、免责与限制

1. **本页由 relay-api.com 维护**，该站是列表中的平台之一。价格数据包含其劣势项
2. **价格会变**，且比官方频繁。本页数据带采集时间，超过 14 天请视为过期
3. **平台信任标记来自第三方公开收录列表**，本仓库不做核验，也不为其准确性背书
4. **上游合规风险自负**：中转通常依赖上游账号或渠道，上游服务条款一般不允许转售访问权
5. 本仓库不代理、不转售、不提供任何模型的访问权
6. 所有产品名与商标归各自所有者

---

## License

MIT
