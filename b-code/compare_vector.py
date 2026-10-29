"""Compare direct single-token directions with autoregressive numeric vectors."""
import json
import time
import probe

output = probe.ROOT / 'runs' / f'vector-comparison-{time.time_ns()}.json'
cases = []
for goal in ['maximize', 'minimize']:
    for current in [-3, 0, 4]:
        for direction in [-1, 1]:
            target = current + 2 * direction
            factor = -1 if goal == 'maximize' else 1
            history = [{'x': [x], 'height': factor * (x-target)**2}
                       for x in [current-1, current+1, current]]
            case = {'goal': goal, 'current': current, 'expected_direction': direction,
                    'history': history, 'conditions': {}}
            for name, policy in [('single', probe.choose), ('vector', probe.choose_vector)]:
                actions, audit = policy('http://127.0.0.1:18765', history, 1, 1, 1,
                                         goal, regret=False, prompt_layout='suffix')
                case['conditions'][name] = {'actions': actions, 'correct': actions == [[0,direction]], 'audit': audit}
            cases.append(case)
            output.write_text(json.dumps({'cases':cases}, ensure_ascii=False, indent=2),encoding='utf-8')
            print(goal, current, direction, [(name, r['actions'], r['correct']) for name,r in case['conditions'].items()],flush=True)
lines=['# 多次前向：完整位移数组对照','','相同12个一维单峰/单谷案例、相同原始历史、后缀目标、固定步长1、关闭后悔。单次路线输出 +/−；自回归路线直接输出 JSON 位移数组，完整生成后执行一次。两条路线的输出格式、提示词和采样设置不同，因此不能把差异单独归因于前向次数。','','| 路线 | 方向正确 | 实际生成 token 范围 |','|---|---|---|']
for name in ['single','vector']:
    records=[c['conditions'][name] for c in cases]
    counts=[r['audit']['response']['tokens_predicted'] for r in records]
    lines.append(f'| {name} | {sum(r["correct"] for r in records)}/12 | {min(counts)}–{max(counts)} |')
lines+=['','| 目标 | 当前位置 | 正确方向 | 单 token 方向 | 自回归位移数组 |','|---|---|---|---|---|']
for c in cases:
    def choice(name):
        r=c['conditions'][name]
        return ('右' if r['actions'][0][1]>0 else '左')+(' ✓' if r['correct'] else ' ✗')
    lines.append(f'| {c["goal"]} | {c["current"]} | {"右" if c["expected_direction"]>0 else "左"} | {choice("single")} | {choice("vector")} |')
lines+=['',f'完整请求/响应：runs/{output.name}。未执行任何在线环境动作。']
(probe.ROOT/'vector-comparison.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print('Report saved: vector-comparison.md',flush=True)
