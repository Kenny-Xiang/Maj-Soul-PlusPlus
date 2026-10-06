"""Offline WebKit check of overlay layout, automation controls and click-through behavior."""
import json
from pathlib import Path
import sys
import time

import AppKit
import WebKit
from Foundation import NSDate, NSRunLoop, NSURL
from monitor import ROOT as SOURCE, overlay_update
from terminal_stats import format_turn

ROOT = Path(__file__).resolve().parent
app = AppKit.NSApplication.sharedApplication()
app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
config = WebKit.WKWebViewConfiguration.alloc().init()
config.setWebsiteDataStore_(WebKit.WKWebsiteDataStore.nonPersistentDataStore())
config.userContentController().addUserScript_(
    WebKit.WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
        (SOURCE / 'overlay.js').read_text(), 0, True))
view = WebKit.WKWebView.alloc().initWithFrame_configuration_(AppKit.NSMakeRect(0, 0, 1200, 760), config)
view.loadHTMLString_baseURL_('''<html><body style="margin:0;background:#23405a">
<button id="underlay" style="position:fixed;inset:0;width:100%;height:100%;border:0;
background:radial-gradient(ellipse at center,#456c80,#182e44);color:#adc6d4;font:18px system-ui">
本地浮层预览 · 使用保存的牌局样本，不连接游戏服务器</button>
<div style="position:fixed;top:50%;width:100%;border-top:1px dashed #b3d4dd;pointer-events:none"></div>
</body></html>''', NSURL.URLWithString_('https://game.maj-soul.com/1/'))


def evaluate(source):
    result = []
    view.evaluateJavaScript_completionHandler_(source, lambda value, error: result.append((value, error)))
    deadline = time.time() + 10
    while not result and time.time() < deadline:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.03))
    assert result and not result[0][1], result
    return result[0][0]


def packet(value):
    evaluate('window.__mjStatsOverlay.update(' + json.dumps(value, ensure_ascii=False) + '); null;')


def show_turn(key='preview:5', advice=None):
    evaluate('window.__mjStatsOverlay.expectAdvice(' + json.dumps(key) + '); null;')
    packet({'kind': 'turn', 'text': format_turn(event), 'adviceKey': key,
            'advice': advice or {'status': 'computing', 'message': '正在计算行动建议…'}})


def advisor_state():
    return json.loads(evaluate('''JSON.stringify((()=>{
      const a=document.getElementById('mj-statistics-overlay').shadowRoot.querySelector('.advice');
      const panel=a.closest('.panel'),rect=panel.getBoundingClientRect();
      const game=panel.querySelector('.game').getBoundingClientRect();
      return {hidden:a.hidden,text:a.textContent,best:a.querySelector('.best-tile')?.textContent || '',
        images:a.querySelectorAll('img').length,
        alternatives:[...a.querySelectorAll('.alternatives')].map(element=>element.textContent),
        alternativeActions:[...a.querySelectorAll('.alternative-action')].map(element=>element.textContent),
        alternativeRisks:[...a.querySelectorAll('.alternative-risk')].map(element=>element.textContent),
        progress:a.querySelector('.progress')?.textContent || '',
        chips:[...a.querySelectorAll('.tile-chip')].map(element=>element.textContent),
        metricCount:a.querySelectorAll('.metric-value').length,
        bottom:rect.bottom,fontSize:getComputedStyle(panel).fontSize,
        clickTarget:document.elementFromPoint(game.left+3,game.top+3)?.id};
    })())'''))


recommendation = {
    'status': 'ready', 'model': '公开信息启发式估计', 'elapsedMs': 43,
    'candidates': [
        {'tile': '7z', 'shanten': 2, 'ukeire': 38,
         'improvingTiles': [{'tile': '7p', 'count': 4}, {'tile': '9s', 'count': 3}],
         'winProbability': .268, 'expectedWinPoints': 5200,
         'dealInProbability': .036, 'dealInPoints': 5200, 'expectedDealInLoss': 187,
         'score': 1206, 'reasons': ['保留连续搭子与宝牌', '进张和放铳风险综合估计']},
        {'tile': '6z', 'shanten': 2, 'ukeire': 36, 'score': 1160,
         'dealInProbability': .044, 'expectedWinPoints': 5200},
        {'tile': '1s', 'shanten': 2, 'ukeire': 30, 'score': 1020,
         'dealInProbability': .055, 'expectedWinPoints': 3900},
        {'tile': '3p', 'shanten': 3, 'ukeire': 46, 'score': 970},
    ]
}
recommendation['best'] = recommendation['candidates'][0]


