"""Single output-position policy: standard library only, local llama.cpp server."""
import argparse
import json
import math
import itertools
from pathlib import Path
import random
import time
import urllib.request
import threading
import socket

ROOT = Path(__file__).resolve().parent
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
ACTION_SYMBOLS = "+-↑↓前后内外增减"
CONTEXT = 32768
HISTORY_FIELDS = (
    "History is chronological. Each record contains x and height after an observation. "
    "source=warmup records are random pre-model observations with decision=null. "
    "source=model records include the executed decision that produced that record's x: "
    "type is move, stay or undo; displacement is the actual coordinate displacement from the preceding record. "
    "For variable steps, use displacement for magnitudes; actions gives direction signs only. "
    "actions lists executed [axis,sign] primitives (empty for undo). "
)


class Cancelled(RuntimeError):
    pass


class Cancellation:
    def __init__(self):
        self.event = threading.Event()
        self.response = None
        self.lock = threading.Lock()

    def check(self):
        if self.event.is_set():
            raise Cancelled("Stopped by user; no pending action executed")

    def attach(self, response):
        with self.lock:
            self.response = response
        self.check()

    def detach(self):
        with self.lock:
            self.response = None

    def stop(self):
        self.event.set()
        with self.lock:
            response = self.response
            if response is not None:
                try:
                    response.fp.raw._sock.shutdown(socket.SHUT_RDWR)
                except (AttributeError, OSError):
                    pass


