# 双线性八终点独立结果分析

**所有实际模型仍未实现全部适用动作完整Top1严格高于75%。** 新结构显著恢复了seed42的弃牌能力；seed43仅有小幅提高，且立直等动作发生退化。两个bilinear-mix模型共同剩下弃牌、立直、大明杠三项未达标。

只读取完整evaluation/report.json与decision.json，独立完成11081项聚合算术、支持、绑定和guard值/状态复核。没有读取每局NPZ、输入身份、plan、权重、缓存、原始牌谱、test或新训练日志；bootstrap区间引用已完成decision，不宣称独立重抽样。

研究机制：natural与mix均mechanism-not-demonstrated；原完整质量筛查rejected-full-quality-screen。早先稳定版失败结论保留，历史正式验收not-assessed，提升资格false。这些状态与用户逐动作75%目标分别报告。

## 最有辨别力的结论

- 弃牌仍是候选内排序问题：四个bilinear模型的holdout条件选牌仅68.917%～69.491%，fitMonitor仅69.597%～70.152%。固定同类型排序、只校准动作类型，完整弃牌也不可能超过这些条件上界。
- 同类型排序失败解释bilinear弃牌94.216%～96.976%的完整错误；基础牌种错误占89.356%～93.650%。仅补赤牌或摸切身份不足以关闭差距。
- 立直的全部条件准确率约84%，但仅多候选窗口的条件准确率约66%～68%。其类型选择与参数选择均需观察，单候选窗口的自然100%不可掩盖参数差距。
- 大明杠在该holdout全部M=0，当前错误属于选不选该类型。mix的64.885%/54.707%完整召回仍伴随13.219%/14.972% precision，不能将提高正例召回当成全面改善。

## 八个实际模型完整Top1向量

| 动作 / 真实正例支持 | 42 stable自然 | 42 bilinear自然 | 42 stable混合 | 42 bilinear混合 | 43 stable自然 | 43 bilinear自然 | 43 stable混合 | 43 bilinear混合 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| discard / 2036343 | 37.679% | 68.281% | 37.081% | 67.219% | 67.765% | 68.532% | 66.992% | 67.242% |
| riichi / 51706 | 18.775% | 52.940% | 47.298% | 67.835% | 63.333% | 50.091% | 74.181% | 71.549% |
| chi / 0 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |
| pon / 67568 | 56.423% | 68.507% | 61.541% | 79.333% | 67.560% | 67.476% | 77.143% | 75.376% |
| daiminkan / 393 | 0.000% | 2.799% | 100.000% | 64.885% | 0.000% | 6.616% | 52.672% | 54.707% |
| ankan / 4770 | 33.166% | 58.700% | 98.616% | 92.558% | 62.117% | 69.036% | 92.956% | 92.306% |
| shouminkan / 2723 | 5.472% | 73.632% | 99.927% | 98.751% | 69.372% | 71.649% | 98.237% | 98.825% |
| kita / 184406 | 99.322% | 97.585% | 99.232% | 97.875% | 97.988% | 98.144% | 98.124% | 98.266% |
| tsumo / 28180 | 100.000% | 99.979% | 100.000% | 100.000% | 100.000% | 99.996% | 100.000% | 100.000% |
| ron / 28850 | 100.000% | 100.000% | 100.000% | 99.993% | 99.983% | 100.000% | 99.983% | 99.997% |
| abort / 2120 | 100.000% | 97.594% | 100.000% | 100.000% | 99.858% | 97.406% | 100.000% | 100.000% |
| pass / 174051 | 86.811% | 90.742% | 78.726% | 86.117% | 90.928% | 91.174% | 87.935% | 88.544% |

chi为三麻不适用，不能把N/A填为100%。各模型这批report的forced均为0，所有值均是完整候选匹配；立直包含弃牌参数。