deadline = time.time() + 10
while view.isLoading() and time.time() < deadline:
    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))
# Only the native buttons consume input. The controller can be installed after the overlay.
automation = json.loads(evaluate('''JSON.stringify((()=>{
  const host=document.getElementById('mj-statistics-overlay'),root=host.shadowRoot;
  const toggle=root.querySelector('.automation-toggle'),four=root.querySelector('.automation-four');
  const three=root.querySelector('.automation-three'),status=root.querySelector('.automation-status');
  const east=root.querySelector('.automation-east'),south=root.querySelector('.automation-south');
  const defaults={enabled:toggle.getAttribute('aria-checked'),four:four.getAttribute('aria-pressed'),
    three:three.getAttribute('aria-pressed'),east:east.getAttribute('aria-pressed'),south:south.getAttribute('aria-pressed')};
  toggle.click();south.click();
  const unavailable={enabled:toggle.getAttribute('aria-checked'),east:east.getAttribute('aria-pressed'),
    south:south.getAttribute('aria-pressed'),text:status.textContent};
  let state={enabled:false,playerCount:4,roundCount:1,phase:'idle',message:'待机'},calls=[];
  window.__mjAutoplay={
    setEnabled(enabled){calls.push(['enabled',enabled]);state={...state,enabled,message:enabled?'等待匹配':'已停止'};},
    setPlayerCount(playerCount){calls.push(['players',playerCount]);state={...state,playerCount};},
    setRoundCount(roundCount){calls.push(['rounds',roundCount]);state={...state,roundCount};},
    getStatus(){return state;}
  };
  toggle.click();three.click();south.click();
  const active={enabled:toggle.getAttribute('aria-checked'),three:three.getAttribute('aria-pressed'),
    east:east.getAttribute('aria-pressed'),south:south.getAttribute('aria-pressed')};
  const controls=[toggle,four,three,east,south].map(button=>{
    button.focus();const rect=button.getBoundingClientRect();
    return {tag:button.tagName,tabIndex:button.tabIndex,focused:root.activeElement===button,
      pointerEvents:getComputedStyle(button).pointerEvents,width:rect.width,height:rect.height,
      hit:root.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2)===button};
  });
  const rect=status.getBoundingClientRect();
  const statusTarget=document.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2)?.id;
  window.__mjStatsOverlay.updateAutomation({...state,phase:'paused',message:'<img src="invalid"> 连接中断'});
  const literal={text:status.textContent,images:root.querySelectorAll('img').length};
  four.click();east.click();toggle.click();
  south.blur();
  return {defaults,unavailable,active,controls,statusTarget,literal,calls,
    stopped:toggle.getAttribute('aria-checked')};
})())'''))
assert automation['defaults'] == {'enabled': 'false', 'four': 'true', 'three': 'false', 'east': 'true', 'south': 'false'}, automation
assert automation['unavailable'] == {'enabled': 'false', 'east': 'true', 'south': 'false', 'text': '自动打牌暂不可用'}, automation
assert automation['active'] == {'enabled': 'true', 'three': 'true', 'east': 'false', 'south': 'true'}, automation
assert automation['calls'] == [['enabled', True], ['players', 3], ['rounds', 2], ['players', 4], ['rounds', 1], ['enabled', False]], automation
assert automation['stopped'] == 'false' and automation['statusTarget'] == 'underlay', automation
assert automation['literal'] == {'text': '<img src="invalid"> 连接中断', 'images': 0}, automation
for control in automation['controls']:
    assert control['width'] > 0 and control['height'] > 0, control
    assert {key: value for key, value in control.items() if key not in ('width', 'height')} == {
        'tag': 'BUTTON', 'tabIndex': 0, 'focused': True, 'pointerEvents': 'auto', 'hit': True}, control
