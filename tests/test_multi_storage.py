from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from repository_store import save_database


def snapshot(name, number=1, build=1):
    repo = 'openeuler/' + name
    url = f'https://ci.example/job/{name}/{build}/'
    return {'meta': {'repository': repo}, 'prs': [{'number': number, 'repository': repo,
        'title': name, 'metrics': {'e2e_ms': build}, 'events': [{'id': 'create'}],
        'batches': [{'url': url, 'trigger': {'url': url}, 'children': []}]}]}


class MultiStorageTests(unittest.TestCase):
    def test_same_pr_and_event_numbers_are_isolated_and_update_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.sqlite'
            engine, comm = snapshot('ubs-engine'), snapshot('ubs-comm')
            save_database(engine, path)
            save_database(comm, path)
            save_database(comm, path)
            save_database(snapshot('ubs-engine', build=2), path)
            with closing(sqlite3.connect(path)) as db, db:
                self.assertEqual(db.execute('select count(*) from prs').fetchone()[0], 2)
                self.assertEqual(db.execute('select count(*) from events').fetchone()[0], 2)
                self.assertEqual(db.execute('select count(*) from batches').fetchone()[0], 2)
                payload = db.execute('select payload from prs where repository=?', ('openeuler/ubs-comm',)).fetchone()[0]
                self.assertEqual(json.loads(payload)['metrics']['e2e_ms'], 1)
                self.assertEqual(db.execute('pragma integrity_check').fetchone()[0], 'ok')

    def test_legacy_migration_backs_up_and_preserves_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.sqlite'
            with closing(sqlite3.connect(path)) as db, db:
                for sql in ['create table prs(number integer primary key,payload text)',
                            'create table events(pr integer,id text,payload text,primary key(pr,id))',
                            'create table batches(url text primary key,pr integer,payload text)',
                            'create table jobs(url text primary key,payload text)',
                            'create table metadata(key text primary key,payload text)']:
                    db.execute(sql)
                db.execute('insert into prs values(1,?)', ('{"title":"legacy"}',))
                db.execute('insert into events values(1,"create","{}")')
                db.execute('insert into batches values("legacy-build",1,"{}")')
                db.execute('insert into metadata values("snapshot","{}")')
            save_database(snapshot('ubs-comm'), path)
            backups = list(Path(directory).glob('*-before-multi-*.sqlite'))
            self.assertEqual(len(backups), 1)
            with closing(sqlite3.connect(backups[0])) as db:
                self.assertNotIn('repository', [r[1] for r in db.execute('pragma table_info(prs)')])
                self.assertEqual(db.execute('select count(*) from prs').fetchone()[0], 1)
            with closing(sqlite3.connect(path)) as db, db:
                self.assertEqual(db.execute('select repository from batches where url="legacy-build"').fetchone()[0], 'openeuler/ubs-engine')
                self.assertEqual(db.execute('select count(*) from prs').fetchone()[0], 2)

    def test_shared_build_cannot_be_reassigned_to_another_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.sqlite'
            first, second = snapshot('ubs-engine'), snapshot('ubs-comm')
            second['prs'][0]['batches'] = first['prs'][0]['batches']
            save_database(first, path)
            with self.assertRaises(sqlite3.IntegrityError):
                save_database(second, path)
            with closing(sqlite3.connect(path)) as db, db:
                self.assertEqual(db.execute('select count(*) from prs').fetchone()[0], 1)
                self.assertEqual(db.execute('select repository from batches').fetchone()[0], 'openeuler/ubs-engine')


if __name__ == '__main__':
    unittest.main()
