# 单次前向高维爬山

独立实验，不接机器人。使用本机已有 Qwen3 8B GGUF（Ollama 的权重），不下载模型，不训练。Python 只用标准库。

启动（PowerShell 7）：

```powershell
.\b-code\start.ps1
```

打开 http://127.0.0.1:18766 ，点击开始实验。模型服务在 18765，页面服务在 18766。后台进程 PID 保存在 `*.pid`，退出页面不会卸载模型。脚本会复用已启动的服务。

命令行也可直接实验：

```powershell
python b-code/probe.py --dims 5 --k 2 --rounds 40 --seed 39
```

## 一次前向的定义

每轮把**完整历史**作为完整输入，关闭 prompt cache，prefill 一次读取最后位置的 token 概率。`n_predict=1`，没有生成思维链、JSON 列表或后续 token。逻辑与物理 batch 均为 8192，输入严格少于 8192 token，单个 slot；不把长输入拆成多个 prefill 批次。这里的一次前向包含输入 prefill，绝不是整个实验只调用一次模型。服务日志显示 prompt eval、一个预测 token、无后续 decode eval；请求和响应均存档。底层 GPU kernel 数量不等于前向次数。

动作表每维有正负两个方向，分别映射到一个 token；启动推理前验证每个标签确实只有一个 token。grammar 把合法输出限制到这些标签，返回完整受限概率。按概率取 K 个不同坐标的动作，同时执行固定步长 0.2。不试算候选、不择优、不拒绝下降、不回滚。

**这 K 个动作是同一输出位置的并列候选，被实验规则组合执行；并非模型生成了一个有条件依赖的 K 步计划。** 后续 token 树剪枝可以从 `choose()` 和原始概率记录继续扩展，当前没有实现树搜索。

## 输入与环境

当前环境是隐藏参数的耦合多峰地形，高度越大越好。每个维度叠加缓慢下沉的二次项与周期波纹，相邻维度之间还存在耦合，因此有多个局部山峰。初始 4 条观测来自同一条随机动作轨迹。模型仅获得完整的 `[{x: [...], height: ...}, ...]`，以及固定动作定义；不提供目标点、目标公式、梯度、差分、归一化、降维或摘要。不截断历史，超过上下文直接停止并记录错误。JSON 序列化、文本 tokenization 是必要的输入表示，不意味着原生浮点张量直接输入语言模型。

默认 5 维，页面可选 4–5 维，每轮 2 个动作，默认 40 轮，单个动作步长仍为 0.2。CLI 最多支持 31 维；完整历史超过 8192 token 会停止，增加轮数并不意味着静默裁剪历史。模型固定 Qwen3 的非思考模板。这里还没有接入真实环境原始传感器数据，也没有实现最终机器人动作原语接口。

随机基线与真实梯度方向基线使用相同起点、K、步长，各自独立运行。真实梯度基线使用同一复杂地形的解析梯度，仅用于评价；不把其信息输入模型。一个随机种子不能支持统计结论，也不能从效果推出模型内部真的做了梯度下降。

## 文件

- `probe.py`：环境、单位置受限推理、两个基线、完整审计记录。
- `server.py` / `index.html` / `terrain.js`：本地实时页面，含伪三维地形、小点动画、时间拖动和坐标切换，以及曲线、各维状态和 token 分布。地形严格采用同一个目标公式；两个显示轴之外的坐标固定为小点当前值，是动态二维切片。轨迹线投影到当前切片，真实历史高度以曲线为准。动画仅对相邻实测状态作插值，不增加环境采样。
- `runs/run-*.json`：独立运行记录，`latest.json` 是页面正在读取的记录。
- `model.stderr.log`：模型服务时序，用于检查 prefill / decode 行为。

旧版单峰目标首次实测（与当前多峰环境不可直接比较）：seed 39，16 维、K=3、6 轮，初始高度 -53.991478；最终模型 -49.650588、随机 -53.534123、真实梯度方向 -35.690459。模型提高了 4.340890，但远落后于梯度对照；这只是一次连通性实验。

页面轮询只发送轻量状态；展开完整记录时才加载完整 prompt / request / response，完整审计记录仍保存在 runs 中。

新版多峰实测：seed 39，5 维、K=2、40 轮，初始 -4.352544，最终模型 -19.706481、随机 -3.067680、梯度方向对照 3.438180。模型未实现稳定爬升。40 轮均验证完整原始历史、无缓存、无截断、仅一个输出 token；最终输入 5088 token。