assert len(automation['controls']) == 5, automation
assert len({(control['width'], control['height']) for control in automation['controls'][1:]}) == 1, automation
event = json.loads((ROOT / 'fixtures/turn.json').read_text())
# A full four-player river/meld layout exercises the largest normal output.
event['state']['playerCount'] = 4
event['state']['rivers'] = [[{'tile': f'{i % 9 + 1}p'} for i in range(24)] for _ in range(4)]
event['state']['riichi'] = [True, True, False, False]
event['state']['warning'] = '<img src="invalid"> 是文本，不应变成 HTML 元素'
evaluate(overlay_update(event))
show_turn(advice=recommendation)
checks = []
for width, height in [(1200, 760), (800, 600), (600, 400), (1200, 760)]:
    view.setFrameSize_(AppKit.NSMakeSize(width, height))
    info = json.loads(evaluate('''JSON.stringify((()=>{
      dispatchEvent(new Event('resize'));
      const h=document.getElementById('mj-statistics-overlay'),s=h.shadowRoot;
      const p=s.querySelector('.panel'),r=p.getBoundingClientRect();
      const game=s.querySelector('.game'),recording=s.querySelector('.recording');
      const gameRect=game.getBoundingClientRect();
      const modeButtons=['four','three','east','south'].map(mode=>{
        const button=s.querySelector('.automation-'+mode),rect=button.getBoundingClientRect();
        return {width:rect.width,height:rect.height,tabIndex:button.tabIndex,
          visible:rect.left>=r.left&&rect.right<=r.right&&rect.top>=r.top&&rect.bottom<=r.bottom,
          hit:s.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2)===button};
      });
      return {width:innerWidth,height:innerHeight,bottom:r.bottom,top:r.top,
        modeButtons,
        clickTarget:document.elementFromPoint(gameRect.left+3,gameRect.top+3)?.id,images:s.querySelectorAll('img').length,
        containsWarning:s.textContent.includes('<img src="invalid">'),
        rows:s.querySelectorAll('.line').length,
        gameRight:game.getBoundingClientRect().right,recordingLeft:recording.getBoundingClientRect().left,
        recommendation:s.querySelector('.best-tile')?.textContent,
        advisorBottom:s.querySelector('.advice').getBoundingClientRect().bottom,
        fontSize:getComputedStyle(p).fontSize,
        gameText:game.textContent,recordingText:recording.textContent};
    })())'''))
    assert info['bottom'] <= height / 2, info
    assert info['top'] >= 0 and info['rows'] >= 15, info
    assert info['gameRight'] < info['recordingLeft'], info
    assert info['recommendation'] == '打 中' and info['advisorBottom'] <= height / 2, info
    for button in info['modeButtons']:
        assert button['width'] > 0 and button['height'] > 0 and button['tabIndex'] == 0, info
        assert button['visible'] and button['hit'], info
    assert max(button['width'] for button in info['modeButtons']) - min(button['width'] for button in info['modeButtons']) < .01, info
    assert max(button['height'] for button in info['modeButtons']) - min(button['height'] for button in info['modeButtons']) < .01, info
    for label in ['最新动作：', '本机座位：', '剩余牌：', '本人手牌：', '宝牌指示：', '分数：',
                  '座位0 弃牌', '座位1（已立直） 弃牌', '座位3 弃牌', '副露：', '拔北：', '已知牌计数']:
        assert label in info['gameText'] and label not in info['recordingText'], (label, info)
    assert info['gameText'].count('（已立直）') == 1, info
    for label in ['次更新', '动作 #', '状态：', '完整性：', '触发：', '入站', '解析错误']:
        assert label not in info['recordingText'], (label, info)
    assert '说明：' in info['recordingText'] and '说明：' not in info['gameText'], info
    assert info['clickTarget'] == 'underlay' and info['images'] == 0 and info['containsWarning'], info
    del info['gameText'], info['recordingText']
    checks.append(info)
assert float(checks[0]['fontSize'].removesuffix('px')) >= 12, checks[0]
for label in ['后续胡牌率（估计）', '胡牌得点（估计）', '本次放铳率（估计）',
              '本次预期损失（估计）', '放铳输点（估计）']:
    assert label in advisor_state()['text']
