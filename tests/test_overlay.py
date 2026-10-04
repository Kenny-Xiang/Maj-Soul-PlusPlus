"""Offline WebKit check of overlay layout, literal text and click-through behavior."""
import json
from pathlib import Path
import sys
import time

import AppKit
import WebKit
from Foundation import NSDate, NSRunLoop, NSURL
from monitor import ROOT as SOURCE, overlay_update

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
        gameText:game.textContent,recordingText:recording.textContent};
    })())'''))
    assert info['bottom'] <= height / 2, info
    assert info['top'] >= 0 and info['rows'] >= 16, info
    assert info['gameRight'] < info['recordingLeft'], info
    for label in ['最新动作：', '本机座位：', '剩余牌：', '本人手牌：', '宝牌指示：', '分数：',
                  '座位0 弃牌', '座位1（已立直） 弃牌', '座位3 弃牌', '副露：', '拔北：', '已知牌计数']:
        assert label in info['gameText'] and label not in info['recordingText'], (label, info)
    assert info['gameText'].count('（已立直）') == 1, info
    for label in ['次更新', '动作 #', '状态：', '完整性：', '说明：', '触发：', '入站', '解析错误']:
        assert label in info['recordingText'] and label not in info['gameText'], (label, info)
    assert info['clickTarget'] == 'underlay' and info['images'] == 0 and info['containsWarning'], info
    del info['gameText'], info['recordingText']
    checks.append(info)
game_text = evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelector('.game').textContent")
for status in [{'kind': 'status', 'phase': 'disconnected'},
               {'kind': 'error', 'message': '解析失败：测试消息'}]:
    evaluate(overlay_update(status))
    assert evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelector('.game').textContent") == game_text
    text = evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelector('.recording .caption').textContent")
    assert '连接中断' in text if status['kind'] == 'status' else '解析失败' in text
evaluate(overlay_update({'kind': 'status', 'phase': 'between_rounds'}))
assert evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelector('.caption').textContent").startswith('小局结束')
assert evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelectorAll('.line').length") >= 16
evaluate(overlay_update({'kind': 'status', 'phase': 'ended', 'reset': True}))
assert evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelectorAll('.line').length") == 0
assert '统计已重置' in evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelector('.caption').textContent")
evaluate(overlay_update({'kind': 'status', 'phase': 'playing'}))
assert evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelectorAll('.line').length") == 0
assert overlay_update({'kind': 'heartbeat'}) is None
print(json.dumps({'overlay_checks': checks, 'round_transition': 'passed', 'heartbeat': 'silent'}, ensure_ascii=False), flush=True)

if '--snapshot' in sys.argv:
    event['state']['warning'] = '本地预览样本；实际游戏中在发牌及每个场上动作后更新。'
    evaluate(overlay_update(event))
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
