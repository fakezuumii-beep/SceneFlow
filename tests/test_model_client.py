import copy,json,unittest
from unittest.mock import patch,Mock
import requests
import model_client as m

CFG={'provider':'deepseek','name':'DeepSeek','base_url':'https://api.deepseek.com','model':'deepseek-v4-flash','api_key':'secret','type':'openai-compatible','request_options':{'thinking':{'type':'disabled'}}}
MESSAGES=[{'role':'user','content':'return JSON'}]
def response(content='{"shots":[]}', finish='stop', status=200, raw=None):
    r=requests.Response();r.status_code=status;r.headers['content-type']='application/json'
    r._content=raw if raw is not None else json.dumps({'choices':[{'finish_reason':finish,'message':{'content':content,'reasoning_content':'private reasoning'}}]}).encode()
    return r

class ModelClientTests(unittest.TestCase):
    @patch('model_client.time.sleep')
    def test_empty_reasoning_budget_response_recovers(self,sleep):
        payloads=[];diagnostics=[]
        replies=iter([response('',finish='length'),response()])
        def send(*a,**k):payloads.append(copy.deepcopy(k['json']));return next(replies)
        with patch('model_client.requests.post',side_effect=send):
            self.assertEqual(m.request_json(CFG,MESSAGES,diagnostic=diagnostics.append),{'shots':[]})
        self.assertEqual(len(payloads),2)
        self.assertEqual(payloads[0]['thinking'],{'type':'disabled'})
        self.assertEqual(payloads[1]['max_tokens'],12000)
        self.assertNotIn('secret',json.dumps(diagnostics));self.assertNotIn('private reasoning',json.dumps(diagnostics))

    @patch('model_client.time.sleep')
    def test_gateway_then_timeout_then_success(self,sleep):
        with patch('model_client.requests.post',side_effect=[response(raw=b'<html>bad gateway</html>'),requests.Timeout(),response()]) as send:
            self.assertEqual(m.request_json(CFG,MESSAGES),{'shots':[]});self.assertEqual(send.call_count,3)

    @patch('model_client.time.sleep')
    def test_bounded_failure_and_friendly_message(self,sleep):
        with patch('model_client.requests.post',return_value=response('')) as send:
            with self.assertRaisesRegex(m.ModelError,'已尝试 3 次.*继续生成'):m.request_json(CFG,MESSAGES)
            self.assertEqual(send.call_count,3)

    def test_invalid_key_is_not_retried(self):
        with patch('model_client.requests.post',return_value=response(status=401)) as send:
            with self.assertRaisesRegex(m.ModelError,'密钥'):m.request_json(CFG,MESSAGES)
            self.assertEqual(send.call_count,1)

    def test_fenced_json_and_missing_reply(self):
        self.assertEqual(m.parse_content('\ufeff```json\n{"shots":[]}\n```'),{'shots':[]})
        with patch('model_client.requests.post',return_value=response(raw=b'{"choices":[]}')),patch('model_client.time.sleep'):
            with self.assertRaisesRegex(m.ModelError,'缺少有效'):m.request_json(CFG,MESSAGES)

    def test_existing_pipeline_resumes_without_retranscribing(self):
        import core
        p={'segments':[{'text':'already transcribed'}],'shots':[], 'job':{},'exports':[]}
        def plan(pid):p['shots']=[{'kind':'A'}]
        def fail(pid):raise m.ModelError('temporary failure')
        with patch.object(core,'read_project',side_effect=lambda pid:p),patch.object(core,'save_project'),patch.object(core,'transcribe') as asr,patch.object(core,'plan',side_effect=fail),patch.object(core,'materials') as stock,patch('aroll.generate') as lips,patch.object(core,'render') as render:
            core.ACTIVE['x']={};core.job_worker('x','all')
            self.assertEqual(p['job']['status'],'error');asr.assert_not_called();stock.assert_not_called();lips.assert_not_called()
        with patch.object(core,'read_project',side_effect=lambda pid:p),patch.object(core,'save_project'),patch.object(core,'transcribe') as asr,patch.object(core,'plan',side_effect=plan),patch.object(core,'materials'),patch('aroll.generate'),patch.object(core,'render') as render:
            core.ACTIVE['x']={};core.job_worker('x','all')
            self.assertEqual(p['job']['status'],'done');asr.assert_not_called();render.assert_called_once()
