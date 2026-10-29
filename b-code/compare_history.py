"""Read-only policy ablation on recorded checkpoints. Never advance the live run."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import probe


def distribution(audit, dims):
    probabilities = {entry['label']: entry['p'] for entry in audit['ranked']}
    labels = probe.LABELS[:2 * dims]
    if set(probabilities) != set(labels):
        raise RuntimeError('Incomplete legal token probabilities; cannot compare full distributions')
    mass = sum(probabilities.values())
    if mass <= 0:
        raise RuntimeError('Zero legal probability mass')
    # Evaluation only. Input values and choose() are untouched.
    return {label: probabilities[label] / mass for label in labels}, mass


def tv(p, q):
    return 0.5 * sum(abs(p[label] - q[label]) for label in p)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=probe.ROOT / 'runs' / 'latest.json')
    args = parser.parse_args()
    source = args.source.read_bytes()
    doc = json.loads(source)
    cfg = doc['config']
    dims, k, step = cfg['dims'], cfg['k'], cfg['step']
    indices = sorted({0, len(doc['steps']) // 2, len(doc['steps']) - 1})
    if not doc['steps']:
        raise ValueError('No recorded policy steps')
    result = {'source': str(args.source.resolve()), 'source_sha256': hashlib.sha256(source).hexdigest(),
              'source_run_id': doc.get('run_id'), 'config': cfg,
              'design': 'Same current observation last. Reverse only earlier observations. No environment actions executed.',
              'checkpoints': [], 'status': 'running'}
    output = probe.ROOT / 'runs' / f'compare-history-{time.time_ns()}.json'

    def save():
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')

    save()
    for index in indices:
        old_prompt = doc['steps'][index]['audit']['prompt']
        history = json.JSONDecoder().raw_decode(old_prompt.split('Raw history:\n', 1)[1])[0]
        current = history[-1]
        groups = {'original': history, 'reversed': list(reversed(history[:-1])) + [current],
                  'current_only': [current], 'original_repeat': history}
        checkpoint = {'policy_round': index + 1, 'observation_count': len(history),
                      'current': current, 'conditions': {}}
        for name, observations in groups.items():
            assert observations[-1] == current
            actions, audit = probe.choose(cfg['model_url'], observations, dims, k, step, goal=doc.get('goal','maximize'), prompt_layout=doc['steps'][index]['audit'].get('prompt_layout','prefix'))
            probabilities, mass = distribution(audit, dims)
            winner = audit['ranked'][0]
            record = {'actions': actions, 'top1': winner['label'],
                      'probabilities_legal_normalized': probabilities, 'returned_legal_mass': mass,
                      'audit': audit}
            if doc.get('objective') == 'coupled-ripple-v1':
                target = doc['target_evaluation_only']
                record['top1_height_delta_evaluation_only'] = probe.height(
                    probe.advance(current['x'], [winner['action']], step), target) - current['height']
                record['combined_height_delta_evaluation_only'] = probe.height(
                    probe.advance(current['x'], actions, step), target) - current['height']
            checkpoint['conditions'][name] = record
            print(f'round={index + 1} {name}: top1={winner["label"]} '
                  f'p={probabilities[winner["label"]]:.6f} mass={mass:.6f}', flush=True)
        base = checkpoint['conditions']['original']['probabilities_legal_normalized']
        checkpoint['tv_from_original'] = {name: tv(base, condition['probabilities_legal_normalized'])
                                          for name, condition in checkpoint['conditions'].items()}
        result['checkpoints'].append(checkpoint)
        save()
    result['status'] = 'complete'
    save()
    # A compact readable report, with links to the complete request/response audit.
    lines = ['# 历史输入对照实验', '', f'来源 SHA256：`{result["source_sha256"]}`', '',
             f'{dims} 维，原实验 K={k}，每个条件严格一个输出位置；未执行环境动作。', '',
             '反序组只反转当前观测之前的历史，当前位置始终保持在最后。TV 是合法动作分布的总变差距离，0 表示相同、1 表示完全不重叠；概率重归一化只用于评价。', '',
             '| 原轮次 | 条件 | 第一动作 | 概率 | 相对真实历史 TV | 第一动作高度变化 | 联合动作高度变化 |',
             '|---|---|---|---|---|---|---|']
    names = {'original': '真实历史', 'reversed': '反序历史', 'current_only': '仅当前位置',
             'original_repeat': '真实历史复测'}
    for point in result['checkpoints']:
        for name, condition in point['conditions'].items():
            label = condition['top1']
            delta = condition.get('top1_height_delta_evaluation_only', float('nan'))
            combined = condition.get('combined_height_delta_evaluation_only', float('nan'))
            lines.append(f'| {point["policy_round"]} | {names[name]} | {label} | '
                         f'{condition["probabilities_legal_normalized"][label]:.2%} | '
                         f'{point["tv_from_original"][name]:.4f} | {delta:+.4f} | {combined:+.4f} |')
    lines += ['', '动作表：' + json.dumps({label: [i//2, 1 if i%2==0 else -1]
                                          for i, label in enumerate(probe.LABELS[:2*dims])}), '',
              '高度变化来自隐藏环境的事后计算，不进入模型提示词，也不影响动作选择。真实历史复测用于检查同输入数值波动；三个检查点来自同一条轨迹，不能作为跨种子的统计结论。', '',
              f'完整审计：[{output.name}](runs/{output.name})']
    report = probe.ROOT / 'history-comparison.md'
    report.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(report, flush=True)


if __name__ == '__main__':
    main()