assert '攻守评分' not in advisor_state()['text']
assert advisor_state()['chips'] == ['7筒 × 4', '9索 × 3']
assert advisor_state()['metricCount'] == 5
assert advisor_state()['alternativeRisks'] == ['4.4%', '5.5%']
assert '风险估计' in advisor_state()['text']
# Action identity preserves a riichi declaration and dama discard of the same tile.
action_advice = json.loads(json.dumps(recommendation))
riichi = dict(action_advice['best'], action='riichi', actionId='riichi:7z',
              reasons=['立直增加预期打点；与默听比较后综合收益更高', '立直后不能自由改打防守牌'])
dama = dict(action_advice['best'], action='discard', actionId='discard:7z')
action_advice.update(best=riichi, candidates=[riichi, riichi.copy(), dama, dama.copy(),
                                           action_advice['candidates'][1]])
show_turn(advice=action_advice)
info = advisor_state()
assert info['best'] == '立直 · 打 中' and len(info['alternatives']) == 2, info
assert info['alternativeActions'][0] == '打 中', info
assert float(info['fontSize'].removesuffix('px')) >= 12 and info['bottom'] <= 380, info
assert info['clickTarget'] == 'underlay', info
assert '行动建议' in evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.textContent")
action_cases = [
    ({'action': 'chi', 'consumed': ['5m', '3m'], 'calledTile': '4m', 'followupDiscard': '1z'},
     '吃 3万4万5万 · 再打 东'),
    ({'action': 'chi', 'consumed': ['0p', '6p'], 'calledTile': '4p', 'followupDiscard': '9m'},
     '吃 4筒赤5筒6筒 · 再打 9万'),
    ({'action': 'pon', 'consumed': ['5z', '5z'], 'calledTile': '5z', 'followupDiscard': '9m'},
     '碰 白 · 再打 9万'),
    ({'action': 'pon', 'consumed': ['5z', '5z'], 'calledTile': '5z'}, '碰 白'),
    ({'action': 'daiminkan', 'tile': '5z', 'consumed': ['5z'] * 3, 'calledTile': '5z',
      'replacementDraw': True, 'shanten': 1.4}, '大明杠 白'),
    ({'action': 'ankan', 'tile': '5p', 'consumed': ['5p'] * 3 + ['0p'],
      'replacementDraw': True, 'shanten': .4}, '暗杠 5筒'),
    ({'action': 'shouminkan', 'tile': '0p', 'consumed': ['0p'],
      'replacementDraw': True, 'shanten': 1}, '加杠 赤5筒'),
    ({'action': 'kita', 'tile': '4z', 'consumed': ['4z'],
      'replacementDraw': True, 'shanten': 1.6}, '拔北'),
    ({'action': 'pass', 'tile': None, 'reasons': ['不鸣牌，保留门清与立直机会']}, '不鸣牌 / 跳过'),
    ({'action': 'pass', 'tile': None, 'followupDiscard': '4z',
      'reasons': ['跳过杠或拔北，按立直规则随后摸切']}, '跳过 · 随后摸切 北'),
    ({'action': 'abort', 'tile': None, 'reasons': ['继续进攻收益低，建议九种九牌流局']}, '九种九牌流局'),
]
action_checks = []
for fields, expected in action_cases:
    candidate = dict(recommendation['best'], **fields, actionId=fields['action'])
    if fields['action'] in ['chi', 'pon']:
        candidates = [candidate, dict(dama, action='pass', actionId='pass', tile=None)]
    else:
        candidates = [candidate, riichi, dama]
    show_turn(advice=dict(recommendation, best=candidate, candidates=candidates))
    info = advisor_state()
    assert info['best'] == expected and 'undefined' not in info['text'] and '打 —' not in info['text'], info
    assert info['bottom'] <= 380 and float(info['fontSize'].removesuffix('px')) >= 12, info
    assert info['clickTarget'] == 'underlay' and not info['images'], info
    if fields.get('replacementDraw'):
        assert f"补牌后预计 {fields['shanten']} 向听" in info['text'], info
        assert '操作风险（估计）' in info['text'] and '操作预期损失（估计）' in info['text'], info
        assert '补牌后再确定进张' in info['progress'] and not info['chips'], info
        assert '再打' not in info['best'], info
    if fields['action'] in ['chi', 'pon']:
        assert info['alternativeActions'][0] == '不鸣牌 / 跳过', info
        assert info['alternativeRisks'][0] == '—', info
        if fields.get('followupDiscard'):
            assert '后续弃牌风险（估计）' in info['text'], info
            assert '后续弃牌预期损失（估计）' in info['text'], info
    if fields['action'] == 'abort':
        assert '后续胡牌率' not in info['text'], info
        assert not info['progress'] and not info['metricCount'], info
    if fields['action'] == 'pass' and not fields.get('followupDiscard'):
        assert '保留门清与立直机会' in info['text'], info
        assert '预期损失（估计）' not in info['text'] and '放铳输点（估计）' not in info['text'], info
    action_checks.append({'action': fields['action'], 'text': info['best'], 'fontSize': info['fontSize']})
    for width, height in [(800, 600), (600, 400), (1200, 760)]:
        view.setFrameSize_(AppKit.NSMakeSize(width, height))
        evaluate("dispatchEvent(new Event('resize')); null;")
        resized = advisor_state()
        assert resized['best'] == expected and resized['bottom'] <= height / 2, resized
        assert resized['clickTarget'] == 'underlay', resized
