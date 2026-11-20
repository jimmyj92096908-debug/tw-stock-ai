"""Offline tests for bounded LINE production cutover and rollback.

All HTTP calls are simulated. No real LINE token, webhook, or user data.
"""
import importlib.util
import json
import unittest
from pathlib import Path
from urllib.error import HTTPError

source=Path(__file__).resolve().parents[1] / 'scripts' / 'line_temporary_cutover.py'
spec=importlib.util.spec_from_file_location('cutover', source)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Reply:
    def __init__(self, url, obj):
        self.status=200
        self.url=url
        self.obj=obj
    def __enter__(self):
        return self
    def __exit__(self,*args):
        return None
    def geturl(self):
        return self.url
    def read(self,*args):
        return json.dumps(self.obj).encode('utf8')


class FakeOpener:
    def __init__(self):
        self.endpoint=m.LEGACY_URL
        self.active=True
        self.calls=[]
        self.fail_after_switch=False
        self.gate_enabled=True

    def open(self,req,timeout):
        self.calls.append((req.get_method(),req.full_url))
        if req.full_url.endswith('/health'):
            return Reply(req.full_url,{})
        if req.full_url == m.CANDIDATE_URL and req.get_method() == 'POST':
            raise HTTPError(req.full_url,401 if self.gate_enabled else 503,'fail closed',{},None)
        if req.full_url != m.LINE_API:
            raise AssertionError(req.full_url)
        if req.get_method()=='GET':
            return Reply(req.full_url,{'endpoint':self.endpoint,'active':self.active})
        if req.get_method()=='PUT':
            self.endpoint=json.loads(req.data)['endpoint']
            if self.fail_after_switch and self.endpoint==m.CANDIDATE_URL:
                raise ValueError('pretend failure after PUT accepted')
            return Reply(req.full_url,{})
        raise AssertionError(req.get_method())


class TrialTests(unittest.TestCase):
    def test_success_restores_original(self):
        f=FakeOpener()
        m.trial('placeholder',60,opener=f,sleep=lambda _:None)
        self.assertEqual(f.endpoint,m.LEGACY_URL)
        self.assertEqual(sum(1 for verb,url in f.calls if verb=='PUT'),2)

    def test_put_accepts_then_transport_fails_still_restores(self):
        f=FakeOpener()
        f.fail_after_switch=True
        with self.assertRaises(RuntimeError):
            m.trial('placeholder',60,opener=f,sleep=lambda _:None)
        self.assertEqual(f.endpoint,m.LEGACY_URL)

    def test_original_missing_refuses_cutover(self):
        f=FakeOpener()
        f.endpoint='https://other.example.com/'
        with self.assertRaises(RuntimeError):
            m.trial('placeholder',60,opener=f,sleep=lambda _:None)
        self.assertEqual(sum(1 for verb,url in f.calls if verb=='PUT'),0)

    def test_restore_unknown_destination_refuses_write(self):
        f=FakeOpener()
        f.endpoint='https://other.example.com/'
        with self.assertRaises(RuntimeError):
            m.restore('placeholder',opener=f,sleep=lambda _:None)
        self.assertEqual(sum(1 for verb,url in f.calls if verb=='PUT'),0)

    def test_disabled_candidate_blocks_switch(self):
        f=FakeOpener()
        f.gate_enabled=False
        with self.assertRaises(RuntimeError):
            m.trial('placeholder',60,opener=f,sleep=lambda _:None)
        self.assertEqual(sum(1 for verb,url in f.calls if verb=='PUT'),0)

    def test_window_over_four_minutes_blocked(self):
        f=FakeOpener()
        with self.assertRaises(RuntimeError):
            m.trial('placeholder',900,opener=f,sleep=lambda _:None)
        self.assertEqual(len(f.calls),0)


if __name__=='__main__':
    unittest.main()
