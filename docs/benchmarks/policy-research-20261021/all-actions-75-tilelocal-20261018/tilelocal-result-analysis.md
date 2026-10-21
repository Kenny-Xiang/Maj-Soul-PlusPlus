# Tile-local 八终点独立聚合分析

**两个 tilelocal-mix 实际模型的立直完整Top1已超过75%，但全部动作目标尚未实现。** seed42/43立直分别为75.680%/75.488%，包含立直切牌参数；各自仍有弃牌、大明杠两项不足75%。原完整质量筛查与结构机制筛查均失败，不能晋级或部署。

本分析只读取该阶段完整 evaluation/report.json 与 decision.json，完成11084项聚合算术、计数、绑定及guard值/状态复核。2000次整局bootstrap区间引用decision，没有重读每局NPZ或独立重抽样；未读取样本、权重、原始数据、validation/test载荷或新训练日志。

本阶段采用新的8192局自然holdout（old4098/new4094），八模型在同一批窗口上比较。必须使用本阶段重新评估的bilinear控制值；前一阶段holdout不同，不能跨报告点值相减当成结构效果。报告中共2,591,645个选择窗口，forced=0；三麻chi不适用。用户目标、研究保护条件及正式验收分别报告，不互相替代。

## 八个实际模型的完整动作Top1

| 动作/正例支持 | 42双线性自然 | 42tile自然 | 42双线性混合 | 42tile混合 | 43双线性自然 | 43tile自然 | 43双线性混合 | 43tile混合 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| discard / 2043916 | 68.264% | 68.556% | 67.246% | 67.626% | 68.508% | 68.773% | 67.271% | 67.827% |
| riichi / 52048 | 53.126% | 63.088% | 68.041% | 75.680% | 50.119% | 60.704% | 71.826% | 75.488% |
| chi / 0 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| pon / 67723 | 68.633% | 68.297% | 79.382% | 78.864% | 67.831% | 68.336% | 75.465% | 77.330% |
| daiminkan / 431 | 2.320% | 1.856% | 60.325% | 63.341% | 5.104% | 5.568% | 53.596% | 51.508% |
| ankan / 4771 | 60.155% | 60.742% | 93.544% | 93.523% | 68.874% | 67.847% | 93.188% | 93.293% |
| shouminkan / 2613 | 71.642% | 64.677% | 98.814% | 98.622% | 71.642% | 65.672% | 98.431% | 98.240% |
| kita / 185274 | 97.558% | 97.595% | 97.843% | 97.850% | 98.082% | 97.896% | 98.203% | 98.134% |
| tsumo / 28381 | 99.954% | 99.979% | 100.000% | 99.993% | 99.993% | 99.982% | 99.993% | 99.993% |
| ron / 28885 | 100.000% | 99.993% | 99.997% | 99.997% | 100.000% | 99.997% | 99.997% | 99.997% |
| abort / 2095 | 98.998% | 98.759% | 100.000% | 100.000% | 97.900% | 98.043% | 100.000% | 100.000% |
| pass / 175508 | 90.771% | 90.686% | 86.188% | 86.832% | 91.337% | 91.400% | 88.737% | 88.884% |

N/A不能填为100%。每列是一个真实模型，没有按动作拼接跨模型最佳值。

- seed42-bilinear-natural 未严格>75：discard, riichi, pon, daiminkan, ankan, shouminkan。
- seed42-tilelocal-natural 未严格>75：discard, riichi, pon, daiminkan, ankan, shouminkan。
- seed42-bilinear-mix 未严格>75：discard, riichi, daiminkan。
- seed42-tilelocal-mix 未严格>75：discard, daiminkan。
- seed43-bilinear-natural 未严格>75：discard, riichi, pon, daiminkan, ankan, shouminkan。
- seed43-tilelocal-natural 未严格>75：discard, riichi, pon, daiminkan, ankan, shouminkan。
- seed43-bilinear-mix 未严格>75：discard, riichi, daiminkan。
- seed43-tilelocal-mix 未严格>75：discard, daiminkan。