- seed42-stable-natural 未严格>75：discard, riichi, pon, daiminkan, ankan, shouminkan。
- seed42-bilinear-natural 未严格>75：discard, riichi, pon, daiminkan, ankan, shouminkan。
- seed42-stable-mix 未严格>75：discard, riichi, pon。
- seed42-bilinear-mix 未严格>75：discard, riichi, daiminkan。
- seed43-stable-natural 未严格>75：discard, riichi, pon, daiminkan, ankan, shouminkan。
- seed43-bilinear-natural 未严格>75：discard, riichi, pon, daiminkan, ankan, shouminkan。
- seed43-stable-mix 未严格>75：discard, riichi, daiminkan。
- seed43-bilinear-mix 未严格>75：discard, riichi, daiminkan。

| 模型 | D | 最差动作 | macro | 总体Top1 | 自然NLL |
| --- | --- | --- | --- | --- | --- |
| seed42-stable-natural | 0.271350 | 0.000% | 57.968% | 46.888% | 1.542255 |
| seed42-bilinear-natural | 0.113765 | 2.799% | 73.705% | 72.290% | 0.776008 |
| seed42-stable-mix | 0.071891 | 37.081% | 83.857% | 46.806% | 1.570801 |
| seed42-bilinear-mix | 0.022782 | 64.885% | 86.779% | 71.844% | 0.791177 |
| seed43-stable-natural | 0.108957 | 0.000% | 74.446% | 72.111% | 0.798091 |
| seed43-bilinear-natural | 0.106001 | 6.616% | 74.556% | 72.491% | 0.769955 |
| seed43-stable-mix | 0.028323 | 52.672% | 86.202% | 71.873% | 0.809145 |
| seed43-bilinear-mix | 0.028638 | 54.707% | 86.074% | 72.023% | 0.784590 |

## 同目标下bilinear−stable的逐动作变化

所有Δ均为百分点；每列是一个真实成对结构对照。

| 动作 | 42自然 | 42混合 | 43自然 | 43混合 |
| --- | --- | --- | --- | --- |
| discard | +30.601 | +30.138 | +0.767 | +0.251 |
| riichi | +34.164 | +20.537 | -13.242 | -2.632 |
| chi | N/A | N/A | N/A | N/A |
| pon | +12.084 | +17.792 | -0.084 | -1.767 |
| daiminkan | +2.799 | -35.115 | +6.616 | +2.036 |
| ankan | +25.535 | -6.059 | +6.918 | -0.650 |
| shouminkan | +68.160 | -1.175 | +2.277 | +0.588 |
| kita | -1.737 | -1.357 | +0.156 | +0.143 |
| tsumo | -0.021 | +0.000 | -0.004 | +0.000 |
| ron | +0.000 | -0.007 | +0.017 | +0.014 |
| abort | -2.406 | +0.000 | -2.453 | +0.000 |
| pass | +3.932 | +7.390 | +0.246 | +0.608 |

| 对照 | 弃牌Δ | 弃牌95%区间（百分点） | D改善 | D改善95%区间 |
| --- | --- | --- | --- | --- |
| seed42-head-natural | +30.601 | [30.512, 30.696] | 0.157585 | [0.154844, 0.160145] |
| seed42-head-mix | +30.138 | [30.051, 30.228] | 0.049109 | [0.044516, 0.053545] |
| seed43-head-natural | +0.767 | [0.720, 0.814] | 0.002956 | [0.000052, 0.006121] |
| seed43-head-mix | +0.251 | [0.206, 0.297] | -0.000314 | [-0.004647, 0.004202] |

四个弃牌变化区间均在0以上，但seed43两目标分别只有+0.767/+0.251个百分点，未达预先固定的≥1个百分点机制要求。seed42自然还出现拔北−1.737、九种九牌−2.406个百分点；seed43自然立直−13.242个百分点。因此不能用弃牌平均增益概括全部动作，也不能据此声称结构方向毫无价值。

## 混合目标相对同结构自然目标

