"""Bounded OpenAI-compatible SSE responses, opt-in, with cancellation.

No tools/function calls are parsed or executed. Only user-facing text is collected.
"""
from __future__ import annotations
import json
import urllib.request
import urllib.error
from urllib.parse import urlsplit

MAX_CHARS = 150000


class Cancelled(Exception):
    pass


def stream_request(base_url, model, api_key, messages, on_token, stop, timeout=90):
    parsed = urlsplit(base_url)
    loopback = parsed.scheme == 'http' and parsed.hostname in ('localhost','127.0.0.1') and parsed.port is not None
    remote = parsed.scheme == 'https' and parsed.hostname and parsed.port in (None,443)
    if not (loopback or remote) or parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise ValueError('Локальный API: localhost; удалённый API: HTTPS без учётных данных')
    if stop.is_set():
        raise Cancelled('Остановлено пользователем')
    body = json.dumps({'model':model, 'messages':messages, 'stream':True, 'max_tokens':1500}, ensure_ascii=False).encode('utf-8')
    headers = {'Content-Type':'application/json', 'Accept':'text/event-stream'}
    if api_key:
        headers['Authorization']='Bearer '+api_key
    request = urllib.request.Request(base_url.rstrip('/')+'/chat/completions', data=body, headers=headers, method='POST')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise RuntimeError('Перенаправление API запрещено')
    handlers=[NoRedirect()]
    if loopback:
        handlers.append(urllib.request.ProxyHandler({}))
    opener=urllib.request.build_opener(*handlers)
    chunks=[]
    char_count=0
    lines=0
    done=False
    with opener.open(request, timeout=max(5, min(int(timeout),300))) as response:
        for raw in response:
            if stop.is_set():
                raise Cancelled('Остановлено пользователем')
            if len(raw)>1024*1024:
                raise ValueError('Слишком длинное событие ответа')
            lines+=1
            if lines>100000:
                raise ValueError('Превышено число событий ответа')
            line=raw.decode('utf-8', errors='replace').strip()
            if not line.startswith('data:'):
                continue
            payload=line[5:].strip()
            if payload=='[DONE]':
                done=True
                break
            if not payload:
                continue
            event=json.loads(payload)
            if 'error' in event:
                raise RuntimeError(str(event['error'])[:400])
            choices=event.get('choices') or []
            if not choices:
                continue
            delta=choices[0].get('delta') or {}
            token=delta.get('content')
            if isinstance(token,str) and token:
                char_count+=len(token)
                if char_count>MAX_CHARS:
                    raise ValueError('Ответ превысил лимит длины')
                chunks.append(token)
                on_token(token)
        if stop.is_set():
            raise Cancelled('Остановлено пользователем')
    if not done:
        raise RuntimeError('Поток ответа завершился без маркера [DONE]; ответ не сохранён')
    return ''.join(chunks)


def chat_stream(config, messages, api_key, on_token, stop):
    mode=config.get('mode','hybrid')
    timeout=config.get('timeout_seconds',90)
    if mode not in ('local','hybrid','cloud'):
        raise ValueError('Неизвестный режим')
    if mode!='cloud':
        sent=[]
        def local_token(token):
            sent.append(token)
            on_token(token)
        try:
            return stream_request(config['local_url'],config['local_model'],'',messages,local_token,stop,timeout), 'локальный'
        except Cancelled:
            raise
        except Exception as exc:
            if mode=='local' or sent:
                raise RuntimeError('Ошибка локальной генерации: '+str(exc)) from exc
            local_err=str(exc)
    else:
        local_err=''
    if mode=='hybrid' and not config.get('cloud_fallback',False):
        raise RuntimeError('Локальный ИИ недоступен; облачное переключение отключено: '+local_err)
    if not api_key:
        raise RuntimeError('Для облачной модели требуется API-ключ')
    return stream_request(config['cloud_url'],config['cloud_model'],api_key,messages,on_token,stop,timeout), 'облачный'