| 模型 | 平均75缺口D | 最差动作 | macro | 总体Top1 | 自然NLL |
|---|---:|---:|---:|---:|---:|
| seed42-bilinear-natural | 0.114419 | 2.320% | 73.766% | 72.291% | 0.775853 |
| seed42-tilelocal-natural | 0.111622 | 1.856% | 74.021% | 72.704% | 0.758729 |
| seed42-bilinear-mix | 0.026716 | 60.325% | 86.489% | 71.879% | 0.790692 |
| seed42-tilelocal-mix | 0.017303 | 63.341% | 87.484% | 72.362% | 0.772441 |
| seed43-bilinear-natural | 0.107202 | 5.104% | 74.490% | 72.494% | 0.769597 |
| seed43-tilelocal-natural | 0.102818 | 5.568% | 74.929% | 72.912% | 0.753164 |
| seed43-bilinear-mix | 0.029370 | 53.596% | 86.064% | 72.068% | 0.783984 |
| seed43-tilelocal-mix | 0.027877 | 51.508% | 86.427% | 72.633% | 0.764676 |

## 同目标下 tilelocal−bilinear 的逐动作变化

以下Δ均为百分点。

| 动作 | 42自然 | 42混合 | 43自然 | 43混合 |
|---|---:|---:|---:|---:|
| discard | +0.292 | +0.380 | +0.266 | +0.556 |
| riichi | +9.962 | +7.639 | +10.584 | +3.662 |
| chi | N/A | N/A | N/A | N/A |
| pon | -0.335 | -0.518 | +0.505 | +1.865 |
| daiminkan | -0.464 | +3.016 | +0.464 | -2.088 |
| ankan | +0.587 | -0.021 | -1.027 | +0.105 |
| shouminkan | -6.965 | -0.191 | -5.970 | -0.191 |
| kita | +0.037 | +0.007 | -0.187 | -0.069 |
| tsumo | +0.025 | -0.007 | -0.011 | +0.000 |
| ron | -0.007 | +0.000 | -0.003 | +0.000 |
| abort | -0.239 | +0.000 | +0.143 | +0.000 |
| pass | -0.085 | +0.644 | +0.063 | +0.147 |

| 对照 | 弃牌Δ | 弃牌95%区间(pp) | 立直Δ | 立直95%区间(pp) | D改善95%区间 |
|---|---:|---:|---:|---:|---:|
| seed42-head-natural | +0.292 | [0.250, 0.336] | +9.962 | [9.573, 10.348] | [0.000222, 0.005446] |
| seed42-head-mix | +0.380 | [0.340, 0.420] | +7.639 | [7.283, 7.998] | [0.006351, 0.012688] |
| seed43-head-natural | +0.266 | [0.223, 0.303] | +10.584 | [10.206, 10.998] | [0.001521, 0.007413] |
| seed43-head-mix | +0.556 | [0.517, 0.598] | +3.662 | [3.327, 3.974] | [-0.001911, 0.004774] |

四个弃牌区间下界都大于0，但所有增益都小于冻结的≥1pp要求；不能用“显著大于0”替代预先定义的效果量。混合seed43的D改善区间跨0。自然目标的加杠退化分别−6.965/−5.970pp，且old/new同向，必须保留在结果中；自然43暗杠也下降1.027pp。

混合立直的95%点态区间分别为[75.329%,76.040%]、[75.124%,75.848%]。这支持本批内部holdout的立直改善，但不是全部动作、多seed同时置信保证，更不代表正式validation通过。混合立直precision仍仅53.500%/54.145%，低于60%保护条件；应保住完整召回改善并继续检查类型误报。

## 同结构的混合目标取舍

| 动作 | tile42 mix−natural(pp) | tile43 mix−natural(pp) |
|---|---:|---:|
| discard | -0.930 | -0.946 |
| riichi | +12.592 | +14.784 |
| chi | N/A | N/A |
| pon | +10.567 | +8.994 |
| daiminkan | +61.485 | +45.940 |
| ankan | +32.781 | +25.445 |
| shouminkan | +33.946 | +32.568 |
| kita | +0.255 | +0.239 |
| tsumo | +0.014 | +0.011 |
| ron | +0.003 | +0.000 |
| abort | +1.241 | +1.957 |
| pass | -3.854 | -2.516 |