地形视角：鼠标或单指拖动可环绕旋转、改变俯仰，滚轮缩放；支持复位、俯视、侧视和自动旋转。聚焦地形后可用方向键旋转、加减号缩放、Home 复位。视角与回放独立；旋转的是当前二维切片对应的三维高度曲面，高维方向仍用坐标选择切换。小点与轨迹置顶显示以便定位。

## 山谷求极小值实验

页面新增目标选择，默认“山谷 · 求极小值”；原“山峰 · 求极大值”仍可选。山谷环境定义为原山峰高度的相反数 `v(x) = -h(x)`，在环境生成时定义，模型接收的仍是该环境完整原始观测。山谷模式提示词明确使用 `Minimize`，真实梯度对照沿山谷函数的负梯度运行，页面同时显示越低越好、相对起点改善和对应的山谷曲面。原始高度字段依然使用 `height`，并在记录中保存 `goal` 和 `objective`，避免两种目标混淆。

```powershell
python b-code/probe.py --mode valley --dims 2 --k 2 --rounds 40 --seed 8
```

`max h` 和 `min(-h)` 的理想空间动作相同，但提示词与数值符号都变了，所以单靠这组实验不能将数值偏好、动作标签偏好和时序推断错误完全分开。当前保持原 K=2 以便与最近轨迹配对，不同时改变动作数。

## 后悔动作

页面默认启用“允许后悔（撤销）”，CLI 可用 `--no-regret` 关闭。新增单 token `!`，只在有未撤销的模型移动时进入合法动作集合。若它在同一输出分布中排名第一，本轮只撤销最近一次尚未撤销的整组移动，精确恢复之前坐标；否则忽略该候选，照常选择 K 个不同坐标移动。初始预热不能撤销；可连续撤销多次模型移动。每次撤销消耗一轮，完整原始历史不删除、不回写。撤销目标坐标作为原始状态告知模型，不包含梯度、摘要或外部好坏判断。随机和梯度对照仍每轮移动，比较的是相同决策轮数。

动作记录、后悔次数和轨迹紫色圆环均来自真实执行记录。撤销由模型决定，程序不按目标值自动触发。详见 regret-comparison.md 和 runs 原始审计。

## 一维最小实验

页面支持1维，并新增“单峰/单谷（二次函数）”地形；一维显示原始函数剖面和小点，不构造虚假的第二维。默认界面选择1维、K=1、单峰、关闭后悔。

`python b-code/test_one_dimension.py` 执行24个受控案例：三个当前位置、左右两种证据、极大/极小两种目标，以及A/B左右含义交换。目标位置和公式不输入模型。结果保存在 one-dimension-report.md 和 runs/one-dimension-*.json。它是模型能力实验，不是要求模型必须通过的软件单元测试。

连续轨迹可使用 `python b-code/probe.py --dims 1 --k 1 --landscape parabola --mode mountain --no-regret --rounds 40 --seed 39`。现有多维复杂地形、旋转和后悔选项仍保留。

## 前缀 / 后缀对照

当前默认改为后缀：`Raw history + 完整原始JSON → Maximize/Minimize任务要求、动作规则、映射表 → /no_think → 单输出位置`。历史后没有额外归一化、摘要或梯度提示。页面可切换指令位置；CLI 可用 `--prompt-layout prefix` 复现实验旧布局，默认 `suffix`。布局保存到运行配置和逐轮审计。

`python b-code/compare_suffix.py` 对原24个一维案例分别重新运行前缀和后缀，共48次模型调用。前缀提示词与旧实验逐字相同，请求参数也逐项相同；后缀只调整完整规则和原始历史的顺序。结果见 prefix-suffix-report.md。

## 每轮随机标签映射

默认开启“每轮随机打乱标签”，CLI 可用 `--no-shuffle-labels` 关闭。每次决策对移动标签做一次均匀随机排列，并重新分配到完整动作集合；提示词中的映射表标签顺序也随之改变。执行使用同一映射，`!` 后悔标签保持固定。每轮独立洗牌可能偶然与上一轮相同，不强制排除重复。标签随机流与环境/随机基线使用独立的随机数生成器，种子由实验 seed 派生，因此可复现且不会改变初始条件或随机对照。完整映射保存在 audit.action_table，页面显示当轮映射和动作记录中的标签→实际动作。

