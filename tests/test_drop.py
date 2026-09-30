"""End-to-end tests for drop: a real server on a free port, temp database and storage."""
import base64, hashlib, http.client, json, os, secrets, socket, sqlite3, subprocess, sys, tempfile, time, unittest, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DROP = os.path.join(ROOT, "server", "drop")

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

class DropTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="drop-test-")
        cls.port = free_port()
        cls.env = dict(os.environ, DROP_DB=f"{cls.tmp}/drop.db", DROP_FILES=f"{cls.tmp}/files", DROP_INBOX=f"{cls.tmp}/inbox",
                       DROP_STATIC=os.path.join(ROOT, "static"), DROP_LISTEN=f"127.0.0.1:{cls.port}", DROP_BASE="https://example.test",
                       DROP_CERT="/nonexistent", DROP_GRACE="900")
        for d in ("files", "inbox"): os.makedirs(f"{cls.tmp}/{d}")
        cls.srv = subprocess.Popen([sys.executable, DROP, "serve"], env=cls.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for _ in range(50):
            try: socket.create_connection(("127.0.0.1", cls.port), 0.2).close(); break
            except OSError: time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.srv.terminate(); cls.srv.wait()
        subprocess.run(["rm", "-rf", cls.tmp])

    # helpers
    def cli(self, *args):
        r = subprocess.run([sys.executable, DROP, *args], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr); return r.stdout

    def cli_json(self, *args): return json.loads(self.cli(*args, "--json"))

    def add(self, data=b"hello world\n", *opts, name="hello.txt"):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as f: f.write(data)
        return self.cli_json("add", path, *opts)

    def req(self, method, url, body=None, ip="198.51.100.7", headers=None):
        path = urllib.parse.urlsplit(url).path
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"X-Real-IP": ip, "User-Agent": "drop-test"}; h.update(headers or {})
        if isinstance(body, dict): body = urllib.parse.urlencode(body); h["Content-Type"] = "application/x-www-form-urlencoded"
        c.request(method, path, body=body, headers=h); r = c.getresponse(); data = r.read(); c.close()
        return r.status, dict(r.getheaders()), data

    # tests
    def test_preview_does_not_consume_and_post_does(self):
        r = self.add()
        for _ in range(3): self.assertEqual(self.req("GET", r["url"])[0], 200)
        st, h, _ = self.req("POST", r["url"])
        self.assertEqual(st, 200)
        self.assertEqual(h["X-Accel-Redirect"], f"/_files/{r['file_id']}/hello.txt")
        self.assertIn("hello.txt", h["Content-Disposition"])
        self.assertEqual(h["Cache-Control"], "no-store")

    def test_retry_window_same_ip_only(self):
        r = self.add()
        self.assertEqual(self.req("POST", r["url"], ip="203.0.113.1")[0], 200)
        self.assertEqual(self.req("POST", r["url"], ip="203.0.113.1")[0], 200)     # retry from the same IP
        self.assertEqual(self.req("POST", r["url"], ip="203.0.113.99")[0], 404)    # anyone else: gone
        self.assertEqual(self.req("GET", r["url"], ip="203.0.113.99")[0], 404)
        results = [e["result"] for e in json.loads(self.cli("events", "--since", "0", "--json")) if e["link"] == r["link_id"]]
        self.assertEqual(results.count("download"), 1); self.assertIn("retry", results)

    def test_retry_window_expires(self):
        r = self.add()
        self.assertEqual(self.req("POST", r["url"])[0], 200)
        sqlite3.connect(self.env["DROP_DB"]).execute("UPDATE links SET grace_until = 1 WHERE hash LIKE ?", (r["link_id"] + "%",)).connection.commit()
        self.assertEqual(self.req("POST", r["url"])[0], 404)

    def test_multiple_uses(self):
        r = self.add(b"x", "--uses", "2")
        self.assertEqual(self.req("POST", r["url"], ip="192.0.2.1")[0], 200)
        self.assertEqual(self.req("POST", r["url"], ip="192.0.2.2")[0], 200)
        self.assertEqual(self.req("POST", r["url"], ip="192.0.2.3")[0], 404)

    def test_expired(self):
        r = self.add()
        sqlite3.connect(self.env["DROP_DB"]).execute("UPDATE links SET expires = 1 WHERE hash LIKE ?", (r["link_id"] + "%",)).connection.commit()
        self.assertEqual(self.req("GET", r["url"])[0], 404); self.assertEqual(self.req("POST", r["url"])[0], 404)

    def test_unknown_token_and_bad_paths(self):
        self.assertEqual(self.req("GET", "/d/" + secrets.token_urlsafe(32))[0], 404)
        self.assertEqual(self.req("GET", "/d/short")[0], 404)
        self.assertEqual(self.req("GET", "/etc/passwd")[0], 404)
        self.assertEqual(self.req("HEAD", "/d/" + secrets.token_urlsafe(32))[0], 405)

    def test_passphrase_and_lockout(self):
        r = self.add(b"secret", "--pass")
        self.assertRegex(r["passphrase"], r"^[a-z2-9]{4}-[a-z2-9]{4}-[a-z2-9]{4}$")
        st, _, page = self.req("GET", r["url"]); self.assertIn(b'type="password"', page)
        self.assertEqual(self.req("POST", r["url"], {})[0], 403)
        for _ in range(3): self.assertEqual(self.req("POST", r["url"], {"pass": "nope"})[0], 403)
        self.assertEqual(self.req("POST", r["url"], {"pass": "nope"})[0], 403)    # 5th wrong attempt locks
        self.assertEqual(self.req("POST", r["url"], {"pass": r["passphrase"]})[0], 404)
        r2 = self.add(b"secret", "--pass")
        self.assertEqual(self.req("POST", r2["url"], {"pass": r2["passphrase"]})[0], 200)

    def test_encrypted_file_page_and_format(self):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        plain = os.urandom(5000); key = AESGCM.generate_key(bit_length=256); nonce = os.urandom(12)
        r = self.add(nonce + AESGCM(key).encrypt(nonce, plain, None), "--encrypted", name="abc.bin")
        st, h, page = self.req("GET", r["url"])
        self.assertIn(b'data-mode="decrypt"', page); self.assertIn(b'src="/assets/drop.js"', page)
        self.assertIn("script-src 'self'", h["Content-Security-Policy"])
        st, h, _ = self.req("POST", r["url"], headers={"X-Drop-Api": "1"})
        self.assertEqual(st, 200); self.assertIn("encrypted.bin", h["Content-Disposition"])
        # what drop.js does with the stored bytes and the fragment
        with open(os.path.join(self.env["DROP_FILES"], r["file_id"], "abc.bin"), "rb") as f: blob = f.read()
        self.assertEqual(AESGCM(key).decrypt(blob[:12], blob[12:], None), plain)
        self.assertEqual(self.req("GET", "/assets/drop.js")[0], 200)

    def test_api_error_codes(self):
        r = self.add(b"p", "--pass")
        self.assertEqual(self.req("POST", r["url"], {"pass": "x"}, headers={"X-Drop-Api": "1"})[0], 403)
        self.assertEqual(self.req("POST", "/d/" + secrets.token_urlsafe(32), headers={"X-Drop-Api": "1"})[0], 404)

    def test_upload_request(self):
        r = self.cli_json("request", "--max-size", "10")
        self.assertEqual(self.req("GET", r["url"])[0], 200)
        st, _, body = self.req("PUT", r["url"], b"x" * 20, headers={"X-Filename": "big.bin"})
        self.assertEqual(st, 413)
        st, _, body = self.req("PUT", r["url"], b"12345", headers={"X-Filename": urllib.parse.quote("../../evil name.txt")})
        self.assertEqual(st, 200, body); info = json.loads(body)
        self.assertEqual(info["name"], "evil name.txt"); self.assertEqual(info["sha256"], hashlib.sha256(b"12345").hexdigest())
        inbox = self.cli_json("inbox")
        item = [i for i in inbox if i["name"] == "evil name.txt"][0]
        self.assertTrue(os.path.isfile(os.path.join(self.env["DROP_INBOX"], item["id"], "evil name.txt")))
        self.assertEqual(self.req("PUT", r["url"], b"again", headers={"X-Filename": "a"})[0], 404)   # used up

    def test_upload_passphrase(self):
        r = self.cli_json("request", "--pass")
        self.assertEqual(self.req("PUT", r["url"], b"abc", headers={"X-Filename": "a.txt", "X-Drop-Pass": "wrong"})[0], 403)
        self.assertEqual(self.req("PUT", r["url"], b"abc", headers={"X-Filename": "a.txt", "X-Drop-Pass": r["passphrase"]})[0], 200)

    def test_revoke(self):
        r = self.add()
        self.cli("revoke", r["link_id"])
        self.assertEqual(self.req("GET", r["url"])[0], 404)

    def test_gc_removes_only_dead_files(self):
        dead = self.add(b"dead", name="dead.txt"); alive = self.add(b"alive", name="alive.txt")
        con = sqlite3.connect(self.env["DROP_DB"])
        con.execute("UPDATE links SET expires = 1000 WHERE file_id = ?", (dead["file_id"],)); con.commit()
        out = self.cli("gc", "--keep-days", "3")
        self.assertIn("removed", out)
        self.assertFalse(os.path.exists(os.path.join(self.env["DROP_FILES"], dead["file_id"])))
        self.assertTrue(os.path.exists(os.path.join(self.env["DROP_FILES"], alive["file_id"])))
        self.assertEqual(self.req("GET", alive["url"])[0], 200)

    def test_status_and_events(self):
        s = self.cli_json("status")
        for k in ("active_links", "files", "inbox", "last_event", "cert_days"): self.assertIn(k, s)
        r = self.add(); self.req("POST", r["url"])
        ev = json.loads(self.cli("events", "--since", str(s["last_event"]), "--json"))
        self.assertIn("download", [e["result"] for e in ev])
        self.assertEqual([e for e in ev if e["result"] == "download"][0]["name"], "hello.txt")

