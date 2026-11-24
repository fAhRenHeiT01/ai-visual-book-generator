"""Source-versioned decisions in the same SQLite DB as session snapshots."""
import sqlite3


class MetricDecisionRepository:
    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS metric_decisions (
                session_id TEXT NOT NULL, page_id TEXT NOT NULL, metric_id TEXT NOT NULL,
                action TEXT NOT NULL CHECK(action IN ('approve', 'redact')),
                PRIMARY KEY(session_id, page_id, metric_id))''')

    def load(self, session_id):
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute('SELECT page_id, metric_id, action FROM metric_decisions WHERE session_id=?', (session_id,)).fetchall()
        return {(page_id, metric_id): action for page_id, metric_id, action in rows}

    def save(self, session_id, page_id, metric_id, action):
        with sqlite3.connect(self.path) as connection:
            # The snapshot read can race deletion. Check ownership in this same
            # write statement so stale requests cannot resurrect orphan records.
            connection.execute('''INSERT INTO metric_decisions
                SELECT ?, ?, ?, ? WHERE EXISTS (SELECT 1 FROM sessions WHERE session_id=?)
                ON CONFLICT(session_id, page_id, metric_id) DO UPDATE SET action=excluded.action''',
                (session_id, page_id, metric_id, action, session_id))
