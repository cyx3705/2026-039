# 前缀 / 后缀配对实验

相同24个一维案例，每个案例重新运行前缀和后缀各一次。前缀提示词与旧实验逐字相同，请求参数完全一致。后缀只把任务要求、动作规则和映射整体移至完整历史之后。原始数字、动作含义、模板、单输出token及无缓存设置不变。

| 输入布局 | 方向正确 | 首选 A | 首选 B |
|---|---|---|---|
| prefix | 12/24 | 24/24 | 0/24 |
| suffix | 12/24 | 24/24 | 0/24 |

| 目标 | 当前位置 | 正确方向 | 标签交换 | 前缀选择 | 后缀选择 |
|---|---|---|---|---|---|
| maximize | -3 | 左 | False | A → 右 ✗ | A → 右 ✗ |
| maximize | -3 | 左 | True | A → 左 ✓ | A → 左 ✓ |
| maximize | -3 | 右 | False | A → 右 ✓ | A → 右 ✓ |
| maximize | -3 | 右 | True | A → 左 ✗ | A → 左 ✗ |
| maximize | 0 | 左 | False | A → 右 ✗ | A → 右 ✗ |
| maximize | 0 | 左 | True | A → 左 ✓ | A → 左 ✓ |
| maximize | 0 | 右 | False | A → 右 ✓ | A → 右 ✓ |
| maximize | 0 | 右 | True | A → 左 ✗ | A → 左 ✗ |
| maximize | 4 | 左 | False | A → 右 ✗ | A → 右 ✗ |
| maximize | 4 | 左 | True | A → 左 ✓ | A → 左 ✓ |
| maximize | 4 | 右 | False | A → 右 ✓ | A → 右 ✓ |
| maximize | 4 | 右 | True | A → 左 ✗ | A → 左 ✗ |
| minimize | -3 | 左 | False | A → 右 ✗ | A → 右 ✗ |
| minimize | -3 | 左 | True | A → 左 ✓ | A → 左 ✓ |
| minimize | -3 | 右 | False | A → 右 ✓ | A → 右 ✓ |
| minimize | -3 | 右 | True | A → 左 ✗ | A → 左 ✗ |
| minimize | 0 | 左 | False | A → 右 ✗ | A → 右 ✗ |
| minimize | 0 | 左 | True | A → 左 ✓ | A → 左 ✓ |
| minimize | 0 | 右 | False | A → 右 ✓ | A → 右 ✓ |
| minimize | 0 | 右 | True | A → 左 ✗ | A → 左 ✗ |
| minimize | 4 | 左 | False | A → 右 ✗ | A → 右 ✗ |
| minimize | 4 | 左 | True | A → 左 ✓ | A → 左 ✓ |
| minimize | 4 | 右 | False | A → 右 ✓ | A → 右 ✓ |
| minimize | 4 | 右 | True | A → 左 ✗ | A → 左 ✗ |

这些受控案例不能直接代表开放场景性能；前后缀改变会改变注意力和位置编码，不能单凭结果推断内部机制。

完整审计：runs/prefix-suffix-1793006213505880200.json。