waiting_hand = dict(recommendation['best'], action='wait', actionId='wait', tile=None, shanten=1,
                    reasons=['手牌变化已更新，等待摸牌或可执行操作'])
show_turn(advice=dict(recommendation, status='analysis', best=waiting_hand, candidates=[waiting_hand]))
info = advisor_state()
assert info['best'] == '等待下一次行动' and '当前手牌评估' in info['text'], info
assert '1 向听' in info['text'] and '胡牌得点（估计）' in info['text'], info
assert '本次放铳率' not in info['text'] and '本次预期损失' not in info['text'] and '放铳输点' not in info['text'], info
assert not info['alternatives'] and info['bottom'] <= 380, info
show_turn(advice=dict(action_advice, warnings=['暗杠 暂不推荐：操作组合信息缺失']))
info = advisor_state()
assert '仅比较已核实动作 · 暗杠 暂不推荐：操作组合信息缺失' in info['text'], info
assert info['bottom'] <= 380 and float(info['fontSize'].removesuffix('px')) >= 12, info
literal_advice = json.loads(json.dumps(recommendation))
literal_advice['best']['tile'] = '<img src="invalid">'
literal_advice['best']['reasons'] = ['<img src="invalid"> 必须按文本显示']
literal_advice['best']['improvingTiles'] = [{'tile': '<img src="invalid">', 'count': 2}]
show_turn(advice=literal_advice)
assert not advisor_state()['images'] and '<img src="invalid">' in advisor_state()['best']
assert '<img src="invalid">' in advisor_state()['chips'][0]
empty_wait_advice = json.loads(json.dumps(recommendation))
empty_wait_advice['best'].update({'shanten': 0, 'hasValidWait': False})
show_turn(advice=empty_wait_advice)
assert '形0向听·无有效听口' in advisor_state()['text'] and '听牌' not in advisor_state()['text']
# Each wait retains the known tile count and distinguishes legal win routes.
wait_advice = json.loads(json.dumps(recommendation))
wait_advice['best'].update(shanten=0, winningTiles=[
    {'tile': '3s', 'count': 3, 'ronPoints': 3900, 'tsumoPoints': 4000},
    {'tile': '6s', 'count': 0, 'ronPoints': 3900, 'tsumoPoints': 4000},
    {'tile': '1z', 'count': 2, 'ronPoints': 0, 'tsumoPoints': 2000},
    {'tile': '2z', 'count': 1, 'ronPoints': 0, 'tsumoPoints': 0}])
show_turn(advice=wait_advice)
info = advisor_state()
assert '听口' in info['progress'] and len(info['chips']) == 4, info
assert '×0' in info['chips'][1].replace(' ', '') and '张数为未见牌' in info['progress'], info
assert '仅自摸' in info['chips'][2] and '无役' in info['chips'][3], info
# A partial evaluation may expose only its already-ranked candidate prefix.
show_turn(advice=dict(action_advice, rankedCandidateCount=2))
assert not advisor_state()['alternatives'], advisor_state()
show_turn(advice=dict(action_advice, rankedCandidateCount=3))
assert len(advisor_state()['alternatives']) == 1, advisor_state()
# Concrete constraints remain visible even when preceded by generic explanation.
constraint = dict(recommendation['best'], furiten=True, reasons=[
    '当前进攻：与弃和路线按同一终局净收益比较；新窗口重新评估',
    '听牌；有效未见牌 4 张', '整副牌振听，所有等待均只估自摸',
    '当前等待无役，不能仅凭宝牌和牌'])
