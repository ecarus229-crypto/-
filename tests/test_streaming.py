import json
import threading
import unittest
from unittest.mock import patch
from assistant_app import streaming, core

class FakeResponse:
    def __init__(self, lines): self.lines=lines
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def __iter__(self): return iter(self.lines)

class StreamingTests(unittest.TestCase):
    def test_sse_parse(self):
        body=[b'data: '+json.dumps({'choices':[{'delta':{'content':token}}]}).encode()+b'\n' for token in ['При','вет']]
        body.append(b'data: [DONE]\n')
        class FakeOpener:
            def open(self,*args,**kwargs):return FakeResponse(body)
        with patch.object(streaming.urllib.request,'build_opener',return_value=FakeOpener()):
            tokens=[]
            answer=streaming.stream_request('http://127.0.0.1:8080/v1','local','',[],tokens.append,threading.Event())
            self.assertEqual(answer,'Привет')
            self.assertEqual(tokens,['При','вет'])
    def test_stop_before_request(self):
        stop=threading.Event();stop.set()
        with self.assertRaises(streaming.Cancelled):
            streaming.stream_request('http://127.0.0.1:8080/v1','local','',[],lambda x:None,stop)
    def test_no_cloud_fallback(self):
        cfg=core.DEFAULT_CONFIG.copy()
        with patch.object(streaming,'stream_request',side_effect=RuntimeError('no server')) as fn:
            with self.assertRaisesRegex(RuntimeError,'отключено'):
                streaming.chat_stream(cfg,[], 'secret',lambda x:None,threading.Event())
            self.assertEqual(fn.call_count,1)
    def test_no_fallback_after_partial_stream(self):
        cfg={**core.DEFAULT_CONFIG,'cloud_fallback':True}
        def fail(*args):
            args[4]('partial')
            raise RuntimeError('broken')
        with patch.object(streaming,'stream_request',side_effect=fail) as fn:
            with self.assertRaisesRegex(RuntimeError,'Ошибка локальной'):
                streaming.chat_stream(cfg,[], 'secret',lambda x:None,threading.Event())
            self.assertEqual(fn.call_count,1)
    def test_reject_remote_http(self):
        with self.assertRaises(ValueError):
            streaming.stream_request('http://example.com/v1','local','',[],lambda x:None,threading.Event())
