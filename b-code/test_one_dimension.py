"""Controlled single-forward model experiment; not a deterministic unit test."""
import argparse
import json
import time
from pathlib import Path
import probe


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--prompt-layout',choices=['prefix','suffix'],default='suffix')
    args=parser.parse_args()
    cases = []
    output = probe.ROOT / 'runs' / f'one-dimension-{args.prompt_layout}-{time.time_ns()}.json'
    for goal in ['maximize', 'minimize']:
        for current in [-3, 0, 4]:
            for direction in [-1, 1]:
                target = current + direction * 2
                factor = -1 if goal == 'maximize' else 1
                history = [{'x': [x], 'height': factor * (x-target)**2}
                           for x in [current-1, current+1, current]]
                for swap in [False, True]:
                    actions, audit = probe.choose('http://127.0.0.1:18765', history,
                                                  1, 1, 1, goal, regret=False,
                                                  swap_labels=swap, prompt_layout=args.prompt_layout, action_symbols=probe.LABELS)
                    correct = actions == [[0, direction]]
                    case = {'goal': goal, 'current': current, 'target_evaluation_only': target,
                            'history': history, 'expected_direction': direction,
                            'swap_labels': swap, 'actions': actions, 'correct': correct,
                            'audit': audit}
                    cases.append(case)
                    output.write_text(json.dumps({'prompt_layout':args.prompt_layout,'cases': cases}, ensure_ascii=False, indent=2), encoding='utf-8')
                    print(goal, current, direction, 'swap', swap, 'chosen', actions, 'correct', correct, flush=True)
    lines = ['# 一维最小对照', '',
             '单峰负平方函数求极大值、单谷正平方函数求极小值。当前位置固定；历史依次包含当前位置左侧、右侧和当前位置的原始观测。目标点和正确方向不进入提示词。每次只有一个动作，关闭后悔，严格一次前向。', '',
             '三个当前位置 -3、0、4；两种正确方向；两种目标；交换 A/B 的左右含义，共 24 个案例。同一个案例交换标签时，历史数值完全不变。', '',
             '| 目标 | 坐标 | 正确方向 | 正常标签选择 | 交换标签选择 |',
             '|---|---|---|---|---|']
    for i in range(0, len(cases), 2):
        a,b = cases[i:i+2]
        def choice(c):
            return ('右' if c['actions'][0][1]>0 else '左') + (' ✓' if c['correct'] else ' ✗')
        lines.append(f'| {a["goal"]} | {a["current"]} | {"右" if a["expected_direction"]>0 else "左"} | {choice(a)} | {choice(b)} |')
    lines += ['', f'总正确率：{sum(c["correct"] for c in cases)}/{len(cases)}。']
    for swap in [False, True]:
        subset = [c for c in cases if c['swap_labels']==swap]
        lines.append(f'标签交换={swap}：{sum(c["correct"] for c in subset)}/{len(subset)}；首选 A 次数 {sum(c["audit"]["ranked"][0]["label"]=="A" for c in subset)}。')
    lines += ['', '这些案例属于同一任务的受控变体，不代表跨模型或开放环境的泛化准确率。', '', f'完整审计：runs/{output.name}。']
    (probe.ROOT / f'one-dimension-{args.prompt_layout}-report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(output, flush=True)


if __name__ == '__main__':
    main()