| 动作 | bilinear42 mix−natural | bilinear43 mix−natural |
| --- | --- | --- |
| discard | -1.061 | -1.289 |
| riichi | +14.896 | +21.458 |
| chi | N/A | N/A |
| pon | +10.826 | +7.900 |
| daiminkan | +62.087 | +48.092 |
| ankan | +33.857 | +23.270 |
| shouminkan | +25.119 | +27.176 |
| kita | +0.291 | +0.122 |
| tsumo | +0.021 | +0.004 |
| ron | -0.007 | -0.003 |
| abort | +2.406 | +2.594 |
| pass | -4.626 | -2.631 |

这次结构变化仍未消除目标加权取舍：两seed混合目标都降低弃牌、过，同时提高多个稀有动作召回。已有正例加权强度不应仅因D改善继续加大。

## 各模型逐动作TP、FP与机会窗误报

precision=类型TP/预测该类型次数；FPR=类型FP/该类型合法且真实为其他类型的机会数。它们不等于完整动作Top1。

| 模型 | 动作 | TP | FP | precision | FPR | 负例机会 |
| --- | --- | --- | --- | --- | --- | --- |
| seed42-stable-natural | discard | 1927996 | 41512 | 97.892% | 16.572% | 250496 |
| seed42-stable-natural | riichi | 15310 | 71198 | 17.698% | 58.384% | 121947 |
| seed42-stable-natural | chi | 0 | 0 | N/A | N/A | 0 |
| seed42-stable-natural | pon | 38124 | 22740 | 62.638% | 12.770% | 178071 |
| seed42-stable-natural | daiminkan | 0 | 0 | N/A | 0.000% | 16659 |
| seed42-stable-natural | ankan | 1583 | 1705 | 48.145% | 6.974% | 24449 |
| seed42-stable-natural | shouminkan | 149 | 1017 | 12.779% | 16.353% | 6219 |
| seed42-stable-natural | kita | 184290 | 34625 | 84.183% | 94.860% | 36501 |
| seed42-stable-natural | tsumo | 28180 | 204 | 99.281% | 100.000% | 204 |
| seed42-stable-natural | ron | 28850 | 265 | 99.090% | 100.000% | 265 |
| seed42-stable-natural | abort | 2120 | 461 | 82.139% | 100.000% | 461 |
| seed42-stable-natural | pass | 151095 | 29686 | 83.579% | 24.693% | 120220 |
| seed42-bilinear-natural | discard | 2002839 | 25658 | 98.735% | 10.243% | 250496 |
| seed42-bilinear-natural | riichi | 31699 | 21037 | 60.109% | 17.251% | 121947 |
| seed42-bilinear-natural | chi | 0 | 0 | N/A | N/A | 0 |
| seed42-bilinear-natural | pon | 46289 | 15791 | 74.563% | 8.868% | 178071 |
| seed42-bilinear-natural | daiminkan | 11 | 38 | 22.449% | 0.228% | 16659 |
| seed42-bilinear-natural | ankan | 2801 | 1644 | 63.015% | 6.724% | 24449 |
| seed42-bilinear-natural | shouminkan | 2005 | 1052 | 65.587% | 16.916% | 6219 |
| seed42-bilinear-natural | kita | 181033 | 9715 | 94.907% | 26.616% | 36501 |
| seed42-bilinear-natural | tsumo | 28174 | 203 | 99.285% | 99.510% | 204 |
| seed42-bilinear-natural | ron | 28850 | 265 | 99.090% | 100.000% | 265 |
| seed42-bilinear-natural | abort | 2069 | 416 | 83.260% | 90.239% | 461 |
| seed42-bilinear-natural | pass | 157938 | 21583 | 87.977% | 17.953% | 120220 |
| seed42-stable-mix | discard | 1879787 | 15203 | 99.198% | 6.069% | 250496 |
| seed42-stable-mix | riichi | 35393 | 96113 | 26.914% | 78.815% | 121947 |
| seed42-stable-mix | chi | 0 | 0 | N/A | N/A | 0 |
| seed42-stable-mix | pon | 41582 | 20759 | 66.701% | 11.658% | 178071 |
| seed42-stable-mix | daiminkan | 393 | 16570 | 2.317% | 99.466% | 16659 |
| seed42-stable-mix | ankan | 4713 | 20965 | 18.354% | 85.750% | 24449 |
| seed42-stable-mix | shouminkan | 2721 | 5939 | 31.420% | 95.498% | 6219 |
| seed42-stable-mix | kita | 184115 | 34436 | 84.243% | 94.343% | 36501 |
| seed42-stable-mix | tsumo | 28180 | 204 | 99.281% | 100.000% | 204 |
| seed42-stable-mix | ron | 28850 | 265 | 99.090% | 100.000% | 265 |
| seed42-stable-mix | abort | 2120 | 461 | 82.139% | 100.000% | 461 |
| seed42-stable-mix | pass | 137024 | 25317 | 84.405% | 21.059% | 120220 |
| seed42-bilinear-mix | discard | 1978443 | 13452 | 99.325% | 5.370% | 250496 |
| seed42-bilinear-mix | riichi | 40895 | 36891 | 52.574% | 30.252% | 121947 |
| seed42-bilinear-mix | chi | 0 | 0 | N/A | N/A | 0 |
| seed42-bilinear-mix | pon | 53605 | 22225 | 70.691% | 12.481% | 178071 |
| seed42-bilinear-mix | daiminkan | 255 | 1674 | 13.219% | 10.049% | 16659 |
| seed42-bilinear-mix | ankan | 4417 | 6991 | 38.718% | 28.594% | 24449 |
| seed42-bilinear-mix | shouminkan | 2689 | 3237 | 45.376% | 52.050% | 6219 |
| seed42-bilinear-mix | kita | 181528 | 10842 | 94.364% | 29.703% | 36501 |
| seed42-bilinear-mix | tsumo | 28180 | 204 | 99.281% | 100.000% | 204 |
| seed42-bilinear-mix | ron | 28848 | 265 | 99.090% | 100.000% | 265 |
| seed42-bilinear-mix | abort | 2120 | 461 | 82.139% | 100.000% | 461 |
| seed42-bilinear-mix | pass | 149887 | 14001 | 91.457% | 11.646% | 120220 |
| seed43-stable-natural | discard | 1994588 | 17845 | 99.113% | 7.124% | 250496 |
| seed43-stable-natural | riichi | 38632 | 27738 | 58.207% | 22.746% | 121947 |
| seed43-stable-natural | chi | 0 | 0 | N/A | N/A | 0 |
| seed43-stable-natural | pon | 45649 | 15502 | 74.650% | 8.706% | 178071 |
| seed43-stable-natural | daiminkan | 0 | 0 | N/A | 0.000% | 16659 |
| seed43-stable-natural | ankan | 2964 | 2155 | 57.902% | 8.814% | 24449 |
| seed43-stable-natural | shouminkan | 1889 | 1173 | 61.692% | 18.862% | 6219 |
| seed43-stable-natural | kita | 181836 | 10564 | 94.509% | 28.942% | 36501 |
| seed43-stable-natural | tsumo | 28180 | 204 | 99.281% | 100.000% | 204 |
| seed43-stable-natural | ron | 28845 | 265 | 99.090% | 100.000% | 265 |
| seed43-stable-natural | abort | 2117 | 459 | 82.182% | 99.566% | 461 |
| seed43-stable-natural | pass | 158261 | 22244 | 87.677% | 18.503% | 120220 |
| seed43-bilinear-natural | discard | 2002378 | 25770 | 98.729% | 10.288% | 250496 |
| seed43-bilinear-natural | riichi | 30130 | 19307 | 60.946% | 15.832% | 121947 |
| seed43-bilinear-natural | chi | 0 | 0 | N/A | N/A | 0 |
| seed43-bilinear-natural | pon | 45592 | 15003 | 75.241% | 8.425% | 178071 |
| seed43-bilinear-natural | daiminkan | 26 | 68 | 27.660% | 0.408% | 16659 |
| seed43-bilinear-natural | ankan | 3293 | 2364 | 58.211% | 9.669% | 24449 |
| seed43-bilinear-natural | shouminkan | 1951 | 1097 | 64.009% | 17.639% | 6219 |
| seed43-bilinear-natural | kita | 182063 | 11123 | 94.242% | 30.473% | 36501 |
| seed43-bilinear-natural | tsumo | 28179 | 204 | 99.281% | 100.000% | 204 |
| seed43-bilinear-natural | ron | 28850 | 265 | 99.090% | 100.000% | 265 |
| seed43-bilinear-natural | abort | 2065 | 425 | 82.932% | 92.191% | 461 |
| seed43-bilinear-natural | pass | 158690 | 22267 | 87.695% | 18.522% | 120220 |
| seed43-stable-mix | discard | 1974318 | 8815 | 99.556% | 3.519% | 250496 |
| seed43-stable-mix | riichi | 45013 | 40541 | 52.614% | 33.245% | 121947 |
| seed43-stable-mix | chi | 0 | 0 | N/A | N/A | 0 |
| seed43-stable-mix | pon | 52124 | 19643 | 72.629% | 11.031% | 178071 |
| seed43-stable-mix | daiminkan | 207 | 1056 | 16.390% | 6.339% | 16659 |
| seed43-stable-mix | ankan | 4436 | 7382 | 37.536% | 30.193% | 24449 |
| seed43-stable-mix | shouminkan | 2675 | 3060 | 46.643% | 49.204% | 6219 |
| seed43-stable-mix | kita | 182074 | 11069 | 94.269% | 30.325% | 36501 |
| seed43-stable-mix | tsumo | 28180 | 204 | 99.281% | 100.000% | 204 |
| seed43-stable-mix | ron | 28845 | 265 | 99.090% | 100.000% | 265 |
| seed43-stable-mix | abort | 2120 | 461 | 82.139% | 100.000% | 461 |
| seed43-stable-mix | pass | 153052 | 15570 | 90.766% | 12.951% | 120220 |
| seed43-bilinear-mix | discard | 1972277 | 10432 | 99.474% | 4.165% | 250496 |
| seed43-bilinear-mix | riichi | 43196 | 42537 | 50.384% | 34.882% | 121947 |
| seed43-bilinear-mix | chi | 0 | 0 | N/A | N/A | 0 |
| seed43-bilinear-mix | pon | 50930 | 18439 | 73.419% | 10.355% | 178071 |
| seed43-bilinear-mix | daiminkan | 215 | 1221 | 14.972% | 7.329% | 16659 |
| seed43-bilinear-mix | ankan | 4405 | 6303 | 41.137% | 25.780% | 24449 |
| seed43-bilinear-mix | shouminkan | 2691 | 2988 | 47.385% | 48.046% | 6219 |
| seed43-bilinear-mix | kita | 182316 | 12240 | 93.709% | 33.533% | 36501 |
| seed43-bilinear-mix | tsumo | 28180 | 204 | 99.281% | 100.000% | 204 |
| seed43-bilinear-mix | ron | 28849 | 265 | 99.090% | 100.000% | 265 |
| seed43-bilinear-mix | abort | 2120 | 461 | 82.139% | 100.000% | 461 |
| seed43-bilinear-mix | pass | 154111 | 16730 | 90.207% | 13.916% | 120220 |

