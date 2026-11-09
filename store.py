"""SQLite-backed application rules; every operation enforces ownership."""
import csv, hashlib, hmac, io, json, re, secrets, sqlite3, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from seed import DEMO_PASSWORD, SKILLS, UNIVERSITIES, STUDENTS, EMPLOYERS, COORDINATORS, JOBS, APPLICATIONS

class Problem(Exception):
    def __init__(self,message,status=400):super().__init__(message);self.status=status
def now():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def encode(value):return json.dumps(value,ensure_ascii=False)
def password_hash(password,salt):return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
def text(value,limit=2000):
    if not isinstance(value,str):raise Problem('Please enter text in this field.')
    value=value.strip()
    if len(value)>limit:raise Problem(f'This field is limited to {limit} characters.')
    return value
def skills(value):
    if not isinstance(value,list) or any(not isinstance(x,str) or x not in SKILLS for x in value):raise Problem('Choose skills from the available list.')
    return list(dict.fromkeys(value))
def coverage(selected,required):
    matched=[s for s in required if s in selected]
    return {'score':int(100*len(matched)/len(required)+.5) if required else 0,'matched':matched,'missing':[s for s in required if s not in selected]}
SCHEMA='''
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY,email TEXT NOT NULL UNIQUE COLLATE NOCASE,password_hash TEXT NOT NULL,salt TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('student','employer','coordinator')),name TEXT NOT NULL,organization TEXT NOT NULL DEFAULT '',university TEXT NOT NULL DEFAULT '',city TEXT NOT NULL DEFAULT '',skills TEXT NOT NULL DEFAULT '[]',evidence TEXT NOT NULL DEFAULT '',portfolio TEXT NOT NULL DEFAULT '',headline TEXT NOT NULL DEFAULT '',is_demo INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY,code TEXT UNIQUE,employer_id INTEGER NOT NULL REFERENCES users(id),title TEXT NOT NULL,city TEXT NOT NULL,mode TEXT NOT NULL,duration TEXT NOT NULL,stipend TEXT NOT NULL DEFAULT '',skills TEXT NOT NULL,description TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS applications (id INTEGER PRIMARY KEY,student_id INTEGER NOT NULL REFERENCES users(id),job_id INTEGER NOT NULL REFERENCES jobs(id),university TEXT NOT NULL,snapshot TEXT NOT NULL,match_data TEXT NOT NULL,status TEXT NOT NULL,message TEXT NOT NULL,history TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(student_id,job_id));
CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS bookmarks (student_id INTEGER NOT NULL REFERENCES users(id),job_id INTEGER NOT NULL REFERENCES jobs(id),PRIMARY KEY(student_id,job_id));
CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),title TEXT NOT NULL,detail TEXT NOT NULL,is_read INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_apps_student ON applications(student_id);
CREATE INDEX IF NOT EXISTS ix_apps_job ON applications(job_id);
CREATE INDEX IF NOT EXISTS ix_notifications_user ON notifications(user_id);
'''
def initialize(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    s=Store(path);s.db.executescript(SCHEMA);s.db.execute('PRAGMA journal_mode=WAL')
    try:
        s.db.execute('BEGIN IMMEDIATE')
        if s.db.execute("SELECT 1 FROM settings WHERE key='seed_v1'").fetchone():s.db.commit();return
        ids={};job_ids={}
        def user(key,name,role,organization='',university='',city='',selected=None,evidence='',headline=''):
            salt=secrets.token_hex(16)
            cur=s.db.execute('INSERT INTO users(email,password_hash,salt,role,name,organization,university,city,skills,evidence,headline,is_demo,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(key+'@qadam.demo',password_hash(DEMO_PASSWORD,salt),salt,role,name,organization,university,city,encode(selected or []),evidence,headline,1,now()));ids[key]=cur.lastrowid
        for key,name,uni,city,ss,evidence,headline in STUDENTS:user(key,name,'student',university=uni,city=city,selected=ss,evidence=evidence,headline=headline)
        for key,name,company,city,bio in EMPLOYERS:user(key,name,'employer',organization=company,city=city,evidence=bio)
        for key,name,uni,city in COORDINATORS:user(key,name,'coordinator',organization=uni+' Career Centre',university=uni,city=city)
        for code,employer,title,city,mode,duration,stipend,ss,description in JOBS:
            cur=s.db.execute('INSERT INTO jobs(code,employer_id,title,city,mode,duration,stipend,skills,description,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(code,ids[employer],title,city,mode,duration,stipend,encode(ss),description,now(),now()));job_ids[code]=cur.lastrowid
        paths={'Applied':['Applied'],'Shortlisted':['Applied','Shortlisted'],'Offered':['Applied','Shortlisted','Offered'],'Accepted':['Applied','Offered','Accepted'],'Confirmed':['Applied','Offered','Accepted','Confirmed'],'Rejected':['Applied','Rejected']}
        for idx,(student,code,status) in enumerate(APPLICATIONS):
            u=s.user(ids[student]);j=s.job(job_ids[code]);snapshot=s.snapshot(u);history=[]
            snapshot.update({'job_title':j['title'],'required_skills':j['skills']})
            for step,st in enumerate(paths[status]):
                role='student' if st in ['Applied','Accepted'] else 'coordinator' if st=='Confirmed' else 'employer'
                at=(datetime.now(timezone.utc)-timedelta(days=8-idx%4,hours=4-step)).isoformat(timespec='seconds')
                history.append({'status':st,'role':role,'actor':'Seeded example','note':'Fictional classroom record.','at':at})
            s.db.execute('INSERT INTO applications(student_id,job_id,university,snapshot,match_data,status,message,history,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(u['id'],j['id'],u['university'],encode(snapshot),encode(coverage(u['skills'],j['skills'])),status,'Please consider the project evidence in my profile.',encode(history),history[0]['at'],history[-1]['at']))
        for uid in ids.values():s.notify(uid,'Welcome to Qadam','Your demonstration account is ready. All seeded people, companies and placements are fictional.')
        s.db.execute("INSERT INTO settings(key,value) VALUES('seed_v1','1')");s.db.commit()
    except Exception:s.db.rollback();raise
    finally:s.close()

class Store:
    def __init__(self,path):
        self.db=sqlite3.connect(str(path),timeout=15);self.db.row_factory=sqlite3.Row;self.db.execute('PRAGMA foreign_keys=ON')
    def close(self):self.db.close()
    def user(self,id):
        row=self.db.execute('SELECT * FROM users WHERE id=?',(id,)).fetchone()
        if not row:raise Problem('User not found.',404)
        u=dict(row);u.pop('password_hash');u.pop('salt');u['skills']=json.loads(u['skills']);return u
    def job(self,id):
        row=self.db.execute('SELECT j.*,u.organization AS company,u.name AS employer_name FROM jobs j JOIN users u ON j.employer_id=u.id WHERE j.id=?',(id,)).fetchone()
        if not row:raise Problem('Internship not found.',404)
        j=dict(row);j['skills']=json.loads(j['skills']);j['active']=bool(j['active']);return j
    def snapshot(self,u):return {k:u[k] for k in ['name','email','university','city','skills','evidence','portfolio','headline']}
    def require(self,u,role):
        if u['role']!=role:raise Problem('This action is not available for your account.',403)
    def notify(self,uid,title,detail):self.db.execute('INSERT INTO notifications(user_id,title,detail,created_at) VALUES(?,?,?,?)',(uid,title,detail,now()))
    def session(self,u):
        token=secrets.token_urlsafe(32)
        self.db.execute('DELETE FROM sessions WHERE expires_at < ?',(time.time(),))
        self.db.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),u['id'],time.time()+8*3600));self.db.commit();return token,u
    def login(self,email,password):
        email=text(email,254).lower();password=text(password,128);row=self.db.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
        candidate=password_hash(password,row['salt'] if row else '0'*32)
        if not row or not hmac.compare_digest(candidate,row['password_hash']):raise Problem('Email or password is incorrect.',401)
        return self.session(self.user(row['id']))
    def authenticate(self,token):
        if not token:raise Problem('Please sign in.',401)
        row=self.db.execute('SELECT user_id FROM sessions WHERE token_hash=? AND expires_at>?',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
        if not row:raise Problem('Your session has expired. Please sign in again.',401)
        return self.user(row['user_id'])
    def logout(self,token):self.db.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),));self.db.commit()
    def register(self,b):
        name=text(b.get('name',''),60);email=text(b.get('email',''),254).lower();password=text(b.get('password',''),128);uni=b.get('university')
        if not name or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):raise Problem('Enter a name and a valid email address.')
        if len(password)<8:raise Problem('Use a password with at least 8 characters.')
        if uni not in UNIVERSITIES:raise Problem('Choose a university.')
        salt=secrets.token_hex(16)
        try:
            cur=self.db.execute('INSERT INTO users(email,password_hash,salt,role,name,university,city,created_at) VALUES(?,?,?,?,?,?,?,?)',(email,password_hash(password,salt),salt,'student',name,uni,'Astana' if uni=='AITU' else 'Almaty',now()))
            self.notify(cur.lastrowid,'Welcome to Qadam','Complete your skills and project note to start applying.');self.db.commit()
        except sqlite3.IntegrityError:self.db.rollback();raise Problem('An account with this email already exists.',409)
        return self.session(self.user(cur.lastrowid))
    def demo_accounts(self):return [dict(r) for r in self.db.execute('SELECT id,email,name,role,organization,university,headline FROM users WHERE is_demo=1 ORDER BY role DESC,id')]
    def update_profile(self,u,b):
        current=self.user(u['id'])
        for field,limit in [('name',60),('city',60),('evidence',1500),('headline',100),('portfolio',500)]:
            if field in b:current[field]=text(b[field],limit)
        if not current['name']:raise Problem('Your name cannot be empty.')
        if 'skills' in b:self.require(u,'student');current['skills']=skills(b['skills'])
        if current['portfolio']:
            url=urlsplit(current['portfolio'])
            if url.scheme not in ['https','http'] or not url.netloc or url.username or url.password:raise Problem('Use an http:// or https:// portfolio link without credentials.')
        self.db.execute('UPDATE users SET name=?,city=?,skills=?,evidence=?,portfolio=?,headline=? WHERE id=?',(current['name'],current['city'],encode(current['skills']),current['evidence'],current['portfolio'],current['headline'],u['id']));self.db.commit();return self.user(u['id'])
    def save_job(self,u,b,id=None):
        self.require(u,'employer')
        if id is not None:
            j=self.job(id)
            if j['employer_id']!=u['id']:raise Problem('This vacancy belongs to another employer.',403)
        else:j={'title':'','city':u['city'],'mode':'Hybrid','duration':'12 weeks','stipend':'','description':'','skills':[],'active':True}
        for f,l in [('title',100),('city',60),('mode',20),('duration',60),('stipend',80),('description',2500)]:
            if f in b:j[f]=text(b[f],l)
        if 'skills' in b:j['skills']=skills(b['skills'])
        if 'active' in b:
            if not isinstance(b['active'],bool):raise Problem('Invalid vacancy status.')
            j['active']=b['active']
        if not all(j[k] for k in ['title','city','duration','description','skills']):raise Problem('Complete the title, city, duration, description and at least one required skill.')
        if j['mode'] not in ['Remote','Hybrid','On-site']:raise Problem('Choose a valid work format.')
        values=(j['title'],j['city'],j['mode'],j['duration'],j['stipend'],encode(j['skills']),j['description'],int(j['active']),now())
        if id is None:
            cur=self.db.execute('INSERT INTO jobs(title,city,mode,duration,stipend,skills,description,active,updated_at,employer_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',values+(u['id'],now()));id=cur.lastrowid
        else:self.db.execute('UPDATE jobs SET title=?,city=?,mode=?,duration=?,stipend=?,skills=?,description=?,active=?,updated_at=? WHERE id=?',values+(id,))
        self.db.commit();return self.job(id)
    def app_rows(self,u):
        if u['role']=='student':where='a.student_id=?';arg=u['id']
        elif u['role']=='employer':where='j.employer_id=?';arg=u['id']
        else:where='a.university=?';arg=u['university']
        rows=self.db.execute('SELECT a.*,j.title AS job_title,j.employer_id,e.organization AS company,j.city,j.mode,j.active AS job_active FROM applications a JOIN jobs j ON a.job_id=j.id JOIN users e ON j.employer_id=e.id WHERE '+where+' ORDER BY a.updated_at DESC,a.id DESC',(arg,)).fetchall()
        return [self.decode_app(r) for r in rows]
    def decode_app(self,row):
        a=dict(row);a['snapshot']=json.loads(a['snapshot']);a['match']=json.loads(a.pop('match_data'));a['history']=json.loads(a['history']);return a
    def get_application(self,u,id):
        rows=[a for a in self.app_rows(u) if a['id']==id]
        if not rows:raise Problem('Application not found for this account.',404)
        return rows[0]
    def apply(self,u,job_id,message=''):
        self.require(u,'student');u=self.user(u['id']);j=self.job(job_id)
        if not j['active']:raise Problem('This internship is closed.',409)
        if not u['skills'] or not u['evidence'].strip():raise Problem('Add your skills and a project evidence note in My profile before applying.')
        message=text(message,1500);at=now();snapshot=self.snapshot(u);snapshot.update({'job_title':j['title'],'required_skills':j['skills']})
        history=[{'status':'Applied','role':'student','actor':u['name'],'note':message or 'Application submitted.','at':at}]
        try:
            cur=self.db.execute('INSERT INTO applications(student_id,job_id,university,snapshot,match_data,status,message,history,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(u['id'],job_id,u['university'],encode(snapshot),encode(coverage(u['skills'],j['skills'])),'Applied',message,encode(history),at,at))
            self.notify(j['employer_id'],'New application',u['name']+' applied to '+j['title']+'.');self.db.commit()
        except sqlite3.IntegrityError:self.db.rollback();raise Problem('You have already applied to this internship.',409)
        return self.get_application(u,cur.lastrowid)
    def transition(self,u,id,status,note=''):
        note=text(note,1000);self.db.execute('BEGIN IMMEDIATE')
        try:
            a=self.get_application(u,id)
            rules={'Applied':{'employer':['Shortlisted','Offered','Rejected'],'student':['Withdrawn']},'Shortlisted':{'employer':['Offered','Rejected'],'student':['Withdrawn']},'Offered':{'student':['Accepted','Declined']},'Accepted':{'coordinator':['Confirmed']}}
            if status not in rules.get(a['status'],{}).get(u['role'],[]):raise Problem('This action is no longer available. Refresh the application status.',409)
            if status=='Confirmed' and not note:raise Problem('Record the verified start date and confirmation note.')
            at=now();a['history'].append({'status':status,'role':u['role'],'actor':u['name'],'note':note,'at':at})
            self.db.execute('UPDATE applications SET status=?,history=?,updated_at=? WHERE id=?',(status,encode(a['history']),at,id))
            recipients={a['student_id'],a['employer_id']}
            if status in ['Accepted','Confirmed']:recipients.update(r['id'] for r in self.db.execute("SELECT id FROM users WHERE role='coordinator' AND university=?",(a['university'],)))
            recipients.discard(u['id'])
            for uid in recipients:self.notify(uid,'Application '+status.lower(),a['snapshot']['name']+' - '+a['job_title']+': '+status+('. '+note if note else '.'))
            self.db.commit()
        except Exception:self.db.rollback();raise
        return self.get_application(u,id)
    def bookmark(self,u,job_id):
        self.require(u,'student');self.job(job_id)
        with self.db:
            exists=self.db.execute('SELECT 1 FROM bookmarks WHERE student_id=? AND job_id=?',(u['id'],job_id)).fetchone()
            if exists:self.db.execute('DELETE FROM bookmarks WHERE student_id=? AND job_id=?',(u['id'],job_id))
            else:self.db.execute('INSERT INTO bookmarks VALUES(?,?)',(u['id'],job_id))
        return {'saved':not bool(exists)}
    def read_notifications(self,u):self.db.execute('UPDATE notifications SET is_read=1 WHERE user_id=?',(u['id'],));self.db.commit();return {'ok':True}
    def bootstrap(self,u):
        u=self.user(u['id']);q='SELECT id FROM jobs';args=()
        if u['role']=='employer':q+=' WHERE employer_id=?';args=(u['id'],)
        elif u['role']=='student':q+=' WHERE active=1 OR id IN (SELECT job_id FROM bookmarks WHERE student_id=?)';args=(u['id'],)
        else:q+=' WHERE active=1'
        js=[self.job(r['id']) for r in self.db.execute(q+' ORDER BY id DESC',args)]
        for j in js:j['match']=coverage(u['skills'],j['skills'])
        students=[]
        if u['role']=='coordinator':students=[self.user(r['id']) for r in self.db.execute("SELECT id FROM users WHERE role='student' AND university=? ORDER BY name",(u['university'],))]
        notes=[dict(r) for r in self.db.execute('SELECT id,title,detail,is_read,created_at FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 100',(u['id'],))]
        return {'user':u,'jobs':js,'applications':self.app_rows(u),'students':students,'notifications':notes,'bookmarks':[r['job_id'] for r in self.db.execute('SELECT job_id FROM bookmarks WHERE student_id=?',(u['id'],))],'skills':SKILLS,'universities':UNIVERSITIES}
    def export_csv(self,u):
        self.require(u,'coordinator');f=io.StringIO(newline='');writer=csv.writer(f)
        writer.writerow(['application_id','student','university','internship','company','status','coverage_at_application','updated_at'])
        def safe(value):
            value=str(value)
            return "'"+value if value.lstrip().startswith(('=','+','-','@')) else value
        for a in self.app_rows(u):writer.writerow([safe(v) for v in [a['id'],a['snapshot']['name'],a['university'],a['job_title'],a['company'],a['status'],a['match']['score'],a['updated_at']]])
        return f.getvalue()
