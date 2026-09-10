"""Repository-isolated persistence and atomic public snapshots."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')), 'utf-8')
    tmp.replace(path)


def save_database(snapshot, path=None):
    path = Path(path or ROOT / 'data/efficiency.sqlite')
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as db, db:
        columns = [r[1] for r in db.execute('PRAGMA table_info(prs)')]
        if columns and 'repository' not in columns:
            backup = path.with_name(path.stem + '-before-multi-' + datetime.now().strftime('%Y%m%d%H%M%S%f') + '.sqlite')
            with closing(sqlite3.connect(backup)) as dest:
                db.backup(dest)
            # DDL and row copy are transactional; preserve the original snapshot.
            db.execute('BEGIN')
            for table in ['prs', 'events', 'batches']:
                db.execute(f'ALTER TABLE {table} RENAME TO legacy_{table}')
            create_tables(db)
            db.execute("INSERT INTO prs SELECT 'openeuler/ubs-engine',number,payload FROM legacy_prs")
            db.execute("INSERT INTO events SELECT 'openeuler/ubs-engine',pr,id,payload FROM legacy_events")
            db.execute("INSERT INTO batches SELECT url,'openeuler/ubs-engine',pr,payload FROM legacy_batches")
            db.execute("INSERT OR REPLACE INTO metadata SELECT 'openeuler/ubs-engine',payload FROM metadata WHERE key='snapshot'")
            for table in ['prs', 'events', 'batches']:
                db.execute(f'DROP TABLE legacy_{table}')
        else:
            create_tables(db)
        repo = snapshot['meta']['repository']
        for table in ['prs', 'events', 'batches']:
            db.execute(f'DELETE FROM {table} WHERE repository=?', (repo,))
        for p in snapshot['prs']:
            payload = {k: v for k, v in p.items() if k not in ['events', 'batches']}
            payload['repository'] = repo
            db.execute('INSERT INTO prs VALUES (?,?,?)', (repo, p['number'], json.dumps(payload, ensure_ascii=False)))
            for e in p['events']:
                db.execute('INSERT OR REPLACE INTO events VALUES (?,?,?,?)', (repo, p['number'], e['id'], json.dumps(e, ensure_ascii=False)))
            for b in p['batches']:
                db.execute('INSERT INTO batches VALUES (?,?,?,?)', (b['url'], repo, p['number'], json.dumps(b, ensure_ascii=False)))
                for j in [b['trigger']] + b['children']:
                    db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?)', (j['url'], json.dumps(j, ensure_ascii=False)))
        db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (repo, json.dumps(snapshot['meta'], ensure_ascii=False)))


def create_tables(db):
    for sql in [
        'CREATE TABLE IF NOT EXISTS prs(repository TEXT,number INTEGER,payload TEXT NOT NULL,PRIMARY KEY(repository,number))',
        'CREATE TABLE IF NOT EXISTS events(repository TEXT,pr INTEGER,id TEXT,payload TEXT NOT NULL,PRIMARY KEY(repository,pr,id))',
        'CREATE TABLE IF NOT EXISTS batches(url TEXT PRIMARY KEY,repository TEXT,pr INTEGER,payload TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS jobs(url TEXT PRIMARY KEY,payload TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,payload TEXT NOT NULL)',
    ]:
        db.execute(sql)


def publish_snapshot(snapshot):
    name = snapshot['meta']['repository'].split('/')[-1]
    for base in ['data', 'web/data']:
        atomic_json(ROOT / base / 'repos' / (name + '.json'), snapshot)
        if name == 'ubs-engine':
            atomic_json(ROOT / base / 'snapshot.json', snapshot)


def publish_index(entries, start_ms, end_ms):
    value = dict(schema_version=3, start_ms=start_ms, end_ms=end_ms,
                 generated_at=datetime.now(timezone.utc).isoformat(), repositories=entries)
    for base in ['data', 'web/data']:
        atomic_json(ROOT / base / 'repositories.json', value)
