"""Serve only the dashboard directory on localhost; never expose raw/cache data."""
import argparse
import json
import re
import uuid
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

class Handler(SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path!='/api/export':
            self.send_error(404);return
        host=self.headers.get('Host','')
        if host not in [f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'] or self.headers.get('Origin')!='http://'+host:
            self.send_error(403,'Same-origin local requests only');return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=16*1024*1024:raise ValueError('Invalid export size')
            body=json.loads(self.rfile.read(length))
            name=body.get('name','');csv=body.get('csv')
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}\.csv',name) or not isinstance(csv,str):raise ValueError('Invalid export')
        except (ValueError,TypeError,AttributeError):
            self.send_error(400,'Invalid export request');return
        directory=Path(self.directory)/'exports';directory.mkdir(exist_ok=True)
        filename=name[:-4]+'-'+uuid.uuid4().hex[:8]+'.csv'
        (directory/filename).write_text(csv,encoding='utf-8',newline='')
        data=json.dumps({'url':'/exports/'+filename,'name':filename},ensure_ascii=False).encode()
        self.send_response(201);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def end_headers(self):
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        if self.path.startswith('/exports/') and self.path.endswith('.csv'):
            self.send_header('Content-Disposition','attachment; filename="'+Path(self.path).name+'"')
        super().end_headers()
    def list_directory(self,path):
        self.send_error(403,'Directory listing disabled')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8765);args=p.parse_args()
    root=Path(__file__).resolve().parent/'web'
    with ThreadingHTTPServer(('127.0.0.1',args.port),partial(Handler,directory=str(root))) as server:
        print(f'ubs-engine dashboard: http://127.0.0.1:{args.port}',flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt:pass
