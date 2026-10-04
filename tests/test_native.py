import sys,json,time
from pathlib import Path
from monitor import ROOT as SOURCE, collector_source, overlay_update
from terminal_stats import format_turn
from advice_worker import AdviceWorker
import AppKit,WebKit
from Foundation import NSObject,NSURL,NSRunLoop,NSDate
root=Path(__file__).resolve().parent
frames=json.loads((root/'fixtures/recording/capture.json').read_text())
packets=[]
advisor=AdviceWorker()
class Handler(NSObject):
 def userContentController_didReceiveScriptMessage_(self,controller,message):
  packets.append(json.loads(str(message.body())))
  event=packets[-1]
  if event.get('kind')=='turn': advisor.submit(f"{event['session']}:{event['serial']}",event['state'])
  elif event.get('kind') in ('status','error'): advisor.invalidate()
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

# A complete recorded starting hand exercises the live advisor path as well.
def varint(value):
 out=[]
 while value>127:
  out.append((value&127)|128);value>>=7
 return bytes(out+[value])
def num(field,value): return varint(field*8)+varint(value)
def blob(field,value): return varint(field*8+2)+varint(len(value))+value
def string(field,value): return blob(field,value.encode())
def action_frame(name,step,payload):
 keys=[132,94,78,66,57,162,31,96,28]
 transformed=bytes(b^(((23^len(payload))+5*i+keys[i%9])&255) for i,b in enumerate(payload))
 action=num(1,step)+string(2,name)+blob(3,transformed)
 return bytes([1])+string(1,'.lq.ActionPrototype')+blob(2,action)
def evaluate(script):
 results=[]
 view.evaluateJavaScript_completionHandler_(script,lambda value,error:results.append((value,error)))
 deadline=time.time()+10
 while not results and time.time()<deadline:
  NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(.02))
 assert results and not results[0][1],results
 return results[0][0]
def feed(frame):
 evaluate('s.dispatchEvent(new MessageEvent("message",{data:Uint8Array.from('+json.dumps(list(frame))+').buffer}));null;')

baseline=json.loads((root/'fixtures/turn.json').read_text())['state']
payload=(num(1,0)+num(2,0)+num(3,5)+b''.join(string(4,t) for t in baseline['hand'])+
         b''.join(num(6,s) for s in baseline['scores'])+blob(7,num(1,0)+blob(2,num(1,1)))+
         num(13,54)+string(14,'8p'))
feed(action_frame('ActionNewRound',0,payload))
deadline=time.time()+10
ready=None
while time.time()<deadline:
 NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(.02))
 result=advisor.take_result()
 if result:
  evaluate(overlay_update(result))
  if result['advice']['status']=='ready': ready=result;break
assert ready,packets[-3:]
assert ready['advice']['best']['tile'] in baseline['hand'],ready
assert evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelector('.advice').dataset.status")=='ready'
feed(action_frame('ActionDiscardTile',1,num(1,0)+string(2,ready['advice']['best']['tile'])))
evaluate(overlay_update(ready))
assert evaluate("document.getElementById('mj-statistics-overlay').shadowRoot.querySelector('.best-tile')===null")
advisor.close()
print(json.dumps({'test':'complete hand → native bridge → background advisor → keyed overlay',
                  'recommended':ready['advice']['best']['tile'],'elapsed_ms':ready['advice'].get('elapsedMs'),
                  'old_advice_rejected_after_discard':True},ensure_ascii=False))
