"""Private, durable question records. No experimental or literature metadata writes."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import secrets
import sqlite3
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


class HistoryStore:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS questions (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL REFERENCES sessions(id),
                    request_key TEXT NOT NULL,
                    question TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('processing','answered','refused','failed','interrupted')),
                    created_at TEXT NOT NULL, completed_at TEXT,
                    latency_ms INTEGER, reason_code TEXT, error_status INTEGER,
                    result_json TEXT, configuration_json TEXT NOT NULL,
                    UNIQUE(owner_id, request_key)
                );
                CREATE INDEX IF NOT EXISTS questions_owner_time ON questions(owner_id, created_at DESC, id DESC);
                CREATE TABLE IF NOT EXISTS feedback (
                    question_id TEXT PRIMARY KEY REFERENCES questions(id),
                    rating TEXT NOT NULL CHECK(rating IN ('helpful','inaccurate')),
                    tags_json TEXT NOT NULL, note TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                PRAGMA user_version=1;
            ''')

    def recover(self):
        with self.connection() as conn:
            conn.execute("UPDATE questions SET status='interrupted', reason_code='service_restarted', completed_at=? WHERE status='processing'", (now(),))

    def session(self, token: str | None):
        digest = sha256(token.encode()).hexdigest() if token and len(token) <= 128 else None
        with self.connection() as conn:
            if digest and conn.execute('SELECT 1 FROM sessions WHERE id=?', (digest,)).fetchone():
                return digest, None
            token = secrets.token_urlsafe(32)
            digest = sha256(token.encode()).hexdigest()
            conn.execute('INSERT INTO sessions VALUES (?,?)', (digest, now()))
        return digest, token

    def create(self, owner: str, request_key: str, question: str, configuration: dict):
        with self.connection() as conn:
            conn.execute('INSERT OR IGNORE INTO questions (id,owner_id,request_key,question,status,created_at,configuration_json) VALUES (?,?,?,?,?,?,?)',
                         (uuid4().hex, owner, request_key, question, 'processing', now(), json.dumps(configuration, ensure_ascii=False)))
            row = conn.execute('SELECT * FROM questions WHERE owner_id=? AND request_key=?', (owner, request_key)).fetchone()
            if row['question'] != question:
                raise ValueError('request_key_conflict')
            return self.decode(row)

    def by_key(self, owner: str, key: str):
        with self.connection() as conn:
            row = conn.execute('SELECT * FROM questions WHERE owner_id=? AND request_key=?', (owner, key)).fetchone()
            return self.decode(row) if row else None

    def complete(self, record_id: str, result: dict, latency_ms: int):
        with self.connection() as conn:
            conn.execute("UPDATE questions SET status=?,result_json=?,configuration_json=?,completed_at=?,latency_ms=?,reason_code=?,error_status=? WHERE id=? AND status='processing'",
                         (result['status'], json.dumps(result, ensure_ascii=False), json.dumps(result.get('configuration', {}), ensure_ascii=False), now(), latency_ms, result.get('reason_code'), result.get('error_status'), record_id))

    def fail(self, record_id: str, reason: str, status: int, latency_ms: int):
        with self.connection() as conn:
            conn.execute("UPDATE questions SET status='failed',reason_code=?,error_status=?,completed_at=?,latency_ms=? WHERE id=? AND status='processing'",
                         (reason, status, now(), latency_ms, record_id))

    @staticmethod
    def decode(row):
        item = dict(row)
        item.pop('owner_id', None)
        item.pop('request_key', None)
        result_json = item.pop('result_json')
        item['result'] = json.loads(result_json) if result_json else None
        item['configuration'] = json.loads(item.pop('configuration_json'))
        feedback = item.pop('feedback_json', None)
        item['feedback'] = json.loads(feedback) if feedback else None
        return item

    def get(self, owner: str, record_id: str):
        with self.connection() as conn:
            row = conn.execute('SELECT * FROM questions WHERE id=? AND owner_id=?', (record_id, owner)).fetchone()
            if not row:
                return None
            item = self.decode(row)
            feedback = conn.execute('SELECT rating,tags_json,note,updated_at FROM feedback WHERE question_id=?', (record_id,)).fetchone()
            if feedback:
                item['feedback'] = dict(feedback)
                item['feedback']['tags'] = json.loads(item['feedback'].pop('tags_json'))
            return item

    def list(self, owner: str, page: int, page_size: int, search: str):
        # Literal substring search: %, _ and SQL-looking strings are ordinary text.
        where = 'owner_id=? AND instr(lower(question),lower(?))>0'
        with self.connection() as conn:
            total = conn.execute(f'SELECT count(*) FROM questions WHERE {where}', (owner, search)).fetchone()[0]
            rows = conn.execute(f'SELECT id,question,status,created_at,completed_at,latency_ms,reason_code FROM questions WHERE {where} ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',
                                (owner, search, page_size, (page - 1) * page_size)).fetchall()
        return {'data': [dict(row) for row in rows], 'pagination': {'page': page, 'page_size': page_size, 'total': total, 'total_pages': (total + page_size - 1) // page_size}}

    def feedback(self, owner: str, record_id: str, rating: str, tags: list[str], note: str):
        with self.connection() as conn:
            row = conn.execute('SELECT status FROM questions WHERE id=? AND owner_id=?', (record_id, owner)).fetchone()
            if not row:
                return None
            if row['status'] not in ('answered', 'refused'):
                raise ValueError('unfinished')
            updated = now()
            conn.execute('INSERT INTO feedback VALUES (?,?,?,?,?) ON CONFLICT(question_id) DO UPDATE SET rating=excluded.rating,tags_json=excluded.tags_json,note=excluded.note,updated_at=excluded.updated_at',
                         (record_id, rating, json.dumps(tags), note, updated))
        return {'rating': rating, 'tags': tags, 'note': note, 'updated_at': updated}

    def export(self, owner: str | None = None):
        # A read transaction gives this streamed export a stable snapshot, including feedback.
        with self.connection() as conn:
            conn.execute('BEGIN')
            rows = conn.execute('SELECT * FROM questions' + (' WHERE owner_id=?' if owner else '') + ' ORDER BY created_at,id', (owner,) if owner else ())
            for row in rows:
                item = self.decode(row)
                feedback = conn.execute('SELECT rating,tags_json,note,updated_at FROM feedback WHERE question_id=?', (item['id'],)).fetchone()
                if feedback:
                    item['feedback'] = dict(feedback)
                    item['feedback']['tags'] = json.loads(item['feedback'].pop('tags_json'))
                yield json.dumps({'schema_version': 1, **item}, ensure_ascii=False) + '\n'