## 参数选择与训练侧/自然holdout

N为真实动作样本，C为完整正确，T为类型正确，Q为给定真实类型后的候选正确，M为同类型多候选窗口数。完整错误恒等式N−C=(N−T)+(T−C)=(N−Q)+(Q−C)。真正多候选条件准确率为(Q−N+M)/M，M=0为N/A；这是诊断指标，推理时不能读取真实类型。

| 模型 | 动作 | fit完整 | hold完整 | fit多候选条件 | hold多候选条件 | fit M | hold M | hold Q/N |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| seed42-stable-natural | discard | 37.763% | 37.679% | 40.429% | 40.321% | 63813 | 2036343 | 40.321% |
| seed42-stable-natural | riichi | 19.439% | 18.775% | 45.033% | 44.842% | 755 | 24930 | 73.405% |
| seed42-bilinear-natural | discard | 68.942% | 68.281% | 69.884% | 69.240% | 63813 | 2036343 | 69.240% |
| seed42-bilinear-natural | riichi | 53.601% | 52.940% | 70.993% | 67.084% | 755 | 24930 | 84.130% |
| seed42-stable-mix | discard | 37.209% | 37.081% | 40.434% | 40.324% | 63813 | 2036343 | 40.324% |
| seed42-stable-mix | riichi | 48.311% | 47.298% | 44.901% | 44.854% | 755 | 24930 | 73.411% |
| seed42-bilinear-mix | discard | 67.923% | 67.219% | 69.597% | 68.917% | 63813 | 2036343 | 68.917% |
| seed42-bilinear-mix | riichi | 70.937% | 67.835% | 72.185% | 67.389% | 755 | 24930 | 84.276% |
| seed43-stable-natural | discard | 68.593% | 67.765% | 69.715% | 68.898% | 63813 | 2036343 | 68.898% |
| seed43-stable-natural | riichi | 65.137% | 63.333% | 72.715% | 66.996% | 755 | 24930 | 84.087% |
| seed43-bilinear-natural | discard | 69.221% | 68.532% | 70.152% | 69.491% | 63813 | 2036343 | 69.491% |
| seed43-bilinear-natural | riichi | 52.390% | 50.091% | 72.053% | 66.482% | 755 | 24930 | 83.839% |
| seed43-stable-mix | discard | 67.800% | 66.992% | 69.539% | 68.697% | 63813 | 2036343 | 68.697% |
| seed43-stable-mix | riichi | 76.482% | 74.181% | 72.715% | 68.107% | 755 | 24930 | 84.623% |
| seed43-bilinear-mix | discard | 67.862% | 67.242% | 69.757% | 69.137% | 63813 | 2036343 | 69.137% |
| seed43-bilinear-mix | riichi | 74.379% | 71.549% | 73.642% | 67.834% | 755 | 24930 | 84.491% |