## 当前动作：移除 A/B/C/D

当前交互实验不再使用字母选项，也不随机交换方向符号含义。一维直接输出 `+`（坐标增加）或 `-`（坐标减少）；二维再增加 `↑/↓`，第三维 `前/后`，第四维 `内/外`，第五维 `增/减`，各方向的坐标和步长在当轮提示词中明确给出。所有符号均已验证是 Qwen3 的单个 token，最多支持5维。grammar 使用逐项字面量，正确处理 `-` 等特殊字符。后悔 `!` 仍是独立可选动作。

页面移除了“随机打乱标签”开关。旧 A/B 对照脚本显式保留历史字母表用于复现实验，它们不代表当前交互实验的动作设置；旧日志也不会被改写。

## 多次前向：直接输出完整坐标位移

页面新增“推理路线”，默认多次前向；CLI 使用 `--execution-mode vector`（默认），`--execution-mode single` 保留单位置方向实验。

多次路线根据完整原始历史和后缀目标，自回归生成一个完整JSON位移数组，例如 `[0.2,-0.2,0]`。每个分量在前面已输出token的条件下生成；整个数组结束后只执行一次联合动作。它不是取同一logits位置的多个候选。保持固定步长，要求恰好 K 个非零分量，每个非零分量为 ±step；其余为0。grammar仅约束这些合法完整数组，不计算目标、不按目标值排序、不做候选试算。无字母动作标签。开启后悔时还可输出 JSON 字符串 `"undo"`。

当前关闭生成思维链（非思考模板），多次前向用于生成完整动作文本；它不等同于让模型长篇推理。最多128个输出token，保留输出预算；不截断历史，不执行不完整/格式非法的数组，不替模型纠正方向。temperature=0，完整请求、响应、实际生成token数、解码数组和实际动作均存档。输入历史每轮仍重新prefill；输出生成过程中使用正常自回归KV缓存。

随机与梯度对照保持相同每轮K个变动坐标、相同步长。与单次路线比较时，提示词、动作表示、采样配置与计算预算都有变化，不能把差异单独归因于前向次数。`python b-code/compare_vector.py` 重跑12个一维受控案例的两条路线，见 vector-comparison.md。

## 历史决策记录

页面默认开启“思考”（仅用于多次前向路线），CLI 可用 `--no-thinking` 关闭。先使用 Qwen3 的 `/think` 模板自由生成思考，最多16384 token，直到模型输出 `</think>`；再将同一历史和本轮思考作为前缀，用原动作 grammar 生成最终数组。两阶段分别请求，均重新 prefill，不做候选试算。思考达到预算时由程序追加 `</think>`，基于已生成思考继续生成受限动作；审计明确记录 `budget_hit=true, closure=budget_forced`，不伪装成模型自然结束。预算上限16384 token，并根据完整历史剩余空间动态缩小，预留动作输出空间；仍不截断历史。其他异常或动作无效则停止。完整思考阶段请求、响应保存在 `audit.reasoning_audit`，不进入下一轮历史；页面输出计数分别显示动作 token 和思考 token。这比无思考路线多了计算和提示词变化，不构成仅改变前向次数的严格对照。

新运行使用 `history_schema=executed-decisions-v1`。完整历史的每条记录仍包含原始 `x` 和 `height`；随机预热记录额外标记 `source=warmup, decision=null`。模型动作执行后的观测标记 `source=model`，并包含 `decision: {type, actions, displacement}`，表示从上一条观测到这一条观测实际执行的决策。`type` 为 `move` 或 `undo`，`actions` 为实际执行的 `[axis,sign]` 列表（撤销为空），`displacement` 为完整坐标位移数组。撤销也保留原有全部历史，不删除被撤销记录。

决策记录在执行后追加，从下一轮请求起可见。单 token 和数组路线都使用此结构，不把历史模型回答伪装为 assistant 对话，也不添加奖励差值、梯度、好坏评价或思考文本。每轮仍重新输入完整历史，不截断或摘要，不跨轮复用输入 KV；超出上下文预算停止。旧实验档案不回写。

## Long budget / low effort

