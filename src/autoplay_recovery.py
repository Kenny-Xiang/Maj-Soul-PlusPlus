"""In-process, one-shot autoplay recovery. No persisted intent or login secrets."""
import json
import secrets
import time


class AutoplayRecovery:
    # Give the official client time to reconnect; budget is per explicit activation.
    DELAYS = (45, 90, 180)
    RESPONSE_TIMEOUT = 10
    LOAD_TIMEOUT = 60
    EPISODE_TIMEOUT = 180

    def __init__(self, write, activity, clock=time.monotonic):
        self.write, self.activity, self.clock = write, activity, clock
        self.session = None
        self.revision = -1
        self.enabled = False
        self.retired = set()
        self.attempts = 0
        self.stalled_since = self.episode_since = self.progress = None
        self.ticket = self.navigation = self.pending = self.suspended = None
        self.last_poll = float('-inf')

    def _cancel(self):
        self.pending = self.ticket = self.navigation = self.suspended = None
        self.stalled_since = self.episode_since = self.progress = None

    def close(self):
        self._cancel()
        self.enabled = False
        self.activity(False)

    def on_intent(self, event):
        session, revision = event.get('session'), event.get('revision')
        enabled, source = event.get('enabled'), event.get('source')
        if (not isinstance(session, str) or not session or type(revision) is not int or revision < 0 or
                type(enabled) is not bool or source not in ('init', 'user', 'pause', 'restore')):
            return
        # An off event queued just before reload still revokes its one-shot credential.
        if (self.ticket and self.ticket['stage'] in ('loading', 'restoring') and
                session == self.ticket['session'] and source in ('user', 'pause') and
                revision > self.ticket['revision']):
            self.close()
            return
        if session in self.retired:
            return
        if source == 'init':
            if session == self.session or revision != 0 or enabled:
                return
            if self.session:
                self.retired.add(self.session)
            self.session, self.revision = session, 0
            if self.ticket and self.ticket['stage'] == 'loading':
                return  # Initialization off is not a user-off decision.
            self.close()
            return
        if session != self.session or revision <= self.revision:
            return
        if source == 'restore':
            if not self.ticket or self.ticket['stage'] != 'restoring':
                return
            self.revision = revision
            return  # Completion must also prove that this exact restore succeeded.
        was_enabled = self.enabled or self.suspended is not None
        self.revision = revision
        self.close()
        self.enabled = enabled
        if enabled and not was_enabled and source == 'user':
            self.attempts = 0
        self.activity(enabled)

    def navigation_started(self, navigation):
        if self.ticket and navigation == self.navigation:
            return True
        previous = (navigation, self.session, self.revision) if self.enabled or self.suspended else None
        self.close()
        self.suspended = previous
        return False

    def page_committed(self, navigation):
        if self.ticket and navigation == self.navigation:
            self.ticket['committed'] = True
            return True
        self.close()
        return False

    def navigation_failed(self, view, navigation):
        if self.ticket and navigation == self.navigation:
            self._fail(view, '恢复页面加载失败，请检查网络或重新登录后开启自动打牌')
            return True
        if self.suspended and self.suspended[0] == navigation:
            _, session, revision = self.suspended

            def resumed(value):
                self.suspended = None
                if (isinstance(value, dict) and value.get('session') == session == self.session and
                        value.get('revision') == revision == self.revision and
                        value.get('enabled') is True and not value.get('fault')):
                    self.enabled = True
                    self.activity(True)
                    self.write('[自动恢复] 导航已取消，按原页面当前意图继续监督')

            self._evaluate(view, 'window.__mjRecovery?.snapshot();', resumed)
            return True
        return False

    def _evaluate(self, view, expression, callback):
        request = self.pending = object()
        self.request_at = self.clock()

        def completed(value, error):
            if self.pending is not request:
                return
            self.pending = None
            if error is not None:
                self._fail(view, '页面恢复检查失败，请检查游戏窗口')
            else:
                try:
                    decoded = json.loads(value) if isinstance(value, str) else None
                except (ValueError, TypeError):
                    decoded = None
                callback(decoded)

        try:
            # WebKit dictionaries are Objective-C proxies; transport plain JSON strings.
            script = 'JSON.stringify((' + expression.rstrip(';') + ') ?? null);'
            view.evaluateJavaScript_completionHandler_(script, completed)
        except Exception as error:
            completed(None, error)

    def _fail(self, view, reason):
        session, revision = self.session, self.revision
        self.close()
        self.write('[自动恢复] ' + reason)
        # The page checks its current revision and existing fatal state again.
        args = json.dumps([session, revision, reason], ensure_ascii=False)[1:-1]
        try:
            view.evaluateJavaScript_completionHandler_(f'window.__mjRecovery?.fail({args});', None)
        except Exception:
            self.write('[自动恢复] 页面不可用，暂停原因未送达；恢复凭据已撤销')

    def tick(self, view):
        now = self.clock()
        if self.pending is not None:
            if now - self.request_at >= self.RESPONSE_TIMEOUT:
                self._fail(view, '页面未回应恢复检查；未重载或重发操作，请检查游戏窗口')
            return
        if not self.enabled:
            return
        if self.ticket and self.ticket['stage'] == 'loading':
            if now - self.ticket['at'] >= self.LOAD_TIMEOUT:
                self._fail(view, '恢复页面加载超过 60 秒，请检查网络或登录状态')
                return
            if not self.ticket['committed']:
                return
        if now - self.last_poll < 1:
            return
        self.last_poll = now
        callback = self._replacement if self.ticket else self._snapshot
        self._evaluate(view, 'window.__mjRecovery?.snapshot();', lambda value: callback(view, value))

    def _snapshot(self, view, value):
        if not isinstance(value, dict) or value.get('session') != self.session:
            self._fail(view, '无法验证当前页面的恢复状态，请检查游戏窗口')
            return
        if value.get('fault') or value.get('enabled') is False:
            self.close()  # Keep the page's original error/off reason.
            return
        if value.get('revision') != self.revision or value.get('enabled') is not True:
            return
        now = self.clock()
        if value.get('stalled') is not True:
            if self.stalled_since is not None:
                self.write('[自动恢复] 官方连接已恢复有效进展，继续检查权威牌局')
            self.stalled_since = self.episode_since = None
            self.progress = value.get('progress')
            return
        progress = value.get('progress')
        if self.episode_since is None:
            self.episode_since = now
        if self.stalled_since is None or progress != self.progress:
            self.stalled_since, self.progress = now, progress
            self.write(f"[自动恢复] 等待官方恢复，阶段={value.get('phase')}，有效进展={progress}，已重载={self.attempts}")
        delay = self.DELAYS[min(self.attempts, len(self.DELAYS) - 1)]
        if now - self.stalled_since < delay and now - self.episode_since < self.EPISODE_TIMEOUT:
            return
        if self.attempts >= len(self.DELAYS):
            self._fail(view, '自动恢复已尝试 3 次且仍无进展，请检查网络或重新登录后开启')
            return
        self.ticket = {'session': self.session, 'revision': self.revision,
                       'nonce': secrets.token_hex(16), 'stage': 'preparing'}
        args = json.dumps([self.session, self.revision, self.ticket['nonce']])[1:-1]
        self._evaluate(view, f'window.__mjRecovery?.prepare({args});', lambda value: self._prepared(view, value))

    def _prepared(self, view, value):
        ticket = self.ticket
        if not ticket or not self.enabled:
            return
        if (not isinstance(value, dict) or value.get('session') != self.session or
                value.get('revision') != self.revision or value.get('enabled') is not True or
                value.get('nonce') != ticket['nonce'] or value.get('stalled') is not True or
                value.get('fault') or not isinstance(value.get('checkpoint'), dict)):
            self._fail(view, '未能冻结并验证恢复前的操作状态，已停止主动恢复')
            return
        ticket.update(checkpoint=value['checkpoint'], stage='loading', at=self.clock(), committed=False)
        self.attempts += 1
        self.write(f'[自动恢复] 第 {self.attempts}/3 次受控重载；已冻结旧页面操作')
        try:
            self.navigation = view.reload()
            if self.navigation is None:
                raise RuntimeError('reload did not return navigation')
        except Exception:
            self._fail(view, '无法启动恢复页面，请检查游戏窗口')

    def _replacement(self, view, value):
        ticket = self.ticket
        if (not isinstance(value, dict) or value.get('session') == ticket['session']):
            return  # Document-start scripts may not be installed at didCommit yet.
        session = value.get('session')
        if (not isinstance(session, str) or not session or session in self.retired or
                value.get('revision') != 0 or value.get('enabled') is not False or value.get('fault')):
            self.close()  # A user decision or fatal page error always wins.
            return
        # Evaluation and postMessage callbacks can be delivered in either order.
        if session != self.session:
            if self.session:
                self.retired.add(self.session)
            self.session, self.revision = session, 0
        ticket['stage'] = 'restoring'
        args = json.dumps([ticket['checkpoint'], self.session, 0, ticket['nonce']], ensure_ascii=False)[1:-1]
        self._evaluate(view, f'window.__mjRecovery?.restore({args});', lambda value: self._restored(view, value))

    def _restored(self, view, value):
        if (not isinstance(value, dict) or value.get('session') != self.session or
                value.get('revision') != 1 or self.revision not in (0, 1) or value.get('restored') is not True or
                value.get('enabled') is not True or value.get('fault')):
            self._fail(view, '恢复凭据未被当前页面接受，请检查登录及牌局状态')
            return
        self.revision = value['revision']
        self._cancel()  # Consume once; ordinary refresh cannot inherit this intent.
        self.last_poll = float('-inf')
        self.activity(True)
        self.write('[自动恢复] 已恢复本次自动意图和去重保护，等待完整牌局及新建议')
