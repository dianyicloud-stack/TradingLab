from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3,unittest
from contextlib import closing
from shared.storage.maintenance import compact_database
class CompactionTests(unittest.TestCase):
    def test_physical_release_preserves_rows_and_creates_no_backup(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent,prefix='space-test-') as tmp:
            root=Path(tmp);p=root/'owned.db'
            with closing(sqlite3.connect(p)) as db,db:
                db.execute('CREATE TABLE facts(id INTEGER PRIMARY KEY,payload BLOB)')
                db.executemany('INSERT INTO facts VALUES(?,?)',[(i,b'x'*4096) for i in range(256)])
                db.execute('DELETE FROM facts WHERE id>2')
            r=compact_database(root,p);self.assertGreater(r['released_bytes'],500000);self.assertTrue(r['logical_data_unchanged'])
            self.assertEqual([x.name for x in root.iterdir()],['owned.db'])
    def test_busy_database_is_not_compacted(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent,prefix='space-test-') as tmp:
            root=Path(tmp);p=root/'owned.db'
            with closing(sqlite3.connect(p)) as writer,writer:
                writer.execute('CREATE TABLE facts(id INTEGER PRIMARY KEY)');writer.commit();writer.execute('BEGIN IMMEDIATE')
                with self.assertRaises(sqlite3.OperationalError):compact_database(root,p)
if __name__=='__main__':unittest.main()
