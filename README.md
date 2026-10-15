# 流程自动审批

本地页面通过项目编号读取真实项目合同台账，自动识别一二类或三类产品，分别执行对应立项查重规则。一二类另行校验项目业主，页面在业主校验框内显示业主名称、可用的工商基本信息、完整经营范围及醒目的结果标签，查询中、无需校验或检查未完成时也保留此框并标明状态；仅展示全部查重条件满足的重复项目，并可逐项查看一致依据。

## 技术栈与启动

后端使用 FastAPI + Uvicorn、SQLAlchemy Core 和 LangChain（langchain-openai）。SQLAlchemy 通过 PyMySQL 连接既有 MySQL 台账，在 REPEATABLE READ 下执行只读一致性快照；不创建或修改业务表。LangChain 的 ChatPromptTemplate 与 ChatOpenAI 调用链负责经营范围分类，业务规则及原文引用校验仍在 Python 服务中。

前端使用 Next.js 16 App Router、React 19、TypeScript、Tailwind CSS v4 和 shadcn/ui（Radix）。页面由 React 状态和组件渲染，shadcn/ui 提供按钮、输入框、对话框、徽标及卡片。界面延续原有浅绿审批工作台。

需要 Node.js 22.12+、Python 3.12+ 和 uv。首次运行：

```sh
npm ci
uv sync --locked
npm run dev
```

访问 http://127.0.0.1:4186/。该命令同时启动 Next.js（4186）和 FastAPI（4187），退出时关闭两项服务。Next.js 将 `/api/*` 转发到 FastAPI，浏览器使用同源接口。后端 OpenAPI 文档在 http://127.0.0.1:4187/docs。`npm run dev:web` / `npm run dev:api` 可单独启动两端。

生产构建和本机运行：

```sh
npm run build
npm start
```

依赖版本分别由 `package-lock.json` 和 `uv.lock` 锁定。仅构建前端无需数据库或模型密钥。

| 目录 | 内容 |
| --- | --- |
| `app/` | Next.js 路由、布局与 Tailwind 主题 |
| `components/` | 查询工作台、结果视图和 shadcn/ui 组件 |
| `lib/` | TypeScript 接口类型、展示格式及样式工具 |
| `scripts/server.py` | FastAPI 接口、输入校验与生命周期 |
| `scripts/database.py` | SQLAlchemy 引擎和连接池 |
| `scripts/*_service.py` | 查重、业主和场站业务规则 |
| `scripts/business_scope_llm.py` | LangChain 模型调用和结果校验 |
| `config/` | 字段、枚举与业务样例 |
| `tests/` | Python 业务/API 测试和 React 渲染测试 |

数据库连接信息从用户提供的致远接口说明 DOCX 中读入内存。当前机器继续沿用 `local-data/connection.json` 中的文档路径；`local-data/` 被 Git 忽略，不会公开给前端。其他机器可设置：

```sh
LEDGER_CREDENTIALS_DOC='/absolute/path/to/致远API接口调试说明 -AI.docx' npm run dev
```

环境变量优先于本地配置。未配置数据库连接时仍可访问页面，查询会明确提示配置缺失。更多环境变量见 `.env.example`；现有本地 JSON 配置无需迁移，Python 不自动加载 `.env`，通过 shell 导出或 `uvicorn --env-file` 指定。`API_BASE_URL` 为 Next.js 服务端代理目标，修改后需要重启，生产模式需重新构建。

验证命令：

```sh
npm test
npm run typecheck
npm run build
```

测试使用模拟数据库与模型响应，不调用真实外部服务。真实模型回归通过 `uv run python scripts/verify_business_scope_llm.py` 单独执行。

## 统一身份认证

已接入 Keycloak `company-dev`，地址为 `http://10.8.6.32:18080`。前端使用 Public Client `marketing-workflow-automation-web`，通过官方 `keycloak-js` 执行 Authorization Code + PKCE S256。登录回调为 `http://127.0.0.1:4186/callback`，退出后返回 `http://127.0.0.1:4186/`。请使用该地址访问本地页面，认证中心需放行此回调、退出地址和 Web Origin `http://127.0.0.1:4186`。

