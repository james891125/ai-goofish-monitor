"""Additive SQLite migration. Legacy data stays intact and is never scheduled."""
import json
from datetime import datetime, timedelta, timezone
from src.domain.models.shopee import ShopeeTask, Product, utc_now
from src.infrastructure.persistence.sqlite_connection import sqlite_connection, init_schema


class ShopeeRepository:
    def __init__(self, db_path=None):
        self.db_path = db_path
        with sqlite_connection(db_path) as conn:
            init_schema(conn)
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS shopee_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL,
                    deleted_at TEXT
                );
                CREATE TABLE IF NOT EXISTS shopee_imports (
                    product_id TEXT PRIMARY KEY, payload TEXT NOT NULL, imported_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS shopee_products (
                    task_id INTEGER NOT NULL, product_id TEXT NOT NULL, source TEXT NOT NULL,
                    payload TEXT NOT NULL, analysis TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                    is_new INTEGER NOT NULL, price_changed INTEGER NOT NULL,
                    PRIMARY KEY(task_id, source, product_id)
                );
                CREATE TABLE IF NOT EXISTS shopee_price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL,
                    source TEXT NOT NULL, product_id TEXT NOT NULL, price_twd REAL NOT NULL,
                    observed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS shopee_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL,
                    started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
                    found INTEGER NOT NULL DEFAULT 0, new_count INTEGER NOT NULL DEFAULT 0,
                    changed_count INTEGER NOT NULL DEFAULT 0, notified_count INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT, error_message TEXT
                );
                CREATE TABLE IF NOT EXISTS shopee_notifications (
                    task_id INTEGER NOT NULL, source TEXT NOT NULL, product_id TEXT NOT NULL,
                    price_twd REAL NOT NULL, attempted_at TEXT NOT NULL, status TEXT NOT NULL,
                    PRIMARY KEY(task_id, source, product_id, price_twd)
                );
                CREATE TABLE IF NOT EXISTS shopee_locks (
                    task_id INTEGER PRIMARY KEY, expires_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS shopee_history_product ON shopee_price_history(task_id, source, product_id, id);
                CREATE INDEX IF NOT EXISTS shopee_runs_task ON shopee_runs(task_id, id);
            ''')
            conn.execute("INSERT OR IGNORE INTO app_metadata VALUES ('migration:shopee_tw_v1','done')")
            conn.commit()

    def connection(self):
        return sqlite_connection(self.db_path)

    def tasks(self):
        with self.connection() as conn:
            return [ShopeeTask.model_validate_json(row['payload']).model_copy(update={'id': row['id']})
                    for row in conn.execute('SELECT * FROM shopee_tasks WHERE deleted_at IS NULL ORDER BY id')]

    def get_task(self, task_id):
        return next((task for task in self.tasks() if task.id == task_id), None)

    def save_task(self, task, task_id=None):
        task = task.model_copy(update={'id': task_id})
        with self.connection() as conn:
            if task_id is None:
                cursor = conn.execute('INSERT INTO shopee_tasks(payload) VALUES (?)', (task.model_dump_json(),))
                task_id = cursor.lastrowid
            else:
                cursor = conn.execute('UPDATE shopee_tasks SET payload=? WHERE id=? AND deleted_at IS NULL', (task.model_dump_json(), task_id))
                if not cursor.rowcount:
                    raise KeyError(task_id)
            conn.commit()
        return task.model_copy(update={'id': task_id})

    def delete_task(self, task_id):
        with self.connection() as conn:
            cursor = conn.execute('UPDATE shopee_tasks SET deleted_at=? WHERE id=? AND deleted_at IS NULL', (utc_now(), task_id))
            conn.commit()
            return bool(cursor.rowcount)

    def import_products(self, products):
        with self.connection() as conn:
            for product in products:
                conn.execute('INSERT INTO shopee_imports VALUES (?,?,?) ON CONFLICT(product_id) DO UPDATE SET payload=excluded.payload,imported_at=excluded.imported_at',
                             (product.product_id, product.model_dump_json(), utc_now()))
            conn.commit()
        return len({p.product_id for p in products})

    def imported_products(self):
        with self.connection() as conn:
            return [json.loads(row['payload']) for row in conn.execute('SELECT payload FROM shopee_imports ORDER BY product_id')]

    def observe(self, task_id, product: Product, analysis=None):
        now, source, pid = utc_now(), product.data_source, product.product_id
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            prior = conn.execute('SELECT * FROM shopee_products WHERE task_id=? AND source=? AND product_id=?', (task_id, source, pid)).fetchone()
            old_price = json.loads(prior['payload'])['price_twd'] if prior else None
            is_new, changed = prior is None, old_price is not None and old_price != product.price_twd
            old_analysis = json.loads(prior['analysis']) if prior and prior['analysis'] else None
            stored_analysis = analysis if analysis is not None else old_analysis
            conn.execute('''INSERT INTO shopee_products VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(task_id,source,product_id) DO UPDATE SET payload=excluded.payload,
                analysis=excluded.analysis,last_seen=excluded.last_seen,is_new=excluded.is_new,price_changed=excluded.price_changed''',
                         (task_id,pid,source,product.model_dump_json(),json.dumps(stored_analysis,ensure_ascii=False) if stored_analysis else None,
                          now,now,int(is_new),int(changed)))
            if is_new or changed:
                conn.execute('INSERT INTO shopee_price_history(task_id,source,product_id,price_twd,observed_at) VALUES (?,?,?,?,?)', (task_id,source,pid,product.price_twd,now))
            conn.commit()
        return dict(is_new=is_new, price_changed=changed, price_dropped=changed and product.price_twd < old_price, analysis=stored_analysis)

    def set_analysis(self, task_id, product, analysis):
        with self.connection() as conn:
            conn.execute('UPDATE shopee_products SET analysis=? WHERE task_id=? AND source=? AND product_id=?', (json.dumps(analysis,ensure_ascii=False),task_id,product.data_source,product.product_id))
            conn.commit()

    def products(self, task_id=None):
        query, args = 'SELECT * FROM shopee_products', ()
        if task_id is not None:
            query += ' WHERE task_id=?'; args=(task_id,)
        with self.connection() as conn:
            rows = conn.execute(query+' ORDER BY last_seen DESC LIMIT 2000',args)
            return [dict(json.loads(r['payload']),task_id=r['task_id'],analysis=json.loads(r['analysis']) if r['analysis'] else None,
                         first_seen=r['first_seen'],last_seen=r['last_seen'],is_new=bool(r['is_new']),price_changed=bool(r['price_changed'])) for r in rows]

    def history(self, product_id, task_id=None, source=None):
        query,args='SELECT * FROM shopee_price_history WHERE product_id=?',[product_id]
        if task_id is not None: query+=' AND task_id=?'; args.append(task_id)
        if source: query+=' AND source=?'; args.append(source)
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(query+' ORDER BY id DESC LIMIT 1000',args)]

    def start_run(self, task_id):
        with self.connection() as conn:
            cursor=conn.execute("INSERT INTO shopee_runs(task_id,started_at,status) VALUES (?,?,'running')",(task_id,utc_now()))
            conn.commit()
            return cursor.lastrowid

    def finish_run(self, run_id, *, status='completed', found=0, new_count=0, changed_count=0, notified_count=0, error_code=None, error_message=None):
        with self.connection() as conn:
            conn.execute('UPDATE shopee_runs SET finished_at=?,status=?,found=?,new_count=?,changed_count=?,notified_count=?,error_code=?,error_message=? WHERE id=?',
                         (utc_now(),status,found,new_count,changed_count,notified_count,error_code,error_message,run_id))
            conn.commit()

    def runs(self, task_id=None):
        query,args='SELECT * FROM shopee_runs',()
        if task_id is not None: query+=' WHERE task_id=?'; args=(task_id,)
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(query+' ORDER BY id DESC LIMIT 200',args)]

    def acquire(self, task_id):
        now=utc_now(); expiry=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('DELETE FROM shopee_locks WHERE expires_at<?',(now,))
            cursor=conn.execute('INSERT OR IGNORE INTO shopee_locks VALUES (?,?)',(task_id,expiry))
            conn.commit()
            return bool(cursor.rowcount)

    def release(self, task_id):
        with self.connection() as conn:
            conn.execute('DELETE FROM shopee_locks WHERE task_id=?',(task_id,)); conn.commit()

    def claim_notification(self, task_id, product, allow_price_drop):
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            rows=conn.execute('SELECT price_twd FROM shopee_notifications WHERE task_id=? AND source=? AND product_id=?',(task_id,product.data_source,product.product_id)).fetchall()
            if rows and (not allow_price_drop or product.price_twd >= min(row['price_twd'] for row in rows)):
                return False
            cursor=conn.execute("INSERT OR IGNORE INTO shopee_notifications VALUES (?,?,?,?,?,'attempted')",(task_id,product.data_source,product.product_id,product.price_twd,utc_now()))
            conn.commit()
            return bool(cursor.rowcount)

    def notification_result(self, task_id, product, success):
        with self.connection() as conn:
            conn.execute('UPDATE shopee_notifications SET status=? WHERE task_id=? AND source=? AND product_id=? AND price_twd=?',('sent' if success else 'failed_or_uncertain',task_id,product.data_source,product.product_id,product.price_twd))
            conn.commit()
