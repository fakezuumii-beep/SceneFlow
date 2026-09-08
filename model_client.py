"""Bounded retries and diagnostic metadata for structured planning replies."""
import copy
import json
import re
import time
import requests


class ModelError(RuntimeError):
    def __init__(self, message, retryable=True):
        super().__init__(message)
        self.retryable = retryable


def parse_content(content):
    if isinstance(content, list):
        content = ''.join(x.get('text', '') for x in content if isinstance(x, dict) and x.get('type') == 'text')
    if not isinstance(content, str) or not content.strip():
        raise ModelError('语义模型返回了空回复')
    text = content.strip().lstrip('\ufeff')
    text = re.sub(r'^<think>.*?</think>\s*', '', text, flags=re.S)
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip(), flags=re.I)
    try:
        value = json.loads(text)
    except ValueError:
        raise ModelError('语义模型返回的分镜格式不完整或不是有效 JSON') from None
    if not isinstance(value, dict):
        raise ModelError('语义模型未返回分镜对象')
    return value


def request_json(cfg, messages, report=None, diagnostic=None, attempts=3):
    url = cfg['base_url'].rstrip('/') + '/chat/completions'
    headers = {'Content-Type': 'application/json'}
    if cfg['api_key']:
        headers['Authorization'] = 'Bearer ' + cfg['api_key']
    payload = {'model': cfg['model'], 'messages': copy.deepcopy(messages),
               'temperature': .2, 'max_tokens': 6000, 'response_format': {'type': 'json_object'}}
    payload.update(copy.deepcopy(cfg.get('request_options') or {}))
    last = None
    for attempt in range(attempts):
        if report:
            report(f'正在请求语义分镜（第 {attempt+1}/{attempts} 次）' if not last else f'{last}；正在自动重试（第 {attempt+1}/{attempts} 次）')
        meta = {'attempt': attempt+1, 'provider': cfg['provider'], 'model': cfg['model']}
        began = time.monotonic()
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=(10,90))
            meta.update(http_status=response.status_code, content_type=response.headers.get('content-type',''), response_bytes=len(response.content))
            if response.status_code in (401,403):
                raise ModelError('语义服务密钥无效或没有权限，请在「连接与设置」检查密钥', False)
            if response.status_code != 200:
                retry = response.status_code in (408,429) or response.status_code >= 500
                raise ModelError(f'语义服务暂时不可用（HTTP {response.status_code}）' if retry else f'语义请求被拒绝（HTTP {response.status_code}），请检查模型和连接设置', retry)
            try:
                body = response.json()
            except ValueError:
                raise ModelError('语义服务返回了空响应或非 JSON 网关内容') from None
            if not isinstance(body, dict) or not isinstance(body.get('choices'), list) or not body['choices']:
                raise ModelError('语义服务响应缺少有效的模型回复')
            choice = body['choices'][0]
            if not isinstance(choice, dict) or not isinstance(choice.get('message'),dict):
                raise ModelError('语义服务回复结构异常')
            message = choice['message']
            content = message.get('content')
            meta.update(finish_reason=choice.get('finish_reason'), content_chars=len(content) if isinstance(content,str) else 0,
                        reasoning_chars=len(message.get('reasoning_content') or ''))
            if choice.get('finish_reason') == 'length':
                payload['max_tokens'] = 12000
                raise ModelError('语义模型回复达到长度上限，分镜尚未完整返回')
            if choice.get('finish_reason') == 'content_filter' or message.get('refusal'):
                raise ModelError('语义服务未接受这次内容，无法生成分镜',False)
            value = parse_content(content)
            meta['result'] = 'ok'
            return value
        except requests.RequestException:
            last = ModelError('语义服务连接中断或响应超时')
            meta.update(result='error',error=str(last))
        except ModelError as exc:
            last = exc
            meta.update(result='error',error=str(exc))
            if not exc.retryable:
                raise
        finally:
            meta['seconds'] = round(time.monotonic()-began,2)
            if diagnostic:
                diagnostic(meta)  # Metadata only: no key, transcript, or reasoning text.
        if attempt+1 < attempts:
            payload['messages'] = copy.deepcopy(messages) + [{'role':'user','content':'请只返回完整的 JSON 分镜对象，不要空回复、Markdown 或额外解释。'}]
            time.sleep(attempt+1)
    raise ModelError(f'{last}。已尝试 {attempts} 次；已完成内容保留，可点击「继续生成」重试。')
