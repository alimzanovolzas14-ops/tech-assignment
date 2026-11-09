import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import Store, Problem, initialize

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.test_root=Path(__file__).resolve().parents[1]/'data/test-databases'
        self.test_root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=self.test_root)
        self.path=Path(self.temp.name)/'qadam.sqlite3'
        initialize(self.path)
        self.s=Store(self.path)
    def tearDown(self):
        self.s.close()
        self.assertTrue(Path(self.temp.name).resolve().is_relative_to(self.test_root.resolve()))
        self.temp.cleanup()
    def user(self,email):
        token,u=self.s.login(email,'Qadam2026!')
        return u
    def student(self):return self.user('aruzhan@qadam.demo')
    def employer(self):return self.user('steppe@qadam.demo')
    def coordinator(self):return self.user('aitu@qadam.demo')
    def test_seed_counts_and_login_do_not_expose_secrets(self):
        token,u=self.s.login('aruzhan@qadam.demo','Qadam2026!')
        self.assertEqual(u['role'],'student');self.assertNotIn('password_hash',u)
        self.assertEqual(self.s.authenticate(token)['id'],u['id'])
        self.assertEqual(len(self.s.demo_accounts()),18)
        self.assertEqual(len(self.s.bootstrap(u)['jobs']),8)
    def test_wrong_password_and_revoked_session_are_rejected(self):
        with self.assertRaises(Problem): self.s.login('aruzhan@qadam.demo','wrong')
        token,u=self.s.login('aruzhan@qadam.demo','Qadam2026!')
        self.s.logout(token)
        with self.assertRaises(Problem):self.s.authenticate(token)
    def test_registration_cannot_escalate_role_and_duplicate_email_fails(self):
        token,u=self.s.register({'name':'Test Person','email':'new@example.test','password':'Password123!','university':'AITU','role':'employer'})
        self.assertEqual(u['role'],'student')
        with self.assertRaises(Problem):self.s.register({'name':'Other','email':'NEW@example.test','password':'Password123!','university':'AITU'})
    def test_users_have_scoped_records(self):
        emp=self.employer();boot=self.s.bootstrap(emp)
        self.assertTrue(boot['applications'])
        self.assertTrue(all(a['employer_id']==emp['id'] for a in boot['applications']))
        stu=self.student();self.assertTrue(all(a['student_id']==stu['id'] for a in self.s.bootstrap(stu)['applications']))
        coord=self.coordinator();self.assertTrue(all(a['university']=='AITU' for a in self.s.bootstrap(coord)['applications']))
    def test_application_snapshots_duplicates_and_full_workflow(self):
        stu=self.student();emp=self.employer();coord=self.coordinator()
        job=next(j for j in self.s.bootstrap(stu)['jobs'] if j['code']=='data')
        a=self.s.apply(stu,job['id'],'Please review my dashboard project.')
        self.assertEqual(a['match']['score'],67)
        with self.assertRaises(Problem):self.s.apply(stu,job['id'],'duplicate')
        self.s.update_profile(stu,{'name':'Changed','city':'Astana','skills':['Python','SQL','Excel'],'evidence':'Updated project','portfolio':''})
        a=self.s.get_application(stu,a['id'])
        self.assertEqual(a['snapshot']['name'],'Aruzhan Saparova')
        self.assertEqual(a['match']['score'],67)
        with self.assertRaises(Problem):self.s.transition(coord,a['id'],'Confirmed','')
        self.s.transition(emp,a['id'],'Offered','Offer for the data team')
        with self.assertRaises(Problem):self.s.transition(coord,a['id'],'Confirmed','')
        self.s.transition(stu,a['id'],'Accepted','Accepted')
        final=self.s.transition(coord,a['id'],'Confirmed','Start date and both parties checked')
        self.assertEqual(final['status'],'Confirmed')
        self.assertEqual(len(final['history']),4)
    def test_cross_account_application_and_job_access_is_blocked(self):
        stu=self.student();emp=self.employer();other=self.user('ornek@qadam.demo')
        job=next(j for j in self.s.bootstrap(stu)['jobs'] if j['code']=='data')
        a=self.s.apply(stu,job['id'],'Evidence included')
        with self.assertRaises(Problem):self.s.transition(other,a['id'],'Offered','')
        with self.assertRaises(Problem):self.s.get_application(self.user('dias@qadam.demo'),a['id'])
        with self.assertRaises(Problem):self.s.get_application(self.user('iitu@qadam.demo'),a['id'])
        with self.assertRaises(Problem):self.s.save_job(other,{'active':False},job['id'])
    def test_job_creation_closure_and_bookmark_persist(self):
        emp=self.employer();stu=self.student()
        job=self.s.save_job(emp,{'title':'Analytics Intern','city':'Astana','mode':'Remote','duration':'8 weeks','stipend':'120,000 KZT / month','description':'Build dashboards using sample data.','skills':['SQL','Excel']})
        self.assertEqual(job['employer_id'],emp['id'])
        self.assertTrue(self.s.bookmark(stu,job['id'])['saved'])
        self.assertIn(job['id'],self.s.bootstrap(stu)['bookmarks'])
        self.s.save_job(emp,{'active':False},job['id'])
        saved_job=next(j for j in self.s.bootstrap(stu)['jobs'] if j['id']==job['id'])
        self.assertFalse(saved_job['active'])
        with self.assertRaises(Problem):self.s.apply(stu,job['id'],'Closed vacancy')
        self.assertFalse(self.s.bookmark(stu,job['id'])['saved'])
        self.assertNotIn(job['id'],[j['id'] for j in self.s.bootstrap(stu)['jobs']])
    def test_profile_role_fields_ignored_and_url_validation(self):
        stu=self.student()
        result=self.s.update_profile(stu,{'name':'Safe Student','city':'Astana','skills':['SQL'],'evidence':'SQL project','portfolio':'https://example.com/project','role':'coordinator','university':'IITU'})
        self.assertEqual(result['role'],'student');self.assertEqual(result['university'],'AITU')
        with self.assertRaises(Problem):self.s.update_profile(stu,{'portfolio':'javascript:alert(1)'})
    def test_notification_and_csv_ownership(self):
        stu=self.student();emp=self.employer();coord=self.coordinator()
        job=next(j for j in self.s.bootstrap(stu)['jobs'] if j['code']=='data')
        a=self.s.apply(stu,job['id'],'New application')
        self.assertTrue(any(n['title']=='New application' for n in self.s.bootstrap(emp)['notifications']))
        self.s.read_notifications(emp)
        self.assertTrue(all(n['is_read'] for n in self.s.bootstrap(emp)['notifications']))
        csv=self.s.export_csv(coord)
        self.assertIn('application_id',csv);self.assertNotIn('IITU',csv)
        with self.assertRaises(Problem):self.s.export_csv(stu)
    def test_restart_does_not_reseed_or_lose_new_user(self):
        self.s.register({'name':'Persistent User','email':'persist@example.test','password':'Password123!','university':'AITU'})
        self.s.close();initialize(self.path);self.s=Store(self.path)
        token,u=self.s.login('persist@example.test','Password123!')
        self.assertEqual(u['name'],'Persistent User');self.assertEqual(len(self.s.demo_accounts()),18)

if __name__=='__main__':unittest.main()
