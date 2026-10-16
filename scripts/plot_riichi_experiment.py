"""Render stationary losses and action tradeoffs from the completed pilot report."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import MaxNLocator, PercentFormatter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    if report['status'] != 'complete':
        raise ValueError('Only completed, verified reports may be plotted')
    font_manager.fontManager.addfont('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
    plt.rcParams.update({'font.family': 'Arial Unicode MS', 'font.size': 11,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'axes.unicode_minus': False, 'svg.fonttype': 'path'})
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), layout='constrained')
    parent = report['models']['parent']
    for name, label, color in [('control', '原机会权重', '#2166ac'),
                                ('riichi2', '加入立直机会权重 2', '#d66027')]:
        model = report['models'][name]
        points = [parent] + model['history']
        epochs = list(range(len(points)))
        for axis, partition in [(axes[0, 0], 'validation'), (axes[0, 1], 'trainMonitor')]:
            axis.plot(epochs, [point[partition]['metrics']['choiceNll'] for point in points],
                      'o-', color=color, label=label, linewidth=2)
        riichi = [point['validation']['metrics']['byOpportunity']['riichi'] for point in points]
        for metric, suffix, style in [('exactPositiveRecall', '完整召回', '-'), ('precision', '精确率', '--')]:
            axes[1, 0].plot(epochs, [point[metric] for point in riichi],
                            marker='o', linestyle=style, color=color, label=label + ' · ' + suffix)
        kan = [point['validation']['metrics']['byOpportunity']['daiminkan'] for point in points]
        for metric, suffix, style in [('truePositive', '正确选择 TP', '-'), ('falsePositive', '误选 FP', '--')]:
            axes[1, 1].plot(epochs, [point[metric] for point in kan],
                            marker='o', linestyle=style, color=color, label=label + ' · ' + suffix)
    for axis, title, ylabel in [
        (axes[0, 0], '完整验证集：自然损失', 'NLL（越低越好）'),
        (axes[0, 1], '固定训练监测集：自然损失', 'NLL（未加权，越低越好）'),
        (axes[1, 0], '立直：召回与精确率同时观察', '比例'),
        (axes[1, 1], '大明杠：多选是否伴随更多误选', '验证窗口数')]:
        axis.set(title=title, xlabel='继续训练轮次（0 = 共同起点）', ylabel=ylabel)
        axis.set_xticks([0, 1, 2, 3])
        axis.grid(axis='y', alpha=.22)
        axis.legend(fontsize=8, loc='best', framealpha=.9)
    axes[1, 0].yaxis.set_major_formatter(PercentFormatter(1))
    axes[1, 1].yaxis.set_major_locator(MaxNLocator(integer=True))
    axes[1, 1].set_ylim(bottom=0)
    fig.suptitle('三麻立直机会窗口对照：固定 3 轮，按第 3 轮验收', fontsize=17)
    fig.supxlabel('2,048 场训练 / 512 场固定训练监测 / 4,706 场完整验证；指标衡量牌谱动作匹配，不代表实战强度。', fontsize=10)
    for extension in ('png', 'svg'):
        fig.savefig(args.report.with_suffix('.' + extension), dpi=180, facecolor='white')
    svg = args.report.with_suffix('.svg')
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines()) + '\n')
    plt.close(fig)


if __name__ == '__main__':
    main()
