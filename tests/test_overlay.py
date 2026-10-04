"""Offline WebKit check of overlay layout, literal text and click-through behavior."""
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
    packet({'kind': 'turn', 'text': format_turn(event), 'adviceKey': key,
            'advice': advice or {'status': 'computing', 'message': '正在计算出牌建议…'}})


def advisor_state():
    return json.loads(evaluate('''JSON.stringify((()=>{
      const a=document.getElementById('mj-statistics-overlay').shadowRoot.querySelector('.advice');
      return {hidden:a.hidden,text:a.textContent,best:a.querySelector('.best-tile')?.textContent || '',
        images:a.querySelectorAll('img').length};
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
      return {width:innerWidth,height:innerHeight,bottom:r.bottom,top:r.top,
        clickTarget:document.elementFromPoint(30,40)?.id,images:s.querySelectorAll('img').length,
        containsWarning:s.textContent.includes('<img src="invalid">'),
        rows:s.querySelectorAll('.line').length,
        gameRight:game.getBoundingClientRect().right,recordingLeft:recording.getBoundingClientRect().left,
        recommendation:s.querySelector('.best-tile')?.textContent,
        advisorBottom:s.querySelector('.advice').getBoundingClientRect().bottom,
        fontSize:getComputedStyle(p).fontSize,
        gameText:game.textContent,recordingText:recording.textContent};
    })())'''))
    assert info['bottom'] <= height / 2, info
    assert info['top'] >= 0 and info['rows'] >= 16, info
    assert info['gameRight'] < info['recordingLeft'], info
    assert info['recommendation'] == '打 中' and info['advisorBottom'] <= height / 2, info
    for label in ['最新动作：', '本机座位：', '剩余牌：', '本人手牌：', '宝牌指示：', '分数：',
                  '座位0 弃牌', '座位1（已立直） 弃牌', '座位3 弃牌', '副露：', '拔北：', '已知牌计数']:
        assert label in info['gameText'] and label not in info['recordingText'], (label, info)
    assert info['gameText'].count('（已立直）') == 1, info
    for label in ['次更新', '动作 #', '状态：', '完整性：', '说明：', '触发：', '入站', '解析错误']:
        assert label in info['recordingText'] and label not in info['gameText'], (label, info)
    assert info['clickTarget'] == 'underlay' and info['images'] == 0 and info['containsWarning'], info
    del info['gameText'], info['recordingText']
    checks.append(info)
assert float(checks[0]['fontSize'].removesuffix('px')) >= 12, checks[0]
assert '后续胡牌率（估计）' in advisor_state()['text']
assert '本次放铳率（估计）' in advisor_state()['text']
assert '本次预期损失（估计）' in advisor_state()['text']
assert '放铳输点（估计）' in advisor_state()['text']
assert '未校准' in advisor_state()['text'] and '风险 4.4%' in advisor_state()['text']
literal_advice = json.loads(json.dumps(recommendation))
literal_advice['best']['tile'] = '<img src="invalid">'
literal_advice['best']['reasons'] = ['<img src="invalid"> 必须按文本显示']
show_turn(advice=literal_advice)
assert not advisor_state()['images'] and '<img src="invalid">' in advisor_state()['best']
empty_wait_advice = json.loads(json.dumps(recommendation))
empty_wait_advice['best'].update({'shanten': 0, 'hasValidWait': False})
show_turn(advice=empty_wait_advice)
assert '形0向听·无有效听口' in advisor_state()['text'] and '听牌' not in advisor_state()['text']
# A newer turn immediately removes the previous result, including delayed worker replies.
show_turn(key='preview:6')
assert not advisor_state()['best'] and '正在计算' in advisor_state()['text']
packet({'kind': 'advice', 'adviceKey': 'preview:5', 'advice': recommendation})
assert not advisor_state()['best']
packet({'kind': 'advice', 'adviceKey': 'preview:6', 'advice': recommendation})
assert advisor_state()['best'] == '打 中'
# Browser invalidation precedes the native update; late replies must stay cleared.
evaluate('window.__mjStatsOverlay.invalidateAdvice(); null;')
packet({'kind': 'advice', 'adviceKey': 'preview:6', 'advice': recommendation})
assert advisor_state()['hidden'] and not advisor_state()['best']
show_turn(advice=recommendation)
game_text = evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelector('.game').textContent")
for status in [{'kind': 'status', 'phase': 'disconnected'},
               {'kind': 'error', 'message': '解析失败：测试消息'}]:
    evaluate(overlay_update(status))
    assert advisor_state()['hidden'] and not advisor_state()['best']
    packet({'kind': 'advice', 'adviceKey': 'preview:5', 'advice': recommendation})
    assert advisor_state()['hidden']
    assert evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelector('.game').textContent") == game_text
    text = evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelector('.recording .caption').textContent")
    assert '连接中断' in text if status['kind'] == 'status' else '解析失败' in text
    show_turn(advice=recommendation)
evaluate(overlay_update({'kind': 'status', 'phase': 'between_rounds'}))
assert advisor_state()['hidden']
assert evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelector('.caption').textContent").startswith('小局结束')
assert evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelectorAll('.line').length") >= 16
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
assert overlay_update({'kind': 'heartbeat'}) is None
print(json.dumps({'overlay_checks': checks, 'round_transition': 'passed',
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
    show_turn(advice=actual_advice)
    style = AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable | AppKit.NSWindowStyleMaskResizable
    window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        AppKit.NSMakeRect(0, 0, 1200, 760), style, AppKit.NSBackingStoreBuffered, False)
    window.setReleasedWhenClosed_(False)
    window.setTitle_('统计浮层预览（本地样本）')
    window.setContentView_(view)
    window.center()
    window.orderBack_(None)
    snapshots = []
    view.takeSnapshotWithConfiguration_completionHandler_(None, lambda image, error: snapshots.append((image, error)))
    deadline = time.time() + 10
    while not snapshots and time.time() < deadline:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))
    assert snapshots and not snapshots[0][1], snapshots
    bitmap = AppKit.NSBitmapImageRep.imageRepWithData_(snapshots[0][0].TIFFRepresentation())
    output = ROOT.parent / 'build/overlay-preview.png'
    output.parent.mkdir(exist_ok=True)
    assert bitmap.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {}).writeToFile_atomically_(
        str(output), True)
    window.close()
