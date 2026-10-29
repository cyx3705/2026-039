"""Paired prefix/suffix comparison on the original 24 one-dimensional cases."""
import json
import time
import probe

source_path = probe.ROOT / 'runs' / 'one-dimension-1793005691566445200.json'
source = json.loads(source_path.read_text(encoding='utf-8'))
output = probe.ROOT / 'runs' / f'prefix-suffix-{time.time_ns()}.json'
result = {'source': source_path.name, 'cases': [], 'status': 'running'}
for old in source['cases']:
    case = {key: old[key] for key in ('goal', 'current', 'history', 'expected_direction', 'swap_labels')}
    case['conditions'] = {}
    for layout in ['prefix', 'suffix']:
        actions, audit = probe.choose('http://127.0.0.1:18765', old['history'], 1, 1, 1,
                                      goal=old['goal'], regret=False,
                                      swap_labels=old['swap_labels'], prompt_layout=layout, action_symbols=probe.LABELS)
        if layout == 'prefix':
            assert audit['prompt'] == old['audit']['prompt'], 'Prefix control text changed'
            assert audit['request'] == old['audit']['request'], 'Prefix inference settings changed'
        expected_raw = json.dumps(old['history'], separators=(',', ':'), allow_nan=False)
        assert expected_raw in audit['prompt']
        if layout == 'suffix':
            assert audit['prompt'].index(expected_raw) < audit['prompt'].index(old['goal'].capitalize())
        case['conditions'][layout] = {'actions': actions, 'correct': actions == [[0, old['expected_direction']]], 'audit': audit}
    result['cases'].append(case)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(old['goal'], old['current'], old['expected_direction'], old['swap_labels'],
          [(layout, record['audit']['ranked'][0]['label'], record['correct']) for layout,record in case['conditions'].items()], flush=True)
result['status'] = 'complete'
output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
lines = ['# 前缀 / 后缀配对实验', '',
         '相同24个一维案例，每个案例重新运行前缀和后缀各一次。前缀提示词与旧实验逐字相同，请求参数完全一致。后缀只把任务要求、动作规则和映射整体移至完整历史之后。原始数字、动作含义、模板、单输出token及无缓存设置不变。', '',
         '| 输入布局 | 方向正确 | 首选 A | 首选 B |', '|---|---|---|---|']
for layout in ['prefix','suffix']:
    records = [case['conditions'][layout] for case in result['cases']]
    correct = sum(r['correct'] for r in records)
    a = sum(r['audit']['ranked'][0]['label']=='A' for r in records)
    lines.append(f'| {layout} | {correct}/24 | {a}/24 | {24-a}/24 |')
lines += ['', '| 目标 | 当前位置 | 正确方向 | 标签交换 | 前缀选择 | 后缀选择 |', '|---|---|---|---|---|---|']
for case in result['cases']:
    def choice(layout):
        r=case['conditions'][layout]
        return r['audit']['ranked'][0]['label']+' → '+('右' if r['actions'][0][1]>0 else '左')+(' ✓' if r['correct'] else ' ✗')
    lines.append(f'| {case["goal"]} | {case["current"]} | {"右" if case["expected_direction"]>0 else "左"} | {case["swap_labels"]} | {choice("prefix")} | {choice("suffix")} |')
lines += ['', '这些受控案例不能直接代表开放场景性能；前后缀改变会改变注意力和位置编码，不能单凭结果推断内部机制。', '',f'完整审计：runs/{output.name}。']
(probe.ROOT/'prefix-suffix-report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print('\n'.join(lines[:9]), flush=True)
