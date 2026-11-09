import http.client, json, sys, tempfile, threading, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import QadamServer
from store import initialize

class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=Path(__file__).resolve().parents[1]/'data/test-databases'
        cls.root.mkdir(parents=True,exist_ok=True)
        cls.temp=tempfile.TemporaryDirectory(dir=cls.root)
        db=Path(cls.temp.name)/'http.sqlite3';initialize(db)
        cls.server=QadamServer(('127.0.0.1',0),db)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()
        assert Path(cls.temp.name).resolve().is_relative_to(cls.root.resolve())
        cls.temp.cleanup()
    def request(self,path,method='GET',body=None,cookie=None,headers=None):
        h={'Content-Type':'application/json','X-Qadam-Request':'1'}
        if cookie:h['Cookie']=cookie
        if headers:h.update(headers)
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        c.request(method,path,json.dumps(body) if body is not None else None,h)
        r=c.getresponse();raw=r.read();result=(r.status,dict(r.getheaders()),raw);c.close();return result
    def login(self,email):
        status,h,raw=self.request('/api/login','POST',{'email':email,'password':'Qadam2026!'})
        self.assertEqual(status,200);self.assertIn('HttpOnly',h['Set-Cookie']);self.assertIn('SameSite=Strict',h['Set-Cookie'])
        self.assertNotIn('password_hash',raw.decode())
        return h['Set-Cookie'].split(';')[0]
    def test_request_guards_and_static_isolation(self):
        self.assertEqual(self.request('/api/bootstrap')[0],401)
        self.assertEqual(self.request('/api/health',headers={'Host':'attacker.example'})[0],403)
        self.assertEqual(self.request('/api/login','POST',{},headers={'Origin':'https://attacker.example'})[0],403)
        self.assertEqual(self.request('/api/login','POST',{},headers={'X-Qadam-Request':'0'})[0],403)
        self.assertEqual(self.request('/api/login','POST',{},headers={'Sec-Fetch-Site':'cross-site'})[0],403)
        self.assertEqual(self.request('/api/login','POST',{},headers={'Content-Type':'text/plain'})[0],415)
        for path in ['/data/qadam.sqlite3','/../store.py','/server.py']:
            self.assertEqual(self.request(path)[0],404)
        status,headers,raw=self.request('/')
        self.assertEqual(status,200);self.assertIn('Content-Security-Policy',headers);self.assertIn(b'app.js',raw)
    def test_cookie_workflow_scope_and_export(self):
        student=self.login('aruzhan@qadam.demo');employer=self.login('steppe@qadam.demo');coordinator=self.login('aitu@qadam.demo');other=self.login('ornek@qadam.demo')
        boot=json.loads(self.request('/api/bootstrap',cookie=student)[2]);job=next(j for j in boot['jobs'] if j['code']=='data')
        status,_,raw=self.request('/api/applications','POST',{'jobId':job['id'],'message':'HTTP workflow test'},student)
        self.assertEqual(status,201);app=json.loads(raw);path=f"/api/applications/{app['id']}/status"
        self.assertEqual(self.request(path,'POST',{'status':'Offered'},other)[0],404)
        self.assertEqual(self.request(path,'POST',{'status':'Confirmed','note':'Premature'},coordinator)[0],409)
        for who,status in [(employer,'Offered'),(student,'Accepted'),(coordinator,'Confirmed')]:
            code,_,raw=self.request(path,'POST',{'status':status,'note':'Fictional verification, start 2 November'},who)
            self.assertEqual(code,200);self.assertEqual(json.loads(raw)['status'],status)
        self.assertEqual(len(json.loads(raw)['history']),4)
        self.assertEqual(self.request('/api/export',cookie=student)[0],403)
        code,h,raw=self.request('/api/export',cookie=coordinator)
        self.assertEqual(code,200);self.assertIn('attachment',h['Content-Disposition']);self.assertNotIn('IITU',raw.decode());self.assertIn('Confirmed',raw.decode())
        self.assertEqual(self.request('/api/logout','POST',{},student)[0],200)
        self.assertEqual(self.request('/api/bootstrap',cookie=student)[0],401)
    def test_registration_profile_and_job_creation(self):
        code,h,raw=self.request('/api/register','POST',{'name':'HTTP Test Student','email':'http@example.test','password':'LocalTest2026!','university':'AITU','role':'coordinator'})
        self.assertEqual(code,201);self.assertEqual(json.loads(raw)['user']['role'],'student');student=h['Set-Cookie'].split(';')[0]
        code,_,raw=self.request('/api/profile','PATCH',{'skills':['SQL'],'evidence':'Built a fictional SQL report.'},student)
        self.assertEqual(code,200);self.assertEqual(json.loads(raw)['skills'],['SQL'])
        vacancy={'title':'HTTP Test Intern','city':'Astana','mode':'Remote','duration':'8 weeks','description':'Practice SQL with sample data.','skills':['SQL']}
        self.assertEqual(self.request('/api/jobs','POST',vacancy,student)[0],403)
        employer=self.login('steppe@qadam.demo');code,_,raw=self.request('/api/jobs','POST',vacancy,employer)
        self.assertEqual(code,201);job=json.loads(raw)
        self.assertEqual(self.request(f"/api/jobs/{job['id']}",'PATCH',{'active':False},employer)[0],200)
        self.assertEqual(self.request('/api/applications','POST',{'jobId':job['id']},student)[0],409)

if __name__=='__main__':unittest.main()