| bilinear模型 | 弃牌C | Q | N−Q候选内失败 | Q−C类型可挽救 | 候选内失败占全部错误 | typeNLL | withinNLL | 固定排序下距75仍差 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| seed42-bilinear-natural | 1390426 | 1409961 | 626382 | 19535 | 96.976% | 0.029516 | 0.864440 | 5.760pp |
| seed42-bilinear-mix | 1368813 | 1403388 | 632955 | 34575 | 94.820% | 0.051359 | 0.873732 | 6.083pp |
| seed43-bilinear-natural | 1395537 | 1415077 | 621266 | 19540 | 96.951% | 0.031043 | 0.856894 | 5.509pp |
| seed43-bilinear-mix | 1369287 | 1407870 | 628473 | 38583 | 94.216% | 0.055328 | 0.867131 | 5.863pp |

bilinear弃牌达到严格75%还分别需要额外正确：42自然136,832、42混合158,445、43自然131,721、43混合157,971个当前holdout窗口；这是同一固定holdout上的差距计数，不是可以通过重标签或选样本取得的额度。

fitMonitor只有256个已训练局、81,022个动作窗口，且不是完整fit。弃牌fit与hold较接近且均明显不足75%，支持优先改善候选内拟合；终点聚合不能证明训练已收敛、不能断言任务不可达，也不能排除可见状态缺失造成的不可约歧义。

