"""share client: the watcher's counter and `share seen` (regression: seen was overwritten on the next poll)."""
import importlib.machinery, importlib.util, json, os, tempfile, types, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_share(cache):
    loader = importlib.machinery.SourceFileLoader("share_client", os.path.join(ROOT, "client", "share"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("share_client", loader)); loader.exec_module(mod)
    mod.CACHE = cache; mod.STATUS = os.path.join(cache, "status.json"); mod.STATE = os.path.join(cache, "state.json")
    return mod

class WatchTest(unittest.TestCase):
    def setUp(self):
        self.cache = tempfile.mkdtemp(prefix="share-test-")
        self.m = load_share(self.cache)
        self.server = {"last_event": 10, "events": []}; self.notes = []
        def drop(*args, json_out=False):
            if args[0] == "status": return {"version": "t", "cert_days": 80, "files": 0, "active_links": 0, "active_requests": 0,
                                            "inbox": 0, "downloads_24h": 0, "last_event": self.server["last_event"]}
            since = int(args[args.index("--since") + 1])
            return [e for e in self.server["events"] if e["id"] > since]
        self.m.drop = drop
        self.m.notify = lambda title, body, urgency="normal": self.notes.append((title, body))

    def add_event(self, result, name="f.txt"):
        self.server["last_event"] += 1
        self.server["events"].append({"id": self.server["last_event"], "result": result, "name": name, "note": None,
                                      "file_id": "0123456789abcdef", "link": "abcdef1234", "ip": "192.0.2.1"})

    def unseen(self): return json.load(open(self.m.STATE)).get("unseen", 0) if os.path.exists(self.m.STATE) else 0

    def test_first_poll_does_not_replay_history(self):
        self.add_event("download"); self.m.poll_once()
        self.assertEqual(self.notes, []); self.assertEqual(self.unseen(), 0)

    def test_seen_survives_the_next_poll(self):
        self.m.poll_once(); self.add_event("download"); self.add_event("upload"); self.m.poll_once()
        self.assertEqual(self.unseen(), 2); self.assertEqual(len(self.notes), 2)
        self.m.cmd_seen(types.SimpleNamespace()); self.assertEqual(self.unseen(), 0)
        self.m.poll_once(); self.m.poll_once()
        self.assertEqual(self.unseen(), 0); self.assertEqual(len(self.notes), 2)      # no repeats either
        self.add_event("download"); self.m.poll_once()
        self.assertEqual(self.unseen(), 1); self.assertEqual(len(self.notes), 3)

    def test_quiet_events_do_not_count(self):
        self.m.poll_once(); self.add_event("viewed"); self.add_event("refused"); self.m.poll_once()
        self.assertEqual(self.unseen(), 0); self.assertEqual(self.notes, [])

    def test_deleted_file_is_named(self):
        self.m.poll_once(); self.add_event("download", name=None); self.m.poll_once()
        self.assertIn("(deleted)", self.notes[0][1])

if __name__ == "__main__":
    unittest.main(verbosity=2)