默认本地配置下，访问 `http://localhost:4186` 会先由 Next.js 重定向到 `http://127.0.0.1:4186`，再发起认证。回调地址不再跟随浏览器域名变化，避免 Keycloak 拒绝未登记的 `localhost` 回调；PKCE 状态也始终在同一来源下创建和读取。显式配置其他环境的回调地址后，不启用此本地域名重定向。

页面使用 `login-required` 初始化认证；未登录时自动跳转到统一认证平台，已有有效统一登录会话时自动返回，完成登录后由 `/api/me` 验证身份，再加载工作台。访问令牌和刷新令牌仅由适配器保存在内存中，请求前自动刷新，过期时尝试续期；续期失败或 API 返回 401 时清除本地身份和工作台数据，并自动跳转到统一认证平台要求重新登录，避免无交互的 SSO/401 循环。无应用角色时显示无权限页面。退出入口清除本地身份并跳转到认证中心结束会话，返回首页后自动进入统一登录页。跨窗口退出通过后续令牌刷新感知，不依赖第三方 Cookie iframe。

认证初始化完成后关闭适配器内部的 `loginRequired` 标记，后续重新登录由页面统一控制。退出时先保留 `id_token_hint` 构造退出地址，再停止过期回调、清除本地令牌并跳转；禁止 `clearToken()` 隐式发起登录，以免登录跳转覆盖退出请求。退出进行中忽略并发请求的认证失败回调。

FastAPI 的所有 `/api/*` 接口（含 `/api/health`、`/api/policy`、`/api/me`）均要求 Bearer Access Token。后端通过固定 JWKS 地址验证 RS256 签名、有效期、issuer `http://10.8.6.32:18080/realms/company-dev`、audience `marketing-workflow-automation-api` 和非空 `sub`，拒绝 ID Token。公钥缓存 5 分钟，未知 `kid` 按 PyJWT 的默认 30 秒刷新冷却处理。当前查询功能允许 `resource_access.marketing-workflow-automation-api.roles` 中任一 `agent_admin`、`agent_manager`、`agent_user` 角色；其他客户端或 Realm 的同名角色不能授权。现阶段不根据部门限制台账数据范围。

`/api/me` 返回 `user_id`（来自 `sub`）、`username`、`display_name`、`email`、`department_code`、`department_name` 和本应用角色，页面展示姓名和部门。没有令牌或令牌无效返回 401，缺少应用角色返回 403，获取公钥失败返回 503，均不会执行业务查询。

认证参数默认使用上述本地开发配置，可按 `.env.example` 覆盖。Next.js 自动读取 `.env.local`，`NEXT_PUBLIC_*` 在构建时写入前端；Python 仍需通过 shell 导出 `KEYCLOAK_*`，或单独启动 Uvicorn 时使用 `--env-file`。切换环境后重启后端并重新构建前端。后端仅作为资源服务器验证令牌，不获取机器 Token，因此此接入不需要后端 Client Secret，也不要将 Secret 放入前端配置。

认证回归随 `npm test` 执行：包含真实 RSA 签名验证、过期/错误 issuer/错误 audience/伪造签名拦截、角色隔离、JWKS 缓存与轮换、认证服务故障拒绝访问，以及前端刷新、401/403 和取消请求处理。业务回归使用 FastAPI 的测试依赖覆盖，不提供运行时免登录开关。真实账号的登录、刷新、退出和业务访问需在已分配应用角色的账号下另行验收。