## 真实动作支持

| 动作 | 全fit正例 | 全fit正例局数 | hold正例 | hold正例局数 | fitMonitor正例 | hold M |
| --- | --- | --- | --- | --- | --- | --- |
| discard | 1014751 | 4096 | 2036343 | 8192 | 63813 | 2036343 |
| riichi | 25501 | 4077 | 51706 | 8169 | 1569 | 24930 |
| pon | 33812 | 4079 | 67568 | 8153 | 2134 | 67 |
| daiminkan | 223 | 215 | 393 | 374 | 12 | 0 |
| ankan | 2352 | 1787 | 4770 | 3646 | 142 | 17 |
| shouminkan | 1366 | 1178 | 2723 | 2294 | 91 | 8 |
| kita | 91940 | 4096 | 184406 | 8191 | 5843 | 2396 |
| tsumo | 13949 | 3974 | 28180 | 7933 | 889 | 0 |
| ron | 14376 | 4044 | 28850 | 8079 | 870 | 0 |
| abort | 1079 | 930 | 2120 | 1831 | 65 | 0 |
| pass | 86873 | 4096 | 174051 | 8188 | 5594 | 0 |

45项冻结支持检查均通过。大明杠holdout为393正例/374局，16,659负例机会；fitMonitor却仅12正例，混合模型的fitMonitor大明杠100%不能当成充分的泛化证据。全fit与正例局数来自decision已核验支持；本次没有重读准备文件，不能宣称再次独立核验原始支持身份。