def api(base, path, body=None, cancel=None):
    if cancel:
        cancel.check()
    req = urllib.request.Request(base + path, data=None if body is None else
                                 json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with HTTP.open(req, timeout=600) as response:
        try:
            if cancel:
                cancel.attach(response)
            result = json.load(response)
            if cancel:
                cancel.check()
            return result
        finally:
            if cancel:
                cancel.detach()


def stream_completion(base, body, on_text=None, cancel=None):
    """Consume llama.cpp SSE; retain the same full response audit as non-streaming."""
    request = urllib.request.Request(base + "/completion",
        data=json.dumps({**body, "stream": True}).encode(),
        headers={"Content-Type": "application/json"})
    chunks, final = [], None
    if cancel:
        cancel.check()
    try:
        with HTTP.open(request, timeout=600) as response:
            try:
                if cancel:
                    cancel.attach(response)
                for line in response:
                    if cancel:
                        cancel.check()
                    if not line.startswith(b"data:"):
                        continue
                    data = line[5:].strip()
                    if data == b"[DONE]":
                        break
                    event = json.loads(data)
                    if event.get("error"):
                        raise RuntimeError(str(event["error"]))
                    chunk = event.get("content", "")
                    chunks.append(chunk)
                    if chunk and on_text:
                        on_text(chunk)
                    if event.get("stop"):
                        final = event
                if cancel:
                    cancel.check()
            finally:
                if cancel:
                    cancel.detach()
    except Exception:
        if cancel:
            cancel.check()
        raise
    if final is None:
        raise RuntimeError("Thinking stream ended without final event; no action executed")
    return {**final, "content": "".join(chunks)}


def height(x, target):
    # Hidden coupled, multimodal landscape; the viewer uses exactly this formula.
    d = [v - t for v, t in zip(x, target)]
    return sum(-0.18 * v * v + 1.2 * math.cos(2.3 * v)
               + 0.45 * math.sin(1.4 * v + 0.9 * d[(i + 1) % len(d)])
               for i, v in enumerate(d))


def gradient(x, target):
    d = [v - t for v, t in zip(x, target)]
    return [-0.36 * v - 2.76 * math.sin(2.3 * v)
            + 0.63 * math.cos(1.4 * v + 0.9 * d[(i + 1) % len(d)])
            + 0.405 * math.cos(1.4 * d[(i - 1) % len(d)] + 0.9 * v)
            for i, v in enumerate(d)]


def advance(x, actions, step):
    result = x.copy()
    for axis, sign in actions:
        result[axis] += sign * step
    return result


def apply_decision(x, actions, step, undo_stack, decision, displacement=None):
    if decision == "stay":
        if actions or (displacement is not None and any(displacement)):
            raise ValueError("Stay must have zero displacement")
        return x.copy()
    if decision == "undo":
        if not undo_stack:
            raise ValueError("No committed move to undo")
        if actions:
            raise ValueError("Undo cannot be combined with movement")
        return undo_stack.pop()
    if decision != "move" or not actions:
        raise ValueError("Expected a movement or undo decision")
    undo_stack.append(x.copy())
    if displacement is not None:
        return [v + delta for v, delta in zip(x, displacement)]
    return advance(x, actions, step)


def variable_grammar(dims, max_step, undo=False):
    """Bound each coordinate independently without enumerating whole vectors."""
    if type(max_step) is not int or not 1 <= max_step <= 10:
        raise ValueError("Variable max_step must be an integer from 1 to 10")
    inner = " | ".join(json.dumps(str(n)) for n in range(max_step))
    array_rule = '"[" ' + ' "," '.join(['scalar'] * dims) + ' "]"'
    root = array_rule + (' | "\\\"undo\\\""' if undo else '')
    return ('root ::= ' + root + '\nscalar ::= "-"? magnitude\n'
            'magnitude ::= (' + inner + ') ("." [0-9]{1,3})? | '
            + json.dumps(str(max_step)) + ' ("." "0"{1,3})?')


def choose(base, history, dims, k, step, goal="maximize", regret=False, undo_target=None,
           swap_labels=False, prompt_layout="suffix", label_rng=None, action_symbols=None):
    if goal not in ("maximize", "minimize"):
        raise ValueError("goal must be maximize or minimize")
    if prompt_layout not in ("prefix", "suffix"):
        raise ValueError("prompt_layout must be prefix or suffix")
    symbols = ACTION_SYMBOLS if action_symbols is None else action_symbols
    if not 1 <= dims <= len(symbols) // 2:
        raise ValueError(f"Action symbols support 1..{len(symbols)//2} dimensions")
    labels = symbols[:2 * dims]
    table = {label: [i // 2, 1 if i % 2 == 0 else -1]
             for i, label in enumerate(labels)}
    if swap_labels:
        table = {label: [axis, -sign] for label, (axis, sign) in table.items()}
    if label_rng is not None:
        shuffled = list(table)
        label_rng.shuffle(shuffled)
        table = dict(zip(shuffled, table.values()))
    undo_available = regret and undo_target is not None
    if undo_available:
        labels += "!"
        table["!"] = "undo"
    regret_instruction = ""
    if regret:
        regret_instruction = (
            "You may regret a previous move. Label ! means UNDO: return exactly to "
            "the state before the most recent un-undone movement, keeping all observations. "
            "If ! has the highest probability, execute ONLY undo, with no movement. "
            "Otherwise ignore ! and select the movement actions. Undo consumes one round. "
            "There is no automatic rollback based on height. "
            + ("Undo is available. Raw undo destination coordinates: " + json.dumps(undo_target)
               if undo_available else "Undo is unavailable: no model movement to undo yet.")
            + "\n"
        )
    rules = (
        f"{goal.capitalize()} the unknown scalar height using raw observations. "
        "Each observation contains x (coordinates) and height. " + HISTORY_FIELDS +
        f"One action changes one coordinate by sign * {step}. "
        "Output one action label. Its next-token distribution will select "
        f"{k} distinct-axis actions, applied simultaneously, without lookahead. "
        + regret_instruction +
        "Infer a useful direction from the full history. "
        "No objective formula or gradient is available. Labels map to [axis,sign]:\n"
        + json.dumps(table, separators=(",", ":"))
    )
    raw = "Raw history:\n" + json.dumps(history, separators=(",", ":"), allow_nan=False)
    instruction = rules + "\n" + raw if prompt_layout == "prefix" else raw + "\n" + rules
    # Explicit Qwen3 non-thinking chat template; no generated reasoning tokens.
    prompt = ("<|im_start|>user\n" + instruction +
              " /no_think<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n")
    tokens = api(base, "/tokenize", {"content": prompt, "add_special": True})["tokens"]
    if len(tokens) >= CONTEXT:
        raise ValueError(f"Full raw history needs {len(tokens)} tokens; limit {CONTEXT - 1}. "
                         "Stopped without truncation or summarization.")
    # Every legal primitive must be exactly one model token.
    for label in labels:
        ids = api(base, "/tokenize", {"content": label, "add_special": False})["tokens"]
        if len(ids) != 1:
            raise ValueError(f"Action label {label!r} is not one token")
    payload = {"prompt": tokens, "n_predict": 1, "cache_prompt": False,
               "temperature": 1, "top_k": 0, "top_p": 1, "min_p": 0,
               "repeat_penalty": 1, "n_probs": len(labels),
               "post_sampling_probs": True,
               "grammar": ('root ::= [' + labels + ']' if action_symbols is not None else
                           'root ::= ' + ' | '.join(json.dumps(label, ensure_ascii=False) for label in labels))}
    begin = time.perf_counter()
    response = api(base, "/completion", payload)
    duration = time.perf_counter() - begin
    if response.get("tokens_predicted") != 1:
        raise RuntimeError("Expected exactly one output token")
    timing = response.get("timings", {})
    if response.get("truncated") or timing.get("cache_n") != 0 or timing.get("prompt_n") != len(tokens):
        raise RuntimeError("Expected full uncached prompt evaluation without truncation")
    probs = response["completion_probabilities"][0]
    # llama.cpp renamed these fields across releases.
    candidates = probs.get("top_probs", probs.get("probs", []))
    ranked = []
    for item in candidates:
        label = item.get("token", item.get("tok_str", ""))
        p = item.get("prob", item.get("probability", 0))
        if label in table:
            ranked.append({"label": label, "p": p, "action": table[label]})
    ranked.sort(key=lambda entry: -entry["p"])
    if not ranked:
        raise RuntimeError("No legal action probabilities returned")
    selected, axes = [], set()
    decision = "undo" if ranked[0]["action"] == "undo" else "move"
    for entry in ranked if decision == "move" else []:
        if entry["action"] == "undo":
            continue
        axis = entry["action"][0]
        if axis not in axes:
            selected.append(entry["action"])
            axes.add(axis)
        if len(selected) == k:
            break
    if decision == "move" and len(selected) != k:
        raise RuntimeError(f"Insufficient legal probability entries: {probs}")
    return selected, {"prompt": prompt, "request": payload, "response": response,
                      "ranked": ranked, "seconds": duration,
                      "decision": decision, "undo_available": undo_available,
                      "prompt_layout": prompt_layout,
                      "action_table": table, "shuffle_labels": label_rng is not None,
                      "prompt_tokens": len(tokens)}


def choose_vector(base, history, dims, k, step, goal="maximize", regret=False,
                  undo_target=None, prompt_layout="suffix", thinking=False, thinking_budget=16384,
                  on_thought=None, cancel=None, action_space="fixed", max_step=2):
    """Generate one complete joint displacement autoregressively, then execute once."""
    if goal not in ("maximize", "minimize") or prompt_layout not in ("prefix", "suffix"):
        raise ValueError("Invalid goal or prompt layout")
    if not 1 <= k <= dims <= 5 or not math.isfinite(step) or step <= 0:
        raise ValueError("Invalid dimensions, action count, or step")
    undo_available = regret and undo_target is not None
    if action_space not in ("fixed", "variable"):
        raise ValueError("Invalid action space")
    variable = action_space == "variable"
    if variable:
        grammar = variable_grammar(dims, max_step, undo_available)
    vectors = []
    for axes in itertools.combinations(range(dims), k):
        for signs in itertools.product([-1, 1], repeat=k):
            vector = [0] * dims
            for axis, sign in zip(axes, signs):
                vector[axis] = sign * step
            vectors.append(json.dumps(vector, separators=(",", ":")))
    if undo_available:
        vectors.append(json.dumps("undo"))
    if not variable:
        grammar = "root ::= " + " | ".join(json.dumps(v) for v in vectors)
    movement_rules = (
        f"Choose each coordinate displacement independently between {-max_step} and {max_step}, "
        "using at most 3 decimal places. You may change any number of axes simultaneously, "
        "including all axes, and choose different magnitudes per axis. Zero means no change; "
        "an all-zero vector means stay at the current position. "
        if variable else
        f"Exactly {k} coordinates must change by either {step} or {-step}; all others must be 0. "
    )
    rules = (f"{goal.capitalize()} the unknown scalar height using raw observations. "
             "Each observation contains x (coordinates) and height. " + HISTORY_FIELDS +
             f"Return a JSON displacement array of length {dims}, in coordinate order. "
             + movement_rules +
             "The complete vector will be applied simultaneously once: next_x = current_x + displacement. "
             "Use the full history to choose a useful direction. The last observation is the current state. "
             "No objective formula or gradient is available. Output only the JSON array, without explanations.")
    if regret:
        rules += (' Alternatively output the JSON string "undo" to undo the last un-undone movement; '
                  'this consumes a round and preserves all observations. Raw undo destination: '
                  + json.dumps(undo_target) if undo_available else
                  ' Undo is unavailable: there is no model movement to undo yet.')
    raw = "Raw history:\n" + json.dumps(history, separators=(",", ":"), allow_nan=False)
    instruction = rules + "\n" + raw if prompt_layout == "prefix" else raw + "\n" + rules
    prompt = ("<|im_start|>user\n" + instruction +
              (" Reasoning effort: low. Make a brief assessment from the observations, then give the final action. "
               "Avoid exhaustive calculations, repeatedly checking the same evidence, or exploring many alternatives. "
               "Finish once you have enough evidence for one action. /think<|im_end|>\n<|im_start|>assistant\n<think>\n" if thinking else
               " /no_think<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"))
    reasoning_audit = None
    reasoning_budget_hit = False
    begin = time.perf_counter()
    if thinking:
        think_tokens = api(base, "/tokenize", {"content": prompt, "add_special": True})["tokens"]
        # Reserve final action tokens and room for the inserted closing marker.
        budget = min(thinking_budget, CONTEXT - len(think_tokens) - 128 - 32)
        if budget < 1:
            raise ValueError("Full history leaves no thinking/output budget; no truncation performed")
        think_request = {"prompt": think_tokens, "n_predict": budget, "cache_prompt": False,
                         "temperature": 0, "top_k": 0, "top_p": 1, "min_p": 0,
                         "repeat_penalty": 1, "stop": ["</think>"]}
        think_request["stream"] = True
        think_response = stream_completion(base, think_request, on_text=on_thought, cancel=cancel)
        timing = think_response.get("timings", {})
        if (think_response.get("truncated") or timing.get("cache_n") != 0
                or timing.get("prompt_n") != len(think_tokens)):
            raise RuntimeError("Expected full uncached thinking prompt without truncation")
        reasoning_budget_hit = (think_response.get("stopping_word") != "</think>"
                                and think_response.get("stop_type") == "limit")
        if think_response.get("stopping_word") != "</think>" and not reasoning_budget_hit:
            error = RuntimeError("Thinking ended unexpectedly; no action executed")
            error.failed_audit = {"prompt": prompt, "request": think_request, "response": think_response}
            raise error
        reasoning_audit = {"prompt": prompt, "request": think_request, "response": think_response,
                           "budget_hit": reasoning_budget_hit,
                           "closure": "budget_forced" if reasoning_budget_hit else "model"}
        prompt += think_response["content"] + "</think>\n\n"
    tokens = api(base, "/tokenize", {"content": prompt, "add_special": True})["tokens"]
    if len(tokens) + 128 > CONTEXT:
        raise ValueError("Full history plus vector output exceeds context; no truncation performed")
    request = {"prompt": tokens, "n_predict": 128, "cache_prompt": False,
               "temperature": 0, "top_k": 0, "top_p": 1, "min_p": 0,
               "repeat_penalty": 1, "n_probs": 0,
               "grammar": grammar}
    response = api(base, "/completion", request, cancel=cancel)
    timing = response.get("timings", {})
    if response.get("truncated") or timing.get("cache_n") != 0 or timing.get("prompt_n") != len(tokens):
        raise RuntimeError("Expected full uncached prompt without truncation")
    if response.get("stop_type") == "limit":
        raise RuntimeError("Vector generation reached token limit; incomplete output not executed")
    decoded = json.loads(response["content"])
    if decoded == "undo" and undo_available:
        actions, decision = [], "undo"
    else:
        if (not isinstance(decoded, list) or len(decoded) != dims
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in decoded)
                or (variable and any(abs(v) > max_step or abs(v * 1000 - round(v * 1000)) > 1e-8 for v in decoded))
                or (not variable and (any(v not in (0, step, -step) for v in decoded)
                                      or sum(v != 0 for v in decoded) != k))):
            raise RuntimeError("Invalid displacement vector; output not executed")
        actions = [[axis, 1 if value > 0 else -1] for axis, value in enumerate(decoded) if value != 0]
        decision = "move" if actions else "stay"
    return actions, {"prompt": prompt, "request": request, "response": response,
                     "seconds": time.perf_counter() - begin, "prompt_tokens": len(tokens),
                     "predicted_tokens": response.get("tokens_predicted"),
                     "execution_mode": "vector", "decoded_output": decoded,
                     "action_space": action_space, "displacement": decoded if decision != "undo" else None,
                     "thinking": thinking, "reasoning_audit": reasoning_audit,
                     "reasoning_effort": "low_prompt" if thinking else None,
                     "reasoning_budget_hit": reasoning_budget_hit,
                     "reasoning_tokens": think_response.get("tokens_predicted", 0) if thinking else 0,
                     "decision": decision, "undo_available": undo_available,
                     "prompt_layout": prompt_layout, "ranked": [], "action_table": {}}


def run(args, cancel=None, on_progress=None):
    if not 1 <= args.dims <= 5 or not 1 <= args.k <= args.dims:
        raise ValueError("Require 1 <= k <= dims <= 5")
    if args.step <= 0 or args.rounds < 1 or args.warmup < 2:
        raise ValueError("step > 0, rounds >= 1, warmup >= 2 required")
    execution_mode = getattr(args, "execution_mode", "single")
    if execution_mode not in ("single", "vector"):
        raise ValueError("execution_mode must be single or vector")
    mode = getattr(args, "mode", "mountain")
    if mode not in ("mountain", "valley"):
        raise ValueError("mode must be mountain or valley")
    goal = "minimize" if mode == "valley" else "maximize"
    terrain_sign = -1 if mode == "valley" else 1
    landscape = getattr(args, "landscape", "ripple")
    if landscape not in ("ripple", "parabola"):
        raise ValueError("landscape must be ripple or parabola")
    def value(x, target):
        return terrain_sign * (-sum((v-t)**2 for v,t in zip(x,target))
                               if landscape == "parabola" else height(x, target))
    rng = random.Random(args.seed)
    # Independent stream: relabeling cannot change the environment or random baseline.
    label_rng = None  # Direction symbols retain their meaning; no anonymous labels.
    target = [rng.uniform(-2, 2) for _ in range(args.dims)]
    initial = [rng.uniform(-3, 3) for _ in range(args.dims)]
    # Shared random observed trajectory; never sorted, normalized, rounded or projected.
    x, history = initial.copy(), []
    for i in range(args.warmup):
        history.append({"x": x.copy(), "height": value(x, target),
                        "source": "warmup", "decision": None})
        if i < args.warmup - 1:
            axes = rng.sample(range(args.dims), args.k)
            x = advance(x, [(a, rng.choice([-1, 1])) for a in axes], args.step)
    random_x, oracle_x = x.copy(), x.copy()
    undo_stack = []
    regret = getattr(args, "regret", True)
    objective = ("parabola-valley-v1" if mode == "valley" else "parabola-mountain-v1") if landscape == "parabola" else ("coupled-valley-v1" if mode == "valley" else "coupled-ripple-v1")
    document = {"config": vars(args), "objective": objective, "history_schema": "executed-decisions-v1",
                "goal": goal,
                "target_evaluation_only": target, "warmup": history.copy(),
                "steps": [], "status": "running"}
    output = ROOT / "runs" / f"run-{time.time_ns()}.json"
    document["run_id"] = output.stem
    output.parent.mkdir(exist_ok=True)

    def save():
        text = json.dumps(document, ensure_ascii=False, indent=2)
        output.write_text(text, encoding="utf-8")
        temporary = ROOT / "runs" / "latest.tmp"
        temporary.write_text(text, encoding="utf-8")
        # Windows may briefly hold the previous snapshot while the viewer reads it.
        for attempt in range(40):
            try:
                temporary.replace(ROOT / "runs" / "latest.json")
                break
            except PermissionError:
                if attempt == 39:
                    raise
                time.sleep(0.05)

    save()
    try:
        for i in range(args.rounds):
            if cancel:
                cancel.check()
            live = {"run_id": document["run_id"], "round": i + 1, "text": "", "status": "thinking"}
            def progress(chunk="", status=None):
                live["text"] += chunk
                if status:
                    live["status"] = status
                if on_progress:
                    on_progress(dict(live))
            progress(status="thinking" if getattr(args, "thinking", False) and execution_mode == "vector" else "action")
            policy = choose_vector if execution_mode == "vector" else choose
            extra = {"thinking": getattr(args, "thinking", False), "on_thought": progress,
                     "cancel": cancel, "action_space": getattr(args, "action_space", "fixed"),
                     "max_step": getattr(args, "max_step", 2)} if execution_mode == "vector" else {}
            actions, audit = policy(args.model_url, history, args.dims, args.k, args.step, goal,
                                   regret=regret, undo_target=undo_stack[-1] if undo_stack else None,
                                   prompt_layout=getattr(args, "prompt_layout", "suffix"), **extra)
            if cancel:
                cancel.check()
            progress(status="complete")
            previous_x = x.copy()
            x = apply_decision(x, actions, args.step, undo_stack, audit["decision"],
                               displacement=audit.get("displacement"))
            random_actions = [(a, rng.choice([-1, 1])) for a in
                              rng.sample(range(args.dims), args.k)]
            random_x = advance(random_x, random_actions, args.step)
            # Oracle comparator only: true gradient of the same multimodal landscape.
            base_grad = [-2*(v-t) for v,t in zip(oracle_x,target)] if landscape == "parabola" else gradient(oracle_x, target)
            grad = [terrain_sign * v for v in base_grad]
            axes = sorted(range(args.dims), key=lambda a: -abs(grad[a]))[:args.k]
            direction = -1 if goal == "minimize" else 1
            oracle_actions = [(a, direction * (1 if grad[a] > 0 else -1)) for a in axes]
            oracle_x = advance(oracle_x, oracle_actions, args.step)
            displacement = [0] * args.dims
            if audit["decision"] == "undo":
                displacement = [new - old for new, old in zip(x, previous_x)]
            elif audit.get("displacement") is not None:
                displacement = audit["displacement"]
            else:
                for axis, sign in actions:
                    displacement[axis] = sign * args.step
            observation = {"x": x.copy(), "height": value(x, target), "source": "model",
                           "decision": {"type": audit["decision"], "actions": actions,
                                        "displacement": displacement}}
            history.append(observation)
            document["steps"].append({"round": i + 1, **observation,
                                      "decision": audit["decision"], "previous_x": previous_x,
                                      "undo_depth": len(undo_stack),
                                      "actions": actions, "random_height": value(random_x, target),
                                      "oracle_height": value(oracle_x, target), "audit": audit})
            save()
            print(f"{i + 1}: model={observation['height']:.6f} "
                  f"random={value(random_x, target):.6f} "
                  f"oracle={value(oracle_x, target):.6f} tokens={audit['prompt_tokens']}", flush=True)
        document["status"] = "complete"
    except Exception as exc:
        stopped = isinstance(exc, Cancelled) or (cancel is not None and cancel.event.is_set())
        document["status"] = "stopped" if stopped else "error"
        document["error"] = "Stopped by user; no pending action executed" if stopped else str(exc)
        if 'live' in locals():
            progress(status=document["status"])
            document["pending_thought"] = dict(live)
        if hasattr(exc, "failed_audit"):
            document["failed_audit"] = exc.failed_audit
        raise
    finally:
        save()
        print(output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-url", default="http://127.0.0.1:18765")
    parser.add_argument("--dims", type=int, default=5)
    parser.add_argument("--k", type=int, default=2)
    parser.add_argument("--rounds", type=int, default=40)
    parser.add_argument("--warmup", type=int, default=4)
    parser.add_argument("--step", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=39)
    parser.add_argument("--mode", choices=["mountain", "valley"], default="valley")
    parser.add_argument("--regret", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--landscape", choices=["ripple", "parabola"], default="ripple")
    parser.add_argument("--prompt-layout", choices=["prefix", "suffix"], default="suffix")
    parser.add_argument("--execution-mode", choices=["single", "vector"], default="vector")
    parser.add_argument("--thinking", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--action-space", choices=["fixed", "variable"], default="variable")
    parser.add_argument("--max-step", type=int, default=2)
    run(parser.parse_args())
