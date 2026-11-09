"""Local-only Qadam server. Run with Python 3.10+; no packages required."""
import argparse, json, mimetypes, threading, time, traceback
from collections import defaultdict
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from store import Store, Problem, initialize
from seed import DEMO_PASSWORD, SKILLS, UNIVERSITIES

BASE=Path(__file__).resolve().parent
class QadamServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,db_path):
        self.db_path=db_path;self.login_attempts=defaultdict(list);self.rate_lock=threading.Lock()
        super().__init__(address,Handler)

class Handler(BaseHTTPRequestHandler):
    server_version='Qadam/2.0'
    def log_message(self,format,*args):pass
    def reply(self,data,status=200,content_type='application/json; charset=utf-8',cookie=None,download=None):
        raw=json.dumps(data,ensure_ascii=False).encode('utf-8') if content_type.startswith('application/json') else data if isinstance(data,bytes) else data.encode('utf-8')
        self.send_response(status);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','same-origin')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'")
        if cookie is not None:self.send_header('Set-Cookie','qadam_session='+cookie+'; HttpOnly; SameSite=Strict; Path=/; Max-Age='+('28800' if cookie else '0'))
        if download:self.send_header('Content-Disposition','attachment; filename="'+download+'"')
        self.end_headers();self.wfile.write(raw)
    def token(self):
        cookie=SimpleCookie()
        try:cookie.load(self.headers.get('Cookie',''))
        except Exception:return ''
        return cookie['qadam_session'].value if 'qadam_session' in cookie else ''
    def guard(self,write=False):
        host=self.headers.get('Host','')
        allowed={'127.0.0.1:'+str(self.server.server_port),'localhost:'+str(self.server.server_port)}
        if host not in allowed:raise Problem('Use the local Qadam address.',403)
        if write:
            if self.headers.get('X-Qadam-Request')!='1':raise Problem('Open this action from Qadam.',403)
            origin=self.headers.get('Origin')
            if origin and origin!='http://'+host:raise Problem('Cross-origin requests are not permitted.',403)
            if self.headers.get('Sec-Fetch-Site') in ['cross-site','same-site']:raise Problem('Cross-origin requests are not permitted.',403)
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise Problem('JSON request required.',415)
    def body(self):
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:raise Problem('Invalid request length.')
        if length<0 or length>65536:raise Problem('The request is too large.',413)
        try:data=json.loads(self.rfile.read(length) or b'{}')
        except (ValueError,UnicodeError):raise Problem('Invalid JSON request.')
        if not isinstance(data,dict):raise Problem('An object is required.')
        return data
    def throttle(self,email):
        key=(self.client_address[0],str(email).lower());t=time.time()
        with self.server.rate_lock:
            recent=[x for x in self.server.login_attempts[key] if t-x<60]
            if len(recent)>=15:raise Problem('Too many attempts. Wait one minute and try again.',429)
            self.server.login_attempts[key]=recent+[t]
    def do_GET(self):self.handle_route(False)
    def do_POST(self):self.handle_route(True)
    def do_PATCH(self):self.handle_route(True)
    def do_OPTIONS(self):self.reply({'error':'Cross-origin requests are not enabled.'},403)
    def handle_route(self,write):
        store=None
        try:
            self.guard(write);path=urlsplit(self.path).path
            if not write and path=='/api/health':return self.reply({'app':'qadam','version':'2.0','ok':True})
            if not path.startswith('/api/'):
                if write:raise Problem('Not found.',404)
                files={'/':'index.html','/index.html':'index.html','/app.js':'app.js','/styles.css':'styles.css','/favicon.svg':'favicon.svg'}
                if path not in files:raise Problem('Page not found.',404)
                target=BASE/'static'/files[path]
                return self.reply(target.read_bytes(),content_type=mimetypes.guess_type(str(target))[0] or 'application/octet-stream')
            store=Store(self.server.db_path);b=self.body() if write else {}
            if path=='/api/meta' and not write:return self.reply({'accounts':store.demo_accounts(),'demoPassword':DEMO_PASSWORD,'skills':SKILLS,'universities':UNIVERSITIES})
            if path=='/api/login' and self.command=='POST':
                self.throttle(b.get('email'));token,u=store.login(b.get('email',''),b.get('password',''));return self.reply({'user':u},cookie=token)
            if path=='/api/register' and self.command=='POST':
                self.throttle(b.get('email'));token,u=store.register(b);return self.reply({'user':u},201,cookie=token)
            if path=='/api/logout' and self.command=='POST':store.logout(self.token());return self.reply({'ok':True},cookie='')
            u=store.authenticate(self.token())
            if path=='/api/bootstrap' and not write:return self.reply(store.bootstrap(u))
            if path=='/api/profile' and self.command=='PATCH':return self.reply(store.update_profile(u,b))
            if path=='/api/jobs' and self.command=='POST':return self.reply(store.save_job(u,b),201)
            parts=path.strip('/').split('/')
            if len(parts)==3 and parts[:2]==['api','jobs'] and self.command=='PATCH':return self.reply(store.save_job(u,b,int(parts[2])))
            if path=='/api/applications' and self.command=='POST':return self.reply(store.apply(u,int(b.get('jobId',0)),b.get('message','')),201)
            if len(parts)==4 and parts[:2]==['api','applications'] and parts[3]=='status' and self.command=='POST':return self.reply(store.transition(u,int(parts[2]),b.get('status',''),b.get('note','')))
            if len(parts)==3 and parts[:2]==['api','bookmarks'] and self.command=='POST':return self.reply(store.bookmark(u,int(parts[2])))
            if path=='/api/notifications/read' and self.command=='POST':return self.reply(store.read_notifications(u))
            if path=='/api/export' and not write:return self.reply('\ufeff'+store.export_csv(u),content_type='text/csv; charset=utf-8',download='qadam-placements.csv')
            raise Problem('Not found.',404)
        except Problem as e:self.reply({'error':str(e)},e.status)
        except (ValueError,TypeError):self.reply({'error':'Invalid request value.'},400)
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception:
            traceback.print_exc();self.reply({'error':'The local server could not finish this action. Try again.'},500)
        finally:
            if store:store.close()

def main():
    parser=argparse.ArgumentParser(description='Qadam local MVP')
    parser.add_argument('--port',type=int,default=8766);parser.add_argument('--db',type=Path,default=BASE/'data/qadam.sqlite3')
    args=parser.parse_args();initialize(args.db)
    server=QadamServer(('127.0.0.1',args.port),args.db)
    print(f'Qadam is ready at http://127.0.0.1:{args.port}',flush=True)
    print('Local classroom application. Ctrl+C stops the server.',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
if __name__=='__main__':main()