## 来源一致性

| 比较 | 动作 | old Δ百分点 | new Δ百分点 |
| --- | --- | --- | --- |
| seed42-head-natural | discard | +30.582 | +30.621 |
| seed42-head-natural | riichi | +34.481 | +33.842 |
| seed42-head-natural | pon | +12.098 | +12.070 |
| seed42-head-natural | daiminkan | +2.732 | +2.857 |
| seed42-head-natural | pass | +3.951 | +3.912 |
| seed42-head-mix | discard | +30.145 | +30.131 |
| seed42-head-mix | riichi | +20.630 | +20.442 |
| seed42-head-mix | pon | +17.973 | +17.609 |
| seed42-head-mix | daiminkan | -36.612 | -33.810 |
| seed42-head-mix | pass | +7.448 | +7.332 |
| seed42-bilinear-objective | discard | -1.026 | -1.098 |
| seed42-bilinear-objective | riichi | +14.706 | +15.089 |
| seed42-bilinear-objective | pon | +10.909 | +10.742 |
| seed42-bilinear-objective | daiminkan | +60.656 | +63.333 |
| seed42-bilinear-objective | pass | -4.685 | -4.565 |
| seed43-head-natural | discard | +0.759 | +0.774 |
| seed43-head-natural | riichi | -12.923 | -13.567 |
| seed43-head-natural | pon | +0.050 | -0.220 |
| seed43-head-natural | daiminkan | +7.650 | +5.714 |
| seed43-head-natural | pass | +0.266 | +0.227 |
| seed43-head-mix | discard | +0.234 | +0.268 |
| seed43-head-mix | riichi | -2.849 | -2.411 |
| seed43-head-mix | pon | -1.433 | -2.105 |
| seed43-head-mix | daiminkan | +7.650 | -2.857 |
| seed43-head-mix | pass | +0.732 | +0.483 |
| seed43-bilinear-objective | discard | -1.285 | -1.294 |
| seed43-bilinear-objective | riichi | +20.907 | +22.019 |
| seed43-bilinear-objective | pon | +8.017 | +7.782 |
| seed43-bilinear-objective | daiminkan | +49.180 | +47.143 |
| seed43-bilinear-objective | pass | -2.601 | -2.661 |

old/new固定各4,098/4,094局。同head弃牌改善及混合目标造成的弃牌/过下降均在两来源同向。seed43混合head的大明杠old为+7.650pp、new为−2.857pp，来源表现并非处处一致；不能把合并+2.036pp当成两个来源均改善，也不能把单个区间跨0当成来源间差异显著的检验。全部动作来源点值与配对区间保存在JSON。

## 冻结筛查的失败项