show_turn(advice=dict(recommendation, best=constraint, candidates=[constraint]))
for width, height in [(1200, 760), (800, 600), (600, 400)]:
    view.setFrameSize_(AppKit.NSMakeSize(width, height))
    evaluate("dispatchEvent(new Event('resize')); null;")
    info = json.loads(evaluate('''JSON.stringify((()=>{
      const s=document.getElementById('mj-statistics-overlay').shadowRoot;
      const warnings=[...s.querySelectorAll('.advice .advice-warning')];
      return warnings.map(e=>({text:e.textContent,display:getComputedStyle(e).display,
        bottom:e.getBoundingClientRect().bottom,height:e.getBoundingClientRect().height}));
    })())'''))
    assert len(info) == 2 and all(w['display'] != 'none' and w['height'] > 0 and w['bottom'] <= height / 2 for w in info), info
    assert '振听' in info[0]['text'] and '无役' in info[1]['text'], info
view.setFrameSize_(AppKit.NSMakeSize(1200, 760))
# Dense waits and multiple constraints must remain fully visible at every size.
thirteen_waits = dict(recommendation['best'], shanten=0, furiten=True, winningTiles=[
    {'tile': tile, 'count': 3, 'ronPoints': 0, 'tsumoPoints': 32000}
    for tile in '1m 9m 1p 9p 1s 9s 1z 2z 3z 4z 5z 6z 7z'.split()], reasons=[
        '整副牌振听，所有等待均只估自摸', '立直后不能自由改打防守牌'])
show_turn(advice=dict(recommendation, best=thirteen_waits,
                     candidates=[thirteen_waits, riichi, dama],
                     warnings=['暗杠 暂不推荐：操作组合信息缺失']))
for width, height in [(1200, 760), (800, 600), (600, 400)]:
    view.setFrameSize_(AppKit.NSMakeSize(width, height))
    evaluate("dispatchEvent(new Event('resize')); null;")
    info = json.loads(evaluate('''JSON.stringify((()=>{
      const s=document.getElementById('mj-statistics-overlay').shadowRoot;
      const p=s.querySelector('.panel').getBoundingClientRect();
      const selectors=['.tile-chip','.comparison-head > div','.alternatives > div','.advice .advice-warning'];
      const elements=selectors.flatMap(selector=>[...s.querySelectorAll(selector)].map(e=>{
        const r=e.getBoundingClientRect(),style=getComputedStyle(e);
        return {selector,text:e.textContent,left:r.left,right:r.right,top:r.top,bottom:r.bottom,
          height:r.height,display:style.display,visibility:style.visibility};
      }));
      return {left:p.left,right:p.right,bottom:p.bottom,
        chips:s.querySelectorAll('.tile-chip').length,
        alternatives:s.querySelectorAll('.alternatives').length,elements};
    })())'''))
    assert info['chips'] == 13 and info['alternatives'] == 2, info
    assert len(info['elements']) == 28, info  # 13 waits, 12 table cells, three warnings.
    assert info['bottom'] <= height / 2, info
    for element in info['elements']:
        assert element['display'] != 'none' and element['visibility'] == 'visible' and element['height'] > 0, element
        assert element['left'] >= info['left'] and element['right'] <= info['right'], element
        assert element['top'] >= 0 and element['bottom'] <= height / 2, element
view.setFrameSize_(AppKit.NSMakeSize(1200, 760))
fourth_riichi = dict(riichi, abortAfterRiichi=True, reasons=[
    '当前已立直：按合法强制续打评估', '听牌；有效未见牌 4 张',
    '有对手立直，已计入较高放铳风险',
    '立直后不能自由弃和，和牌与强制摸切放铳共用存活概率',
    '第四家立直：宣言牌未被荣和则途中流局，无后续和牌机会或听牌料'])
