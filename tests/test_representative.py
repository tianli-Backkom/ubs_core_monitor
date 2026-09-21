import unittest
from metrics import pr_metrics

class RepresentativeTest(unittest.TestCase):
    def batch(self,n,t,eligible=True,children=None):
        return dict(number=n,url=f"trigger/{n}",e2e_ms=t,eligible=eligible,children=children or [])
    def test_longest_and_tie(self):
        m=pr_metrics([self.batch(1,10),self.batch(2,30),self.batch(3,30),self.batch(4,90,False)])
        self.assertEqual(m['representative_batch_number'],3)
        self.assertEqual(m['e2e_ms'],30)
    def test_completed_cancelled_batch_represents_developer_wait(self):
        cancelled = self.batch(7470, 11_021_462, True)
        cancelled.update(status='failure', cancelled=True)
        m = pr_metrics([cancelled])
        self.assertEqual(m['representative_batch_number'], 7470)
        self.assertEqual(m['e2e_ms'], 11_021_462)

    def test_missing_task_does_not_fall_back(self):
        task=dict(kind='x86',url='x/1',association_valid=True,result='SUCCESS',building=False,total_ms=100,queue_ms=10,duration_ms=90)
        m=pr_metrics([self.batch(1,10,children=[task]),self.batch(2,30)])
        self.assertIsNone(m['x86']['total_ms'])
        self.assertIsNone(pr_metrics([])['e2e_ms'])