- 结构机制 seed42-head-natural：daiminkan.falsePositiveCountChange, shouminkan.falsePositiveCountChange, kita.accuracyChange, abort.accuracyChange。
- 结构机制 seed42-head-mix：pon.falsePositiveCountChange, daiminkan.accuracyChange, daiminkan.preserveAbove75Strict, ankan.accuracyChange, shouminkan.accuracyChange, kita.accuracyChange。
- 结构机制 seed43-head-natural：discard.accuracyImprovement, discard.falsePositiveCountChange, riichi.accuracyChange, daiminkan.falsePositiveCountChange, ankan.falsePositiveCountChange, kita.falsePositiveCountChange, abort.accuracyChange, pass.falsePositiveCountChange。
- 结构机制 seed43-head-mix：discard.accuracyImprovement, discard.falsePositiveCountChange, riichi.falsePositiveCountChange, riichi.accuracyChange, pon.accuracyChange, daiminkan.falsePositiveCountChange, kita.falsePositiveCountChange, pass.falsePositiveCountChange。
- 完整质量 seed42-head-natural：minimumAccuracy.improvement, daiminkan.precision, kita.accuracyChange, abort.accuracyChange。
- 完整质量 seed42-head-mix：riichi.precision, daiminkan.accuracyChange, daiminkan.preserveAlready75, daiminkan.precision, daiminkan.falsePositiveRate, ankan.accuracyChange, shouminkan.accuracyChange, kita.accuracyChange。
- 完整质量 seed42-bilinear-objective：discard.accuracyChange, discard.protectedAccuracyChange, riichi.precision, riichi.falsePositiveRateChange, daiminkan.precision, daiminkan.falsePositiveRate, ankan.precisionChange, shouminkan.precisionChange, pass.accuracyChange, pass.protectedAccuracyChange。
- 完整质量 seed43-head-natural：meanDeficit.improvement, macroAccuracy.improvement, riichi.accuracyChange, daiminkan.precision, abort.accuracyChange。
- 完整质量 seed43-head-mix：meanDeficit.improvement, minimumAccuracy.improvement, macroAccuracy.improvement, riichi.accuracyChange, riichi.precision, pon.accuracyChange, daiminkan.precision, daiminkan.falsePositiveRate, pairedDeficitImprovement.lower95。
- 完整质量 seed43-bilinear-objective：discard.accuracyChange, discard.protectedAccuracyChange, riichi.precision, riichi.falsePositiveRateChange, daiminkan.precision, daiminkan.falsePositiveRate, ankan.precisionChange, shouminkan.precisionChange, pass.accuracyChange, pass.protectedAccuracyChange。

## 下一步最有辨别力的优化方向

**优先将“动作类型选择”和“类型内候选排序”做可独立测量的对照，而不是继续扩大同一稀有动作正例权重。** 目前弃牌即使给定真实类型仍差至少5.5个百分点，大明杠在本批窗口根本没有参数竞争却存在严重误报；这两个瓶颈需要分别获得监督反馈。

最小可区分设计是预先固定一个自然目标基线与一个分解式处理：p(类型|可见状态,合法类型)×q(完整候选|可见状态,类型)，类型分支保留自然机会分布，类型和参数投影分开；两项损失先保持系数1，固定fit、可见特征、合法候选、两seed和预算。这样先判断分解本身是否能同时改善候选排序并稳定类型边界；若同时改权重，就无法区别结构与权重效果。完整推理仍在所有合法候选中一次选出动作，不得读取真实类型。

该方向的首要诊断不是只看稀有动作召回或总体D，而是弃牌多候选条件准确率能否在训练监控与独立holdout一起提高，并最终提高完整弃牌；随后才检查立直/大明杠的完整召回、precision、FPR及过的保护。若分解有效但候选训练侧仍约70%，再用独立固定预算的训练侧学习曲线区分优化不足与表征限制；不重复已有容量probe或碰撞审核，除非出现新证据。

这是下一步研究设计建议，并未启动试验、修改冻结门槛或赋予部署资格。此次holdout已经用于判断，后续超参数选择/早停不能反复使用它；任何新计划须另外冻结分析与评价边界。改架构、head参数量和初始化分布同时变化，因此当前结果不单独证明某一种gate机制就是根因。