实现参考：[Keycloak JavaScript adapter](https://www.keycloak.org/securing-apps/javascript-adapter)、[PyJWT 验证与 JWKS](https://pyjwt.readthedocs.io/en/stable/usage.html)。

## 当前确认的查重规则

按 `field0026`（一二类公司产品）与 `field0036`（三类公司产品）的类别编号选择规则。编号对应名称由用户提供的枚举映射表确认。一二类与三类字段同时有值、两者均缺失或编号无法识别时，返回待核实，不猜测项目类别。

### 一二类产品

| 步骤 | 数据库字段 | 用途 |
| --- | --- | --- |
| 读取当前项目 | `field0007` | 项目编码 |
| 检索其他项目 | `field0024` | 电厂名称 |
| 一致性比对 | `field0013` | 项目所在省份 |
| 一致性比对 | `field0014` | 项目所在市 |
| 一致性比对 | `field0015` | 项目所在区/县 |
| 一致性比对 | `field0027` | 公司产品子类（一二类产品子类） |
| 一致性比对 | `field0025` | 装机容量MW |

按项目编码查询；编号不存在或对应多条记录时停止判断。候选集为 `formmain_8861` 中电厂名称完全一致的一二类项目及类别待核实记录，以 `ID` 排除当前记录，不按项目状态过滤。

省份、市、区县、公司产品子类和容量均有值且五项全部一致时提示重复。省份、市、区县、公司产品子类按内部选项编号准确比较；容量使用 Decimal 按数值比较，`0.63` 与 `0.630000` 一致。项目名称仅展示，不参与判断。当前规则不使用之前的客户、名称和内容字符相似度或任何匹配分数。

若当前项目缺少必要字段，提示待核实。同名候选项目有缺失字段且其余已知字段没有差异时也提示待核实；如果已有字段明确不同，该候选不符合重复条件。查询中断不输出“未发现重复”。原始枚举编号和长整型 ID 通过字符串传输，不因 JavaScript Number 精度造成误判。

所有数据库查询在一次只读一致性快照事务内完成。候选查询没有 LIMIT，避免仅取部分记录导致漏报。页面仅在有确认重复的项目时显示候选列表，数量只统计重复项目，并展示各项一致依据；有差异或待核实的候选不列出，资料缺失仍保留待核实提示。

### 三类产品

| 比对条件 | 数据库字段 |
| --- | --- |
| 电网分类（国网/南网） | `field0033` |
| 分部/省/市电力公司 | `field0035` |
| 部门 | `field0034` |
| 年份 | `field0425` |
| 三类 | `field0036` |
| 公司产品（具体产品） | `field0037` |

先按项目编号取资料，再以 `field0035` 的原值检索同一电力公司的其他三类项目及类别待核实记录。六项均有值且一致时提示重复。电厂、容量及一二类产品子类不参与三类规则。部门和年份直接取对应字段；年份缺失时提示待核实，不从部门或项目名称提取。文本按原值比较，不自动拆分、去除空格或合并别名。

两套规则均排除当前记录及明确属于另一类的候选，不按项目状态过滤；候选类别不明或冲突且已知比对字段没有差异时提示待核实，不标为重复。三类具体产品使用已导入的三类枚举映射。用户提供的映射表未包含电网分类 `field0033`，该字段暂显示原始编号，仍按编号准确比较。

## 一二类业主校验

先取项目合同台账 `field0009`（立项时项目业主方全称），以全称精确查询客户档案 `formmain_4214.field0010`（客户名称），按 `field0068`（大客户分类）判断。映射使用附件中的枚举 ID，长编号始终保留为字符串。

| 客户档案选项 | 按业务要求判断为 | 结果 |
| --- | --- | --- |
| 风机厂 | 风机厂 | 不符合要求 |
| 综自客户 | 综自厂家 | 不符合要求 |
| 代理商 | 总包方（用户确认） | 不符合要求 |
| 关联方 | 关联方 | 不符合要求 |
| 不涉及、竞争对手 | 未命中受限类别 | 未发现业主限制 |

三类不查询客户档案或天眼查。项目类别不明确、业主全称缺失、客户分类为空或编号未知时提示待核实。同名档案中任一条命中限制即提醒，其他分类冲突提示待核实。客户档案查询失败不会被当作“未查到客户”。原有查重状态仍只表示重复结果，业主校验通过独立的 `ownerReview` 返回并在页面优先显示。`GET /api/policy` 的 `ownerPolicy` 提供业主规则说明。

仅客户档案确实未找到时，在结束数据库只读事务后调用天眼查 `GET /services/open/ic/baseinfo/normal?keyword=...`。请求头使用 `Authorization`，名称按 URL 编码，接口超时为 10 秒。校验 `error_code`、返回企业名称与经营范围；企业名称比较去除首尾空白，并将全角、半角圆括号视为等价，保留原始名称展示，其余文字须一致；失败、无权限、无结果、名称不一致或经营范围为空均提示待核实。

经营范围由 `scripts/business_scope_llm.py` 通过 LangChain 调用 OpenAI 兼容的 `POST /chat/completions`，使用配置的 LLM 做语义分类，不再使用关键词/正则规则分类。提示词定义风机厂、综自厂家和总包方的业务含义，并要求理解否定、排除、零部件制造、销售/运营/咨询与制造/总包的区别。只将返回企业名称和经营范围发给模型，不发送项目资料或客户档案。经营范围作为数据处理，不能改变分类指令。

模型必须分别返回三类的“认定属于／未认定属于／待核实”、简短理由及逐字原文依据。服务端校验三类齐全、类别不重复、判定值有效、理由非空，并检查引用确实存在于经营范围中。任一类认定属于则提示不符合要求；没有认定属于但有不确定项则待核实；三类均未认定属于才展示相应结果。未配置、接口失败、超时、输出截断、结构不完整或引用无效均提示待核实，不回退到关键词规则。引用校验不能保证模型语义判断正确，接口保留各类理由、原文与完整经营范围供复核，页面显示基本信息、完整经营范围和最终结果，不展示逐类分析或引用列表；仍不推断关联方。

用户确认的典型参照已纳入提示词：三一重能的“发电机及发电机组制造／新能源原动设备制造＋风电整机销售和技术服务”组合用于识别风机厂；南京国电南自电网自动化的“继电器保护、配用电自动化、智能变电站设备＋制造”共享动作表述用于识别综自厂家。仅销售、运营或普通机械电气设备制造不能据此认定。`config/business_scope_examples.json` 保存天眼查返回的真实经营范围、获取日期、用户确认类别和合成反例。运行 `uv run python scripts/verify_business_scope_llm.py` 可调用已配置的真实模型验证，测试时隐藏企业名称，检查语义结论与原文引用；该验证会调用 LLM，不包含在离线 `npm test` 中。

LLM 支持 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` 环境变量，优先于 Git 忽略的 `local-data/llm.json` 中的 `apiKey`、`baseUrl`、`model`。本机模型为 `deepseek-v4-flash`；密钥仅保存在权限为 `0600` 的本地配置中。LLM 请求超时为 60 秒，页面总等待上限为 120 秒；配置或提示词修改后需重启服务。页面不展示模型或逐类判断依据，响应保留 `classificationMethod`、`model`、`promptVersion` 和 `assessments` 供复核。

服务端支持 `TIANYANCHA_API_URL`（默认 `http://open.api.tianyancha.com`）和 `TIANYANCHA_TOKEN` 环境变量，也可使用 Git 忽略的 `local-data/tianyancha.json`：`{"apiUrl":"http://open.api.tianyancha.com","token":"..."}`。环境变量优先；本机凭据已保存在权限为 `0600` 的本地文件中，不放入静态文件、响应、日志或 Git。更换配置后重启服务。

## 接口与验证

### 场站类型分类校验

按项目编号取得同一条台账记录，独立返回 `stationReview`，页面单独展示校验状态、四个字段当前值、提示和新签命中的项目。此结果不改变原有查重及业主校验状态；产品类别不明确时仍检查场站分类。

| 字段 | 台账列 |
| --- | --- |
| 产品类型 | `field0020` |
| 项目类型 | `field0022` |
| 是否是改造品 | `field0404` |
| 场站类型分类 | `field0185` |

产品类型为“周期服务”且项目类型为“服务项目”，应填“服务”；是否是改造品为“是”，应填“改造”。当前分类不符时提醒。正常业务下两条件互斥；异常数据同时满足时提示“条件冲突、待人工核实”。未满足这些条件不自动推导为新签。

当前分类为“新签”时，按电厂名称 `field0024` 与其他记录的项目名称 `field0008` **完全相同**检索。以 `ID` 排除当前记录，不按项目状态、类别、地区或容量过滤；公司产品子类 `field0027` 的原始编号相同时提醒并展示命中项目。不使用三类子类 `field0037` 回填。SQL 使用参数化 `BINARY = BINARY` 精确比较，不忽略大小写或首尾空格，名称中的 `%`、`_` 和反斜杠均作为普通字符。没有候选数量上限，查询仍在同一次只读一致性快照中。

四字段均存储枚举 ID。已从 `项目合同台账枚举映射表20261015.xlsx` 导入产品类型 6 项、项目类型 10 项、是否 2 项、场站类型分类 3 项。其中“是否”映射用于 `field0404`（是否是改造品）。`config/contract_ledger_enums.json` 保留完整枚举资料，导入器同时生成 `config/station_type_enums.json`，按列保存 `{"选项ID":"中文名称"}`；两份配置均记录同一来源文件名及 SHA-256。未填写、编号未映射、资料缺失或检索失败时仍提示待核实，不报通过。更新映射后需重启本地服务。

`GET /api/policy` 的 `stationPolicy` 提供规则说明。新增测试覆盖分类不符、条件冲突、项目名称完全相同匹配、排除自身、子类长编号、特殊字符、缺失数据、查询失败、产品类别不明仍执行以及页面提醒和转义。

`POST /api/project-reviews`，请求 `{"projectCode":"..."}`。响应保留原始字段编号，并通过 `displayValues` 和逐项比对中的 `targetDisplayValue`／`candidateDisplayValue` 返回枚举名称；同时包含所有同名电厂候选、逐项比对依据、结果、范围、查询时间和规则版本。

`GET /api/policy` 返回规则集合 `policies` 及字段定义；每次查重响应通过 `policy` 返回实际使用的类别、字段、条件和范围；`GET /api/health` 返回本地服务配置状态。不存在项目返回 404、编号歧义返回 409、数据库不可用返回 503。浏览器统一访问 loopback 4186，Next.js 将 API 请求代理到 loopback 4187 的 FastAPI；服务端凭据不会传给浏览器。

```sh
npm test
```

单元测试同时覆盖四类受限业主、代理商/综自客户别名、客户档案优先、三类跳过、LLM 分类接入、三类结构校验、伪造引用拦截、不确定结论、接口失败及缺失数据不误报通过。查重测试覆盖使用一二类产品子类、子类缺失时不回退到其他字段、市缺失时不判定重复、类别自动识别与冲突、三类六项差异与缺失、年份不从名称补取、两类候选隔离、查询字段选择、排除自身、五项逐一不同、容量小数精度、容量为零、资料缺失、不同电厂、长枚举编号，以及项目不存在／编号歧义和数据源失败时的处理。

## 字段明细与原始查询验证

`config/contract_ledger_fields.json` 保存用户提供的 354 个业务字段定义，它们全部匹配已验证的 367 列主表。其余 13 个系统字段没有用户提供的中文名称。用户提供的枚举映射表已导入 `config/contract_ledger_enums.json`：地区 3,336 条、一二类产品及子类 224 条、三类产品及子类 34 条、大客户分类 6 条、是否 2 条、产品类型 6 条、项目类型 10 条、场站类型分类 3 条，保留父级编号和原表“枚举值”。省份、市、区县使用地区映射，公司产品子类使用一二类映射，均以 `ID` 匹配；不使用“枚举值”列作匹配键。页面显示名称，未映射时显示原始编号；缺失值仍显示未填写。映射只影响展示，查重继续按原始编号比较，同名但编号不同的选项不会判为一致。

`scripts/import_ledger_fields.py` 从字段明细生成映射并按既有快照检查字段覆盖范围。`scripts/verify_contract_ledger.py` 可按项目编号只读读取全部 367 列，输出原始值和中文字段名称。真实验证数据保存在 Git 忽略的 `local-data/`。

更新枚举映射时运行 `python3 scripts/import_ledger_enums.py /absolute/path/to/mapping.xlsx` 后重启本地服务。工作簿必须包含上述八个工作表，缺少任何一个时导入会报错，保留已有配置；成功时同步更新完整枚举及场站校验映射。导入程序按文本保留长编号，检测同一组内冲突编号、缺失列和公式；源文件名及 SHA-256 保存于映射配置中，原 Excel 文件保持不变。

当前应用需运行 Next.js 和 FastAPI 两项服务。此前发布的私有静态演示地址仍是旧演示版本；本次迁移和真实台账接口未部署到该地址。

开发参考：[Next.js 安装](https://nextjs.org/docs/app/getting-started/installation)、[shadcn/ui Next.js](https://ui.shadcn.com/docs/installation/next)、[Tailwind v4](https://ui.shadcn.com/docs/tailwind-v4)、[FastAPI 测试](https://fastapi.tiangolo.com/tutorial/testing/)、[SQLAlchemy 连接管理](https://docs.sqlalchemy.org/en/20/core/connections.html)、[LangChain ChatOpenAI](https://docs.langchain.com/oss/python/integrations/chat/openai)。