混合目标使弃牌分别降低0.930/0.946pp，过降低3.854/2.516pp；提升了立直和稀有动作召回，但没有消除类型误报代价。不能仅因未达标动作数减少继续提高稀有正例权重。

## 全模型逐动作TP、FP、precision与FPR

TP是类型正确次数；precision=TP/预测该类型次数，FPR=FP/该类型合法且真实为其他类型的机会数。完整动作Top1另见前表；同类型参数选错仍会计入类型TP，不能混用。

| 模型 | 动作 | 类型TP | FP | precision | FPR | 自然负例机会 |
|---|---|---:|---:|---:|---:|---:|
| seed42-bilinear-natural | discard | 2010013 | 25884 | 98.729% | 10.294% | 251459 |
| seed42-bilinear-natural | riichi | 31979 | 21088 | 60.262% | 17.312% | 121809 |
| seed42-bilinear-natural | chi | 0 | 0 | N/A | N/A | 0 |
| seed42-bilinear-natural | pon | 46480 | 15880 | 74.535% | 8.846% | 179511 |
| seed42-bilinear-natural | daiminkan | 10 | 37 | 21.277% | 0.222% | 16639 |
| seed42-bilinear-natural | ankan | 2870 | 1587 | 64.393% | 6.665% | 23810 |
| seed42-bilinear-natural | shouminkan | 1874 | 1188 | 61.202% | 17.713% | 6707 |
| seed42-bilinear-natural | kita | 181752 | 9965 | 94.802% | 26.802% | 37180 |
| seed42-bilinear-natural | tsumo | 28368 | 177 | 99.380% | 99.438% | 178 |
| seed42-bilinear-natural | ron | 28885 | 262 | 99.101% | 100.000% | 262 |
| seed42-bilinear-natural | abort | 2074 | 384 | 84.378% | 90.141% | 426 |
| seed42-bilinear-natural | pass | 159311 | 21577 | 88.072% | 17.867% | 120762 |
| seed42-tilelocal-natural | discard | 2007719 | 20711 | 98.979% | 8.236% | 251459 |
| seed42-tilelocal-natural | riichi | 37223 | 23738 | 61.060% | 19.488% | 121809 |
| seed42-tilelocal-natural | chi | 0 | 0 | N/A | N/A | 0 |
| seed42-tilelocal-natural | pon | 46254 | 16152 | 74.118% | 8.998% | 179511 |
| seed42-tilelocal-natural | daiminkan | 8 | 30 | 21.053% | 0.180% | 16639 |
| seed42-tilelocal-natural | ankan | 2899 | 1750 | 62.357% | 7.350% | 23810 |
| seed42-tilelocal-natural | shouminkan | 1692 | 1158 | 59.368% | 17.266% | 6707 |
| seed42-tilelocal-natural | kita | 181853 | 9450 | 95.060% | 25.417% | 37180 |
| seed42-tilelocal-natural | tsumo | 28375 | 176 | 99.384% | 98.876% | 178 |
| seed42-tilelocal-natural | ron | 28883 | 262 | 99.101% | 100.000% | 262 |
| seed42-tilelocal-natural | abort | 2069 | 393 | 84.037% | 92.254% | 426 |
| seed42-tilelocal-natural | pass | 159161 | 21689 | 88.007% | 17.960% | 120762 |
| seed42-bilinear-mix | discard | 1985679 | 13656 | 99.317% | 5.431% | 251459 |
| seed42-bilinear-mix | riichi | 41139 | 36769 | 52.805% | 30.186% | 121809 |
| seed42-bilinear-mix | chi | 0 | 0 | N/A | N/A | 0 |
| seed42-bilinear-mix | pon | 53762 | 22365 | 70.621% | 12.459% | 179511 |
| seed42-bilinear-mix | daiminkan | 260 | 1614 | 13.874% | 9.700% | 16639 |
| seed42-bilinear-mix | ankan | 4464 | 6731 | 39.875% | 28.270% | 23810 |
| seed42-bilinear-mix | shouminkan | 2583 | 3612 | 41.695% | 53.854% | 6707 |
| seed42-bilinear-mix | kita | 182290 | 11206 | 94.209% | 30.140% | 37180 |
| seed42-bilinear-mix | tsumo | 28381 | 178 | 99.377% | 100.000% | 178 |
| seed42-bilinear-mix | ron | 28884 | 262 | 99.101% | 100.000% | 262 |
| seed42-bilinear-mix | abort | 2095 | 426 | 83.102% | 100.000% | 426 |
| seed42-bilinear-mix | pass | 151266 | 14023 | 91.516% | 11.612% | 120762 |
| seed42-tilelocal-mix | discard | 1983630 | 10016 | 99.498% | 3.983% | 251459 |
| seed42-tilelocal-mix | riichi | 44709 | 38860 | 53.500% | 31.902% | 121809 |
| seed42-tilelocal-mix | chi | 0 | 0 | N/A | N/A | 0 |
| seed42-tilelocal-mix | pon | 53411 | 21241 | 71.547% | 11.833% | 179511 |
| seed42-tilelocal-mix | daiminkan | 273 | 1589 | 14.662% | 9.550% | 16639 |
| seed42-tilelocal-mix | ankan | 4463 | 7098 | 38.604% | 29.811% | 23810 |
| seed42-tilelocal-mix | shouminkan | 2579 | 3806 | 40.392% | 56.747% | 6707 |
| seed42-tilelocal-mix | kita | 182358 | 10613 | 94.500% | 28.545% | 37180 |
| seed42-tilelocal-mix | tsumo | 28379 | 178 | 99.377% | 100.000% | 178 |
| seed42-tilelocal-mix | ron | 28884 | 262 | 99.101% | 100.000% | 262 |
| seed42-tilelocal-mix | abort | 2095 | 426 | 83.102% | 100.000% | 426 |
| seed42-tilelocal-mix | pass | 152397 | 14378 | 91.379% | 11.906% | 120762 |
| seed43-bilinear-natural | discard | 2009804 | 26252 | 98.711% | 10.440% | 251459 |
| seed43-bilinear-natural | riichi | 30202 | 19152 | 61.195% | 15.723% | 121809 |
| seed43-bilinear-natural | chi | 0 | 0 | N/A | N/A | 0 |
| seed43-bilinear-natural | pon | 45937 | 14822 | 75.605% | 8.257% | 179511 |
| seed43-bilinear-natural | daiminkan | 22 | 88 | 20.000% | 0.529% | 16639 |
| seed43-bilinear-natural | ankan | 3288 | 2310 | 58.735% | 9.702% | 23810 |
| seed43-bilinear-natural | shouminkan | 1875 | 1213 | 60.719% | 18.086% | 6707 |
| seed43-bilinear-natural | kita | 182745 | 11366 | 94.145% | 30.570% | 37180 |
| seed43-bilinear-natural | tsumo | 28379 | 178 | 99.377% | 100.000% | 178 |
| seed43-bilinear-natural | ron | 28885 | 262 | 99.101% | 100.000% | 262 |
| seed43-bilinear-natural | abort | 2051 | 394 | 83.885% | 92.488% | 426 |
| seed43-bilinear-natural | pass | 160304 | 22116 | 87.876% | 18.314% | 120762 |
| seed43-tilelocal-natural | discard | 2008642 | 21262 | 98.953% | 8.455% | 251459 |
| seed43-tilelocal-natural | riichi | 35724 | 21613 | 62.305% | 17.743% | 121809 |
| seed43-tilelocal-natural | chi | 0 | 0 | N/A | N/A | 0 |
| seed43-tilelocal-natural | pon | 46279 | 14759 | 75.820% | 8.222% | 179511 |
| seed43-tilelocal-natural | daiminkan | 24 | 79 | 23.301% | 0.475% | 16639 |
| seed43-tilelocal-natural | ankan | 3237 | 2161 | 59.967% | 9.076% | 23810 |
| seed43-tilelocal-natural | shouminkan | 1718 | 1143 | 60.049% | 17.042% | 6707 |
| seed43-tilelocal-natural | kita | 182401 | 10314 | 94.648% | 27.741% | 37180 |
| seed43-tilelocal-natural | tsumo | 28376 | 178 | 99.377% | 100.000% | 178 |
| seed43-tilelocal-natural | ron | 28884 | 262 | 99.101% | 100.000% | 262 |
| seed43-tilelocal-natural | abort | 2054 | 387 | 84.146% | 90.845% | 426 |
| seed43-tilelocal-natural | pass | 160415 | 21733 | 88.068% | 17.997% | 120762 |
| seed43-bilinear-mix | discard | 1979407 | 10648 | 99.465% | 4.234% | 251459 |
| seed43-bilinear-mix | riichi | 43506 | 42514 | 50.577% | 34.902% | 121809 |
| seed43-bilinear-mix | chi | 0 | 0 | N/A | N/A | 0 |
| seed43-bilinear-mix | pon | 51110 | 18275 | 73.661% | 10.180% | 179511 |
| seed43-bilinear-mix | daiminkan | 231 | 1199 | 16.154% | 7.206% | 16639 |
| seed43-bilinear-mix | ankan | 4447 | 5999 | 42.571% | 25.195% | 23810 |
| seed43-bilinear-mix | shouminkan | 2574 | 3356 | 43.406% | 50.037% | 6707 |
| seed43-bilinear-mix | kita | 183017 | 12663 | 93.529% | 34.059% | 37180 |
| seed43-bilinear-mix | tsumo | 28379 | 178 | 99.377% | 100.000% | 178 |
| seed43-bilinear-mix | ron | 28884 | 262 | 99.101% | 100.000% | 262 |
| seed43-bilinear-mix | abort | 2095 | 426 | 83.102% | 100.000% | 426 |
| seed43-bilinear-mix | pass | 155741 | 16734 | 90.298% | 13.857% | 120762 |
| seed43-tilelocal-mix | discard | 1984369 | 9824 | 99.507% | 3.907% | 251459 |
| seed43-tilelocal-mix | riichi | 44469 | 37661 | 54.145% | 30.918% | 121809 |
| seed43-tilelocal-mix | chi | 0 | 0 | N/A | N/A | 0 |
| seed43-tilelocal-mix | pon | 52371 | 18007 | 74.414% | 10.031% | 179511 |
| seed43-tilelocal-mix | daiminkan | 222 | 1204 | 15.568% | 7.236% | 16639 |
| seed43-tilelocal-mix | ankan | 4453 | 6808 | 39.544% | 28.593% | 23810 |
| seed43-tilelocal-mix | shouminkan | 2569 | 3581 | 41.772% | 53.392% | 6707 |
| seed43-tilelocal-mix | kita | 182862 | 11536 | 94.066% | 31.027% | 37180 |
| seed43-tilelocal-mix | tsumo | 28379 | 178 | 99.377% | 100.000% | 178 |
| seed43-tilelocal-mix | ron | 28884 | 262 | 99.101% | 100.000% | 262 |
| seed43-tilelocal-mix | abort | 2095 | 426 | 83.102% | 100.000% | 426 |
| seed43-tilelocal-mix | pass | 155999 | 15486 | 90.969% | 12.824% | 120762 |

