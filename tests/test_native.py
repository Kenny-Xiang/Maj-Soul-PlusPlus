import sys,json,time
from pathlib import Path
from monitor import ROOT as SOURCE, collector_source, overlay_update
from terminal_stats import format_turn
import AppKit,WebKit
from Foundation import NSObject,NSURL,NSRunLoop,NSDate
root=Path(__file__).resolve().parent
frames=json.loads((root/'fixtures/recording/capture.json').read_text())
packets=[]
class Handler(NSObject):
 def userContentController_didReceiveScriptMessage_(self,controller,message):
  packets.append(json.loads(str(message.body())))
  update=overlay_update(packets[-1])
  if update: message.webView().evaluateJavaScript_completionHandler_(update,None)
handler=Handler.alloc().init()
app=AppKit.NSApplication.sharedApplication()
config=WebKit.WKWebViewConfiguration.alloc().init()
config.setWebsiteDataStore_(WebKit.WKWebsiteDataStore.nonPersistentDataStore())
c=config.userContentController()
c.addScriptMessageHandler_name_(handler,'mjStatistics')
setup='''window.WebSocket=class extends EventTarget {constructor(url){super();this.url=url;this.readyState=1;}send(){}};'''
for source in [(SOURCE/'overlay.js').read_text(),setup,collector_source()]:
 c.addUserScript_(WebKit.WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(source,0,True))
view=WebKit.WKWebView.alloc().initWithFrame_configuration_(AppKit.NSMakeRect(0,0,300,200),config)
replay='''const s=new WebSocket('wss://sample.maj-soul.com/game-gateway-zone');
for(const hex of FRAMES){s.dispatchEvent(new MessageEvent('message',{data:Uint8Array.from(hex.match(/../g),x=>parseInt(x,16)).buffer}));}
setTimeout(()=>window.webkit.messageHandlers.mjStatistics.postMessage(JSON.stringify({kind:'test-finish',snapshot:window.__mjMonitor?.getSnapshot(),href:location.href})),100);'''.replace('FRAMES',json.dumps([f['hex'] for f in frames]))
view.loadHTMLString_baseURL_('<html><body>Local fixture test<script>'+replay+'</script></body></html>',NSURL.URLWithString_('https://game.maj-soul.com/1/'))
deadline=time.time()+20
while time.time()<deadline and not any(p.get('kind')=='test-finish' for p in packets):
 NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))
finish=next((p for p in packets if p.get('kind')=='test-finish'),None)
turns=[p for p in packets if p.get('kind')=='turn']
assert finish,packets
assert [p['step'] for p in turns]==list(range(63,111)),finish
assert finish['snapshot']['errors']==0,finish
assert finish['snapshot']['received']==60,finish
for p in turns: assert f"动作 #{p['step']}" in format_turn(p)
display=[]
view.evaluateJavaScript_completionHandler_("document.getElementById('mj-statistics-overlay').shadowRoot.querySelector('.panel').textContent",lambda value,error:display.append((value,error)))
deadline=time.time()+10
while not display and time.time()<deadline:
 NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))
assert display and not display[0][1] and '第 48 次更新' in display[0][0] and '动作 #110' in display[0][0],display
assert '第 1 次更新' not in display[0][0],display
print(json.dumps({'test':'real WKWebView → WKScriptMessageHandler → Python formatter → overlay','frames':60,'actions':48,'statistics_updates':len(turns),'errors':0,'overlay_shows_latest_update':True,'network_requests':'none; local fixture and fake WebSocket','base_url':finish['href']},ensure_ascii=False))
