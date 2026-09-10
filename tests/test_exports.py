import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from serve import Handler

class ExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=self.tmp.name))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.origin=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def post(self,name,origin=None):
        return urllib.request.urlopen(urllib.request.Request(self.origin+'/api/export',data=json.dumps({'name':name,'csv':'\ufeff"PR","标题"\r\n"1","测试"'}).encode(),headers={'Content-Type':'application/json','Origin':origin or self.origin}),timeout=5)
    def test_csv_export_is_saved_and_readable(self):
        try:
            with self.post('ubs-engine-pr-summary.csv') as r:d=json.load(r)
        except urllib.error.HTTPError as e:
            code=e.code;e.close();self.fail(f'CSV export unavailable: HTTP {code}')
        raw=(Path(self.tmp.name)/d['url'].lstrip('/')).read_text('utf-8-sig')
        self.assertIn('"1","测试"',raw)
        with urllib.request.urlopen(self.origin+d['url']) as r:self.assertEqual(r.status,200)
    def test_path_traversal_and_external_origin_rejected(self):
        for name,origin in [('../outside.csv',None),('test.csv','https://example.com')]:
            with self.assertRaises(urllib.error.HTTPError) as caught:self.post(name,origin)
            self.assertIn(caught.exception.code,[400,403])
            caught.exception.close()

if __name__=='__main__':unittest.main()