show_turn(advice=dict(recommendation, best=fourth_riichi, candidates=[fourth_riichi]))
assert '第四家立直：宣言牌未被荣和则途中流局' in advisor_state()['text']
assert '共用存活概率' not in advisor_state()['text']
assert not advisor_state()['progress'] and not advisor_state()['chips']
# Normal recording diagnostics disappear, but incompleteness stays prominent.
incomplete = json.loads(json.dumps(event))
incomplete['state'].update(handComplete=False, historyComplete=False)
evaluate("window.__mjStatsOverlay.expectAdvice('incomplete'); null;")
packet({'kind': 'turn', 'adviceKey': 'incomplete', 'text': format_turn(incomplete),
        'advice': {'status': 'unavailable', 'message': '缺少完整手牌，暂停推荐'}})
assert '缺少完整手牌，暂停推荐' in advisor_state()['text']
assert '历史不完整或待核对' in evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelector('.details .advice-warning').textContent")
# A newer turn immediately removes the previous result, including delayed worker replies.
show_turn(key='preview:6')
assert not advisor_state()['best'] and '正在计算' in advisor_state()['text']
assert not advisor_state()['progress'] and not advisor_state()['metricCount']
packet({'kind': 'advice', 'adviceKey': 'preview:5', 'advice': recommendation})
assert not advisor_state()['best']
packet({'kind': 'advice', 'adviceKey': 'preview:6', 'advice': recommendation})
assert advisor_state()['best'] == '打 中'
# Browser invalidation precedes the native update; late replies must stay cleared.
evaluate('window.__mjStatsOverlay.invalidateAdvice(); null;')
packet({'kind': 'advice', 'adviceKey': 'preview:6', 'advice': recommendation})
assert advisor_state()['hidden'] and not advisor_state()['best']
assert not advisor_state()['progress'] and not advisor_state()['metricCount']
# A delayed native turn packet must not re-arm advice after the user has acted.
packet({'kind': 'turn', 'adviceKey': 'preview:6', 'text': format_turn(event), 'advice': recommendation})
packet({'kind': 'advice', 'adviceKey': 'preview:6', 'advice': recommendation})
assert advisor_state()['hidden'] and not advisor_state()['best']
# The browser announces the next snapshot before native callbacks can arrive.
evaluate("window.__mjStatsOverlay.expectAdvice('preview:7'); null;")
packet({'kind': 'turn', 'adviceKey': 'preview:6', 'text': format_turn(event), 'advice': recommendation})
assert advisor_state()['hidden'] and not advisor_state()['best']
# An earlier native status clears the display without losing that newer expectation.
packet({'kind': 'status', 'phase': 'playing', 'text': '已排队的牌局状态'})
packet({'kind': 'turn', 'adviceKey': 'preview:7', 'text': format_turn(event),
        'advice': {'status': 'computing', 'message': '正在计算行动建议…'}})
assert not advisor_state()['hidden'] and '正在计算' in advisor_state()['text']
packet({'kind': 'advice', 'adviceKey': 'preview:6', 'advice': recommendation})
assert not advisor_state()['best']
packet({'kind': 'advice', 'adviceKey': 'preview:7', 'advice': recommendation})
assert advisor_state()['best'] == '打 中'
show_turn(advice=recommendation)
game_text = evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelector('.game').textContent")
for status in [{'kind': 'status', 'phase': 'disconnected'},
               {'kind': 'error', 'message': '解析失败：测试消息'}]:
    evaluate(overlay_update(status))
    assert advisor_state()['hidden'] and not advisor_state()['best']
    assert not advisor_state()['progress'] and not advisor_state()['metricCount']
    packet({'kind': 'advice', 'adviceKey': 'preview:5', 'advice': recommendation})
    assert advisor_state()['hidden']
    assert evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelector('.game').textContent") == game_text
    text = evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelector('.recording .caption').textContent")
    assert '连接中断' in text if status['kind'] == 'status' else '解析失败' in text
    show_turn(advice=recommendation)
