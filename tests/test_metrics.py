import unittest
from metrics import summarize, classify, measure_batch, normalize_job, in_scope, extract_events, match_event

def job(result='SUCCESS', start=1000, duration=2000, url='j/1/', **kw):
    return dict(url=url, result=result, start_ms=start, duration_ms=duration, end_ms=start+duration, building=False, **kw)

class MetricsTest(unittest.TestCase):
    def test_percentile_inc(self):
        self.assertEqual(summarize([0, 100, 200, 300]), {'n':4,'mean':150,'p90':270})
        self.assertEqual(summarize([123])['p90'],123)
        self.assertIsNone(summarize([])['mean'])
    def test_trigger_success_does_not_override_child_failure(self):
        self.assertEqual(classify(job(),[job('FAILURE')],True),'failure')
    def test_all_children_required(self):
        self.assertEqual(classify(job(),[job()],True),'success')
        self.assertEqual(classify(job(),[job()],False),'incomplete')
        self.assertEqual(classify(job(),[],True),'incomplete')
    def test_running_and_aborted(self):
        j=job();j['building']=True
        self.assertEqual(classify(job(),[j],True),'running')
        self.assertEqual(classify(job(),[job('ABORTED')],True),'failure')
    def test_parallel_e2e_uses_latest_completion(self):
        b=measure_batch(job(),[job(start=1500,duration=5000)],500,True)
        self.assertEqual(b['e2e_ms'],6000)
        self.assertTrue(b['eligible'])
    def test_missing_request_and_cancellation_excluded(self):
        b=measure_batch(job(),[job()],None,True)
        self.assertIsNone(b['e2e_ms'])
        self.assertFalse(b['eligible'])
        self.assertFalse(measure_batch(job(),[job('ABORTED')],500,True)['eligible'])
    def test_queue_is_not_zero_when_missing(self):
        j=normalize_job({'url':'j/1/','timestamp':10000,'duration':1000,'result':'SUCCESS','actions':[]})
        self.assertIsNone(j['queue_ms'])
        j=normalize_job({'url':'j/1/','timestamp':10000,'duration':1000,'result':'SUCCESS','actions':[{'waitingTimeMillis':100,'blockedTimeMillis':200,'buildableTimeMillis':300}]})
        self.assertEqual(j['total_ms'],1600)
        self.assertEqual(j['scheduled_ms'],9400)
    def test_scope_includes_all_three_states(self):
        for state in ['open','closed','merged']:
            self.assertTrue(in_scope({'base':{'ref':'master'},'created_at':'2026-09-01T00:00:00+08:00','state':state},0,9999999999999))
        self.assertFalse(in_scope({'base':{'ref':'other'},'created_at':'2026-09-01T00:00:00+08:00'},0,9999999999999))
    def test_retest_exact_discussion_and_ambiguous_push(self):
        p={'number':1,'created_at':'2026-09-01T00:00:00+08:00'}
        comments=[{'id':1,'discussion_id':'abc','body':'/retest','created_at':'2026-09-01T00:01:00+08:00'}]
        ev=extract_events(p,[],comments)
        self.assertEqual(match_event({'eventType':'note','commentID':'abc'},ev)['kind'],'retest')
        self.assertIsNone(match_event({'eventType':'merge_request','eventAction':'update','jobTriggerTime':'2026-09-01T00:01:00+08:00'},ev))
    def test_create_sha_comes_from_platform_creation_log(self):
        p={'number':1,'created_at':'2026-09-01T00:00:00+08:00'}
        logs=[{'action':'commit','content':'create merge request[project id:8744708, iid:1, commit_id:53d1bfb67c0d51c02642d8788fb1bfc57613f7ca], virtual merging success'}]
        ev=extract_events(p,logs,[{'id':1,'body':'/retest','created_at':'2026-09-01T00:01:00+08:00'}])
        self.assertEqual(ev[0]['sha'],'53d1bfb67c0d51c02642d8788fb1bfc57613f7ca')
        self.assertEqual(ev[1]['sha'],ev[0]['sha'])

if __name__=='__main__': unittest.main()
