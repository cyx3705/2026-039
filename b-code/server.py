"""Local experiment viewer. python server.py"""
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from urllib.parse import urlsplit

import probe

RUN_LOCK = threading.Lock()
CONTROL_LOCK = threading.Lock()
CURRENT_CANCEL = None
LIVE_CONDITION = threading.Condition()
LIVE = {"status": "idle", "text": "", "round": None, "run_id": None, "version": 0}


def publish(progress):
    with LIVE_CONDITION:
        LIVE.update(progress)
        LIVE["version"] += 1
        LIVE_CONDITION.notify_all()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(probe.ROOT), **kwargs)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/thought-stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            previous = None
            try:
                while True:
                    with LIVE_CONDITION:
                        LIVE_CONDITION.wait_for(lambda: previous is None or LIVE["version"] != previous["version"], timeout=10)
                        current = dict(LIVE)
                    if previous is not None and current["version"] == previous["version"]:
                        self.wfile.write(b": heartbeat\n\n")
                    else:
                        same = (previous is not None and current["run_id"] == previous["run_id"]
                                and current["round"] == previous["round"]
                                and current["text"].startswith(previous["text"]))
                        event = {**current, "kind": "delta" if same else "snapshot",
                                 "text": current["text"][len(previous["text"]):] if same else current["text"]}
                        self.wfile.write(("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode("utf-8"))
                        previous = current
                    self.wfile.flush()
                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            return
        if path in ("/runs/latest.json", "/state"):
            try:
                # Close the file before network transmission, so snapshot replacement
                # never waits for a browser to finish downloading a large audit.
                content = (probe.ROOT / "runs" / "latest.json").read_bytes()
            except FileNotFoundError:
                self.send_error(404)
                return
            if path == "/state":
                document = json.loads(content)
                for step in document["steps"]:
                    audit = step["audit"]
                    step["audit"] = {key: audit[key] for key in
                                     ("ranked", "seconds", "prompt_tokens", "action_table", "execution_mode", "decoded_output", "predicted_tokens", "thinking", "reasoning_tokens", "reasoning_budget_hit") if key in audit}
                content = json.dumps(document, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)
            return
        super().do_GET()

    def do_POST(self):
        global CURRENT_CANCEL
        if self.path == "/stop":
            with CONTROL_LOCK:
                token = CURRENT_CANCEL
                if token:
                    token.stop()
            self.send_response(202)
            self.end_headers()
            self.wfile.write(b'{"stopping":true}')
            return
        if self.path != "/run":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size < 4096:
                raise ValueError("Invalid request length")
            cfg = json.loads(self.rfile.read(size))
            dims, k, rounds, seed = (int(cfg[key]) for key in ("dims", "k", "rounds", "seed"))
            mode = cfg.get("mode", "valley")
            regret = cfg.get("regret", True)
            landscape = cfg.get("landscape", "ripple")
            prompt_layout = cfg.get("prompt_layout", "suffix")
            execution_mode = cfg.get("execution_mode", "vector")
            action_space = cfg.get("action_space", "variable")
            max_step = cfg.get("max_step", 2)
            if action_space not in ("fixed", "variable") or type(max_step) is not int or not 1 <= max_step <= 10:
                raise ValueError("Invalid action space or max_step (integer 1 to 10 required)")
            thinking = cfg.get("thinking", True)
            if not isinstance(thinking, bool):
                raise ValueError("thinking must be boolean")
            if execution_mode not in ("single", "vector"):
                raise ValueError("execution_mode must be single or vector")
            if prompt_layout not in ("prefix", "suffix"):
                raise ValueError("prompt_layout must be prefix or suffix")
            if landscape not in ("ripple", "parabola"):
                raise ValueError("landscape must be ripple or parabola")
            if not isinstance(regret, bool):
                raise ValueError("regret must be boolean")
            if mode not in ("valley", "mountain"):
                raise ValueError("mode must be valley or mountain")
            if not 1 <= k <= dims <= 5 or not 1 <= rounds <= 100:
                raise ValueError("Require 1 <= k <= dims <= 5, 1 <= rounds <= 100")
            if not RUN_LOCK.acquire(blocking=False):
                self.send_error(409, "Experiment already running")
                return
            args = argparse.Namespace(model_url="http://127.0.0.1:18765", dims=dims,
                                      k=k, rounds=rounds, warmup=4, step=0.2, seed=seed, mode=mode, regret=regret, landscape=landscape, prompt_layout=prompt_layout, execution_mode=execution_mode, thinking=thinking, action_space=action_space, max_step=max_step)
            token = probe.Cancellation()
            with CONTROL_LOCK:
                CURRENT_CANCEL = token

            def work():
                global CURRENT_CANCEL
                try:
                    probe.run(args, cancel=token, on_progress=publish)
                except Exception as exc:
                    print(exc, flush=True)
                finally:
                    with CONTROL_LOCK:
                        if CURRENT_CANCEL is token:
                            CURRENT_CANCEL = None
                    RUN_LOCK.release()

            threading.Thread(target=work, daemon=True).start()
            self.send_response(202)
            self.end_headers()
            self.wfile.write(b'{"started":true}')
        except (ValueError, KeyError) as exc:
            self.send_error(400, str(exc))


if __name__ == "__main__":
    print("http://127.0.0.1:18766", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 18766), Handler).serve_forever()