evaluate(overlay_update({'kind': 'status', 'phase': 'between_rounds'}))
assert advisor_state()['hidden']
assert evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelector('.caption').textContent").startswith('小局结束')
assert evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelectorAll('.line').length") >= 15
evaluate(overlay_update({'kind': 'status', 'phase': 'ended', 'reset': True}))
assert evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelectorAll('.line').length") == 0
assert '统计已重置' in evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelector('.caption').textContent")
assert advisor_state()['hidden']
evaluate(overlay_update({'kind': 'status', 'phase': 'playing'}))
assert evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelectorAll('.line').length") == 0
for phase in ['waiting', 'connected']:
    show_turn(advice=recommendation)
    evaluate(overlay_update({'kind': 'status', 'phase': phase}))
    assert advisor_state()['hidden']
for status in ['waiting', 'unavailable', 'win', 'computing']:
    show_turn(advice=recommendation)
    packet({'kind': 'advice', 'adviceKey': 'preview:5',
            'advice': {'status': status, 'message': '状态说明 <img src="invalid">'}})
    info = advisor_state()
    assert not info['best'] and not info['images'] and '<img src="invalid">' in info['text'], info
    assert not info['progress'] and not info['metricCount'], info
assert overlay_update({'kind': 'heartbeat'}) is None
print(json.dumps({'overlay_checks': checks, 'round_transition': 'passed',
                  'action_checks': action_checks,
                  'advice_versions': 'passed', 'advice_clearing': 'passed', 'heartbeat': 'silent'}, ensure_ascii=False), flush=True)

if '--snapshot' in sys.argv:
    from advisor import advise
    event = json.loads((ROOT / 'fixtures/turn.json').read_text())
    # Real saved opening hand, with the discard operation available at the deal.
    event['state'].update({'canDiscard': True, 'operations': [1], 'riichi': [False] * 4,
                           'forbiddenDiscards': [], 'riichiSticks': 0, 'furiten': False})
    event['state']['warning'] = '保存的开局手牌 · 建议由本地分析引擎现场计算。'
    actual_advice = advise(event['state'])
    assert actual_advice['status'] == 'ready', actual_advice
    action_state = json.loads(json.dumps(event['state']))
    action_state.update({
        'hand': '1m 2m 3m 1p 2p 3p 1s 2s 3s 4s 5s 7z 7z 1z'.split(),
        'playerCount': 4, 'scores': [25000] * 4, 'round': {'chang': 0, 'ju': 0, 'ben': 0},
        'left': 48, 'lastDraw': '1z', 'doras': [], 'canAct': True, 'canDoubleRiichi': False,
        'operations': [1, 7], 'operationDetails': [{'type': 1, 'combination': []},
                                                 {'type': 7, 'combination': ['1z']}],
        'warning': '离线听牌样本 · 立直与默听由本地分析引擎现场比较。',
    })
    actual_action_advice = advise(action_state)
    assert actual_action_advice['status'] == 'ready' and actual_action_advice['best']['action'] == 'riichi', actual_action_advice
    show_turn(advice=actual_advice)
    style = AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable | AppKit.NSWindowStyleMaskResizable
    window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        AppKit.NSMakeRect(0, 0, 1200, 760), style, AppKit.NSBackingStoreBuffered, False)
    window.setReleasedWhenClosed_(False)
    window.setTitle_('统计浮层预览（本地样本）')
    window.setContentView_(view)
    window.center()
    window.orderBack_(None)
    for filename, snapshot_state, advice, size in [
            ('overlay-preview.png', event['state'], actual_advice, (1200, 760)),
            ('action-advice-preview.png', action_state, actual_action_advice, (1200, 760)),
            ('overlay-preview-800.png', event['state'], actual_advice, (800, 600))]:
        window.setContentSize_(AppKit.NSMakeSize(*size))
        event['state'] = snapshot_state
        show_turn(advice=advice)
        snapshots = []
        view.takeSnapshotWithConfiguration_completionHandler_(None, lambda image, error: snapshots.append((image, error)))
        deadline = time.time() + 10
        while not snapshots and time.time() < deadline:
            NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))
        assert snapshots and not snapshots[0][1], snapshots
        bitmap = AppKit.NSBitmapImageRep.imageRepWithData_(snapshots[0][0].TIFFRepresentation())
        output = ROOT.parent / 'build' / filename
        output.parent.mkdir(exist_ok=True)
        assert bitmap.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {}).writeToFile_atomically_(
            str(output), True)
    window.close()