大明杠在当前holdout的M=0，没有同类型参数竞争。tile混合42为273/431正确、1589个误报（precision14.662%、FPR9.550%）；混合43为222/431正确、1204个误报（15.568%、7.236%）。混合43相对控制少9个正确、又多5个误报；这不是整体进步。

## 候选内排序与fitMonitor/holdout

N为真实动作数，C为完整正确，T为类型正确，Q为给定真实类型后的候选正确，M为同类型多候选数。N−C=(N−T)+(T−C)=(N−Q)+(Q−C)。多候选条件准确率=(Q−N+M)/M；M=0应为N/A。Q仅是诊断时的类型oracle，真实推理不得读取标签。

| 模型 | 动作 | fit完整 | hold完整 | fit多候选条件 | hold多候选条件 | fit M | hold M | hold Q/N |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| seed42-bilinear-natural | discard | 68.942% | 68.264% | 69.884% | 69.232% | 63813 | 2043916 | 69.232% |
| seed42-bilinear-natural | riichi | 53.601% | 53.126% | 70.993% | 67.692% | 755 | 25251 | 84.326% |
| seed42-tilelocal-natural | discard | 69.094% | 68.556% | 70.072% | 69.566% | 63813 | 2043916 | 69.566% |
| seed42-tilelocal-natural | riichi | 62.588% | 63.088% | 73.775% | 71.265% | 755 | 25251 | 86.059% |
| seed42-bilinear-mix | discard | 67.923% | 67.246% | 69.597% | 68.946% | 63813 | 2043916 | 68.946% |
| seed42-bilinear-mix | riichi | 70.937% | 68.041% | 72.185% | 68.275% | 755 | 25251 | 84.608% |
| seed42-tilelocal-mix | discard | 68.253% | 67.626% | 69.920% | 69.337% | 63813 | 2043916 | 69.337% |
| seed42-tilelocal-mix | riichi | 76.418% | 75.680% | 76.026% | 72.678% | 755 | 25251 | 86.745% |
| seed43-bilinear-natural | discard | 69.221% | 68.508% | 70.152% | 69.465% | 63813 | 2043916 | 69.465% |
| seed43-bilinear-natural | riichi | 52.390% | 50.119% | 72.053% | 67.391% | 755 | 25251 | 84.180% |
| seed43-tilelocal-natural | discard | 69.323% | 68.773% | 70.288% | 69.746% | 63813 | 2043916 | 69.746% |
| seed43-tilelocal-natural | riichi | 61.058% | 60.704% | 74.172% | 71.498% | 755 | 25251 | 86.172% |
| seed43-bilinear-mix | discard | 67.862% | 67.271% | 69.757% | 69.164% | 63813 | 2043916 | 69.164% |
| seed43-bilinear-mix | riichi | 74.379% | 71.826% | 73.642% | 68.579% | 755 | 25251 | 84.756% |
| seed43-tilelocal-mix | discard | 68.461% | 67.827% | 70.092% | 69.514% | 63813 | 2043916 | 69.514% |
| seed43-tilelocal-mix | riichi | 78.649% | 75.488% | 79.205% | 73.086% | 755 | 25251 | 86.943% |

