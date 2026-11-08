from django.test import SimpleTestCase

from common.models import LogFinding


class LogFindingFingerprintTests(SimpleTestCase):
    def test_reworded_502_findings_share_one_fingerprint(self):
        titles = (
            '관리자 activity.json 502 Bad Gateway (1건)',
            '관리자 활동 API(/lab/admin/activity.json) 502 1건',
            '/lab/ 경로 502 Bad Gateway 2건',
            '/lab/ 및 /lab/admin/activity.json 에서 502 Bad Gateway 발생',
        )
        fingerprints = {LogFinding.make_fingerprint(title) for title in titles}
        self.assertEqual(len(fingerprints), 1)
        self.assertEqual(LogFinding.make_fingerprint('Bad Gateway'), fingerprints.pop())

    def test_upstream_statuses_and_application_500_stay_distinct(self):
        self.assertNotEqual(LogFinding.make_fingerprint('502 Bad Gateway'),
                            LogFinding.make_fingerprint('504 Gateway Timeout'))
        self.assertNotEqual(LogFinding.make_fingerprint('500 error at /foo/32/'),
                            LogFinding.make_fingerprint('500 error at /bar/45/'))