Current service context: 32768 tokens. Default per-round thinking cap: 16384 tokens, reduced only when full history requires more context. Low effort is a prompt instruction (brief assessment, avoid repeated calculations), not a native reasoning_effort parameter. Full raw observations and executed decisions remain unchanged; reasoning is not carried across rounds. Prefill batch/ubatch are now 512; long inputs may use multiple batches. KV cache K and V use q8_0. Earlier single-forward measurements used the old 8192 context configuration.

## 可变步长与自由多轴

新实验页面和 CLI 默认 `action_space=variable`，仅作用于数组路线。每个轴独立选择 [-max_step,max_step] 内的位移（最多3位小数，精度0.001），不限恰好K轴；默认单轴上限2，页面可设置整数1–10。允许全零数组（stay），停留不压入撤销栈；undo仍撤销最近一次移动的整个位移。grammar直接约束每个分量的范围和小数位数，不枚举整组组合，不计算环境候选值。越界或非法输出拒绝执行，不静默裁剪或取整。实际执行原始解码位移，历史中的 displacement 保留各轴实际幅度，actions仅表示方向。

固定模式仍可选择；单 token 路线保持固定步长。K在可变模式只用于随机预热和旧基线。随机/梯度基线仍为0.2步长、K轴，与自由位移模型的动作预算不同，不可直接用曲线优势认定算法更优。开启思考后的推断、规划、大步跳跃与基于局部探索的优化是不同现象；单次轨迹不能区分这些机制。本文下方历史设置说明对应各自版本。

## 实时思考与停止

思考请求使用 llama.cpp 的 SSE 流；页面通过 `/thought-stream` 接收增量文本，在本轮结束前显示于“实时思考”面板。已完成轮次仍可在“模型思考历史”中按轮查看。浏览器断开或刷新不取消实验。

“停止实验”调用 `/stop`，设置取消信号并关闭正在生成请求的连接，使后端取消生成；执行动作前再次检查取消信号。停止后保存 `status=stopped` 和 `pending_thought` 中的部分思考，不执行尚未完成的动作。历史观测和决策不因停止而删除，停止后的新实验仍从其配置重新开始。

## GPU memory tuning result

Keep 32768 context and the default 16384 thinking cap. Launch with `-b 512 -ub 512 -ctk q8_0 -ctv q8_0`. The launcher checks these settings before reusing its managed model process. This changes KV precision relative to earlier f16 experiments; it does not change the raw history text.

Observed total GPU memory dropped from 11900 MiB to 7936 MiB idle, with 7968 MiB peak during a 1024-token thinking smoke call. Model-process counters dropped from 11470.7 MiB dedicated / 1276 MiB shared to 7514.4 MiB dedicated / 134 MiB shared. Smoke generation: 66.0 token/s over 1024 thinking tokens, then a valid joint action. Prior slowdown to around 0.6 token/s came from a different runtime state, so this is an operational check rather than a controlled speed benchmark. Audit: `runs/memory-q8-smoke.json`. The interactive experiment remains stopped.

## F-drive service storage

User preference: run local model services from F: to reduce C: writes. `start.ps1` now uses `F:\LocalModelServices\llama-runtime` for inference binaries, `F:\Models\Ollama` for weights, and `F:\LocalModelServices\b-code` for the working directory, PID files, logs, temp files, caches and run archives. Source files remain in this repository. The source-relative `b-code/runs` becomes a junction to the F: archive; previous C: archives are retained under a timestamped `runs-before-f-drive-*` backup. Stop/restart checks must read PID files from F:, not the old C: PID files. Existing C: logs and model installation are retained; no new service writes are directed there.

The launcher refuses to migrate while an experiment is running. First activation is queued by `F:\LocalModelServices\b-code\activate-when-idle.ps1`, with progress in `migration.log`. Environment redirects include TEMP, TMP, CUDA_CACHE_PATH, HF_HOME, TORCH_HOME, XDG_CACHE_HOME and PYTHONPYCACHEPREFIX, scoped to launched processes. Windows pagefile/system writes and unrelated applications are outside these settings.

## Unified model library

Canonical model root is now `F:\Models`: Ollama, HuggingFace, ModelScope and Speech/CosyVoice. C: user model directories are junctions to F:. Ollama desktop location and persistent user cache environment variables point to F:. Migration inventory, SHA256 records and verification are under `F:\Models\Migration`; overview: `F:\Models\README.md`. Bundled application assets remain at their installation paths.