| 新模型 | 弃牌C | Q | N−Q候选内失败 | Q−C类型可挽救 | 候选内失败占全部错误 | typeNLL | withinNLL | 固定排序距75仍差 | 严格>75额外正确数 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| seed42-tilelocal-natural | 1401226 | 1421876 | 622040 | 20650 | 96.787% | 0.028387 | 0.848706 | 5.434pp | 131712 |
| seed42-tilelocal-mix | 1382218 | 1417199 | 626717 | 34981 | 94.713% | 0.051316 | 0.855793 | 5.663pp | 150720 |
| seed43-tilelocal-natural | 1405665 | 1425546 | 618370 | 19881 | 96.885% | 0.029237 | 0.843285 | 5.254pp | 127273 |
| seed43-tilelocal-mix | 1386324 | 1420807 | 623109 | 34483 | 94.756% | 0.052113 | 0.849275 | 5.486pp | 146614 |

| 新模型 | 弃牌其他类型错误 | 基础牌错误 | 赤牌错误 | 摸切来源错误 | 基础牌错误占全部错误 |
|---|---:|---:|---:|---:|---:|
| seed42-tilelocal-natural | 36197 | 598607 | 101 | 7785 | 93.141% |
| seed42-tilelocal-mix | 60286 | 593705 | 108 | 7599 | 89.724% |
| seed43-tilelocal-natural | 35274 | 594705 | 116 | 8156 | 93.177% |
| seed43-tilelocal-mix | 59547 | 590092 | 107 | 7846 | 89.735% |