class MigrationTest(unittest.TestCase):
    def test_v01_database_is_migrated(self):
        tmp = tempfile.mkdtemp(prefix="drop-mig-")
        db = f"{tmp}/drop.db"; con = sqlite3.connect(db)
        con.executescript("""
          CREATE TABLE files (id TEXT PRIMARY KEY, name TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL, added INTEGER NOT NULL);
          CREATE TABLE links (hash TEXT PRIMARY KEY, file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
              uses_left INTEGER NOT NULL, expires INTEGER NOT NULL, note TEXT, created INTEGER NOT NULL, last_used INTEGER);
          CREATE TABLE events (ts INTEGER NOT NULL, link TEXT, file_id TEXT, ip TEXT, result TEXT, ua TEXT);
          INSERT INTO files VALUES ('0123456789abcdef', 'old.zip', 3, 'x', 1);
          INSERT INTO links VALUES ('aa', '0123456789abcdef', 1, 9999999999, 'n', 1, NULL);""")
        con.commit(); con.close()
        env = dict(os.environ, DROP_DB=db, DROP_FILES=f"{tmp}/f", DROP_INBOX=f"{tmp}/i")
        out = subprocess.run([sys.executable, DROP, "list", "--json"], env=env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        links = json.loads(out.stdout)["files"][0]["links"]
        self.assertEqual(links[0]["state"], "1 left")
        cols = [r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(links)")]
        for c in ("pass_hash", "fails", "grace_ip", "grace_until"): self.assertIn(c, cols)
        subprocess.run(["rm", "-rf", tmp])

if __name__ == "__main__":
    unittest.main(verbosity=2)