tile弃牌的holdout条件准确率仅69.337%～69.746%，fitMonitor为69.920%～70.288%。只修动作类型偏置、保持同类型排序，不可能把完整弃牌推过75%。训练监控与holdout均低于目标且差距较小，支持把下一诊断集中在候选内结构比较；终点聚合不能证明收敛，也不能证明可见信息存在不可达上限。

立直有25,251个多候选窗口，全部立直支持52,048；新模型多候选条件准确率为71.265%～73.086%，相对控制约67%～69%有所提高。全部立直条件准确率约86%～87%包含单候选自然100%的贡献，因此两者必须分开报告。完整立直已达标的混合模型仍需保护这项改善。

fitMonitor只有256个已训练局、81,022个选择窗口，并非完整fit；其中大明杠仅12正例。其100%不能说明完整训练分布或泛化已解决。

## 正例支持及来源一致性

| 动作 | 全fit正例 | 全fit正例局 | hold正例 | hold正例局 | fitMonitor正例 | hold M |
|---|---:|---:|---:|---:|---:|---:|
| discard | 1014751 | 4096 | 2043916 | 8191 | 63813 | 2043916 |
| riichi | 25501 | 4077 | 52048 | 8170 | 1569 | 25251 |
| pon | 33812 | 4079 | 67723 | 8153 | 2134 | 81 |
| daiminkan | 223 | 215 | 431 | 410 | 12 | 0 |
| ankan | 2352 | 1787 | 4771 | 3649 | 142 | 19 |
| shouminkan | 1366 | 1178 | 2613 | 2242 | 91 | 10 |
| kita | 91940 | 4096 | 185274 | 8192 | 5843 | 2247 |
| tsumo | 13949 | 3974 | 28381 | 7915 | 889 | 0 |
| ron | 14376 | 4044 | 28885 | 8060 | 870 | 0 |
| abort | 1079 | 930 | 2095 | 1780 | 65 | 0 |
| pass | 86873 | 4096 | 175508 | 8187 | 5594 | 0 |

45项支持检查均通过。当前大明杠holdout为431正例/410局，16,639个自然负例机会；不能沿用前一阶段393/374的支持数。全fit及正例局数来源于已绑定decision，本分析未重读原准备文件或输入身份。

| 对照 | 动作 | old Δ(pp) | new Δ(pp) |
|---|---|---:|---:|
| seed42-head-natural | discard | +0.286 | +0.298 |
| seed42-head-natural | riichi | +10.230 | +9.693 |
| seed42-head-natural | pon | -0.303 | -0.368 |
| seed42-head-natural | daiminkan | -0.483 | -0.446 |
| seed42-head-natural | shouminkan | -8.665 | -5.330 |
| seed42-head-natural | pass | -0.098 | -0.073 |
| seed42-head-mix | discard | +0.393 | +0.366 |
| seed42-head-mix | riichi | +7.761 | +7.517 |
| seed42-head-mix | pon | -0.493 | -0.543 |
| seed42-head-mix | daiminkan | +0.966 | +4.911 |
| seed42-head-mix | shouminkan | +0.000 | -0.375 |
| seed42-head-mix | pass | +0.689 | +0.600 |
| seed42-tilelocal-objective | discard | -0.900 | -0.960 |
| seed42-tilelocal-objective | riichi | +12.473 | +12.712 |
| seed42-tilelocal-objective | pon | +10.604 | +10.529 |
| seed42-tilelocal-objective | daiminkan | +62.802 | +60.268 |
| seed42-tilelocal-objective | shouminkan | +33.333 | +34.535 |
| seed42-tilelocal-objective | pass | -3.799 | -3.909 |
| seed43-head-natural | discard | +0.240 | +0.291 |
| seed43-head-natural | riichi | +10.867 | +10.301 |
| seed43-head-natural | pon | +0.285 | +0.727 |
| seed43-head-natural | daiminkan | +0.966 | +0.000 |
| seed43-head-natural | shouminkan | -6.323 | -5.631 |
| seed43-head-natural | pass | +0.015 | +0.112 |
| seed43-head-mix | discard | +0.525 | +0.588 |
| seed43-head-mix | riichi | +3.781 | +3.543 |
| seed43-head-mix | pon | +1.848 | +1.883 |
| seed43-head-mix | daiminkan | -3.865 | -0.446 |
| seed43-head-mix | shouminkan | +0.078 | -0.450 |
| seed43-head-mix | pass | +0.088 | +0.206 |
| seed43-tilelocal-objective | discard | -0.921 | -0.971 |
| seed43-tilelocal-objective | riichi | +14.425 | +15.146 |
| seed43-tilelocal-objective | pon | +9.188 | +8.798 |
| seed43-tilelocal-objective | daiminkan | +44.444 | +47.321 |
| seed43-tilelocal-objective | shouminkan | +31.928 | +33.183 |
| seed43-tilelocal-objective | pass | -2.557 | -2.475 |

四个结构对照的弃牌及立直增益都在old/new同向；自然目标加杠退化也在两个来源同向。混合42大明杠两来源均增加召回，混合43两来源均减少召回。点值同向不等于来源效应完全相同，来源交互显著性没有在本分析中额外检验；全部来源指标及原decision配对区间保存在JSON。

## 原冻结筛查失败项

- 结构机制 seed42-head-natural：discard.accuracyImprovement, riichi.falsePositiveCountChange, pon.falsePositiveCountChange, ankan.falsePositiveCountChange, shouminkan.accuracyChange, abort.falsePositiveCountChange, pass.falsePositiveCountChange。
- 结构机制 seed42-head-mix：discard.accuracyImprovement, riichi.falsePositiveCountChange, ankan.falsePositiveCountChange, shouminkan.falsePositiveCountChange, pass.falsePositiveCountChange。
- 结构机制 seed43-head-natural：discard.accuracyImprovement, riichi.falsePositiveCountChange, ankan.accuracyChange, shouminkan.accuracyChange。
- 结构机制 seed43-head-mix：discard.accuracyImprovement, daiminkan.falsePositiveCountChange, daiminkan.accuracyChange, ankan.falsePositiveCountChange, shouminkan.falsePositiveCountChange。
- 完整质量 seed42-head-natural：meanDeficit.improvement, minimumAccuracy.improvement, macroAccuracy.improvement, riichi.falsePositiveRateChange, daiminkan.precision, shouminkan.accuracyChange。
- 完整质量 seed42-head-mix：meanDeficit.improvement, macroAccuracy.improvement, riichi.precision, daiminkan.precision, daiminkan.falsePositiveRate。
- 完整质量 seed42-tilelocal-objective：discard.protectedAccuracyChange, riichi.precision, riichi.falsePositiveRateChange, daiminkan.precision, daiminkan.falsePositiveRate, ankan.precisionChange, shouminkan.precisionChange, pass.accuracyChange, pass.protectedAccuracyChange。
- 完整质量 seed43-head-natural：meanDeficit.improvement, minimumAccuracy.improvement, macroAccuracy.improvement, riichi.falsePositiveRateChange, daiminkan.precision, ankan.accuracyChange, shouminkan.accuracyChange。
- 完整质量 seed43-head-mix：meanDeficit.improvement, minimumAccuracy.improvement, macroAccuracy.improvement, riichi.precision, daiminkan.accuracyChange, daiminkan.precision, daiminkan.falsePositiveRate, pairedDeficitImprovement.lower95。
- 完整质量 seed43-tilelocal-objective：discard.protectedAccuracyChange, riichi.precision, riichi.falsePositiveRateChange, daiminkan.precision, daiminkan.falsePositiveRate, ankan.precisionChange, shouminkan.precisionChange, pass.accuracyChange, pass.protectedAccuracyChange。

结构机制的natural与mix均为mechanism-not-demonstrated；完整质量为rejected-full-quality-screen；qualifiedForPromotion=false。早先bilinear拒绝结论保留，historicalAcceptancePolicy=not-assessed。所有门槛沿用原值，没有把本次立直达标改写成整体通过。

## 依据结果继续优化的方向

最清楚的剩余瓶颈是弃牌的候选内排序，而不是只调整动作类型偏好。下一诊断应检验从现有可见状态可计算的结构向听S、有效未见张数U，能否让模型更容易比较候选弃牌后的手牌结构；以同预算、同数据边界、同完整动作监督和原保护条件区分这种信息表达是否有效。当前证据仅支持这个问题值得检验，不保证特征会提升准确率。本报告不实现适配器、不创建或冻结下一实验；root负责结构特征实验。

大明杠则需要独立处理类型边界与自然机会负例：已完成原完整fit margin及原抽样曝光审计见 ../all-actions-75-bilinear-20261018/kan-fit-audit-20261018/result-review.md。其结论不能直接外推为tilelocal的完整fit结论，且不支持按训练曲线改部署阈值。不要让弃牌结构实验同时改变大明杠负例目标或采样，否则无法区别两项干预。

两混合模型立直跨过75%是实际进展，应保持完整参数定义并保护这项结果；尚存的precision/FPR及自然目标加杠退化仍需在完整动作向量中体现。当前没有任何一个实际模型达到全部适用动作>75%，没有晋级或部署。
