# -*- coding: utf-8 -*-
"""本番／下見：迷路10面をAIに解かせる（1回の実行＝10面・最大250操作）

  python run_experiment.py --mock --trials 1   APIなしで動作確認（でたらめに押す）
  python run_experiment.py --trials 1          下見（各社・各条件を1回ずつ）
  python run_experiment.py                     本番（common.TRIALS 回）

途中で止めても、log.jsonl に「ok」で残っている実行は飛ばして続きから走る。
1手ごとの記録は steps.jsonl に残す（考えた文とメモを後で読むため）。
各面の最初の画面は images/ に残す（図版用）。
"""
import argparse, json, os, random, sys, time
import common as cm

LOG = os.path.join(cm.HERE, "log.jsonl")
STEPS = os.path.join(cm.HERE, "steps.jsonl")
IMG = os.path.join(cm.HERE, "images")


def write(path, rec):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def run_job(provider, job_id, cond, trial, levels, mock):
    memory, history = "", []
    actions, bumps, bad, level_done, errors = 0, 0, 0, 0, 0
    tin_sum = tout_sum = 0
    served = None
    reached = []          # 各面を解いた時点の操作数
    for li, grid in enumerate(levels, start=1):
        maze = cm.Maze(grid)
        if not mock and trial == 1 and cond == "A":
            os.makedirs(IMG, exist_ok=True)
            open(os.path.join(IMG, f"level{li:02d}_start.png"), "wb").write(cm.png(maze))
        solved = False
        while actions < cm.MAX_ACTIONS and not solved:
            png = cm.png(maze) if cond in ("A", "B") else None
            user = cm.observation_text(cond, li, maze, memory, history[-cm.CONTEXT_STEPS:])
            if mock:
                k = random.choice(list(cm.DIRS))
                text, stop, served, tin, tout = json.dumps({"thought": "mock", "action": "press_key",
                                                              "action_input": k, "memory": ""}), "end", "mock", 1000, 50
            else:
                try:
                    text, stop, served, tin, tout = cm.call(provider, cm.body(provider, cond, cm.system_text(cond), user, png))
                    errors = 0
                except Exception as e:
                    errors += 1
                    write(LOG, {"time": cm.now(), "provider": provider, "job": job_id, "status": "error", "error": str(e)[:500]})
                    if errors >= 3:
                        return None
                    time.sleep(10)
                    continue
            tin_sum += tin or 0
            tout_sum += tout or 0
            actions += 1
            j = cm.parse_action(text)
            thought = (j or {}).get("thought", "")
            act, inp = (j or {}).get("action", ""), str((j or {}).get("action_input", ""))
            keyname = next((k for k in cm.DIRS if k.lower() in inp.lower()), None) if act in ("press_key", "hold_key") else None
            if j is None or keyname is None:
                bad += 1
                result = "no_effect"
            else:
                result = maze.move(keyname)
                if result == "blocked":
                    bumps += 1
            if j and j.get("memory"):
                memory = str(j["memory"])[:1500]
            history.append(f"step {actions}: {inp} | {str(thought)[:120]}")
            write(STEPS, {"time": cm.now(), "provider": provider, "job": job_id, "cond": cond, "trial": trial,
                          "level": li, "action_no": actions, "pos": list(maze.pos), "action": act, "input": inp,
                          "key": keyname, "result": result, "thought": thought, "memory": memory, "raw": text[:800]})
            if result == "goal":
                solved = True
                level_done = li
                reached.append(actions)
        if not solved:
            break
    rec = {"time": cm.now(), "provider": provider, "model": cm.MODELS[provider], "model_served": served,
           "job": job_id, "status": "ok", "cond": cond, "trial": trial,
           "levels_done": level_done, "actions": actions, "wall_bumps": bumps, "bad_outputs": bad,
           "reached_at": reached, "in_tokens": tin_sum, "out_tokens": tout_sum,
           "yen": round(cm.yen(provider, tin_sum, tout_sum), 1)}
    write(LOG, rec)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--trials", type=int, default=cm.TRIALS)
    ap.add_argument("--smoke", action="store_true", help="本物のAPIで3手だけ（疎通の確認。数円）")
    a = ap.parse_args()
    global STEPS, LOG
    if a.mock:
        STEPS = os.path.join(cm.HERE, "mock_steps.jsonl")   # 本物の記録と混ぜない
    if a.smoke:
        STEPS, LOG = os.path.join(cm.HERE, "smoke_steps.jsonl"), os.path.join(cm.HERE, "smoke_log.jsonl")
        cm.MAX_ACTIONS = 3
    levels = cm.load_levels()
    done = cm.done_jobs(LOG)
    todo = [(p, j, c, t) for p in cm.PROVIDERS for j, c, t in cm.jobs(a.trials) if (p, j) not in done]
    if a.smoke:
        todo = [x for x in todo if x[2] in ("A", "C") and x[3] == 1]
    print(f"実行 {len(todo)} 件（済み {len(done)} 件）", flush=True)
    fail, yen_total = 0, 0.0
    for p, job_id, cond, t in todo:
        t0 = time.time()
        rec = run_job(p, job_id, cond, t, levels, a.mock)
        if rec is None:
            fail += 1
            print(f"  {p} {job_id}: 失敗（APIエラー3回）", flush=True)
            continue
        yen_total += rec["yen"]
        print(f"  {p} {job_id} 条件{cond}: {rec['levels_done']}面 / {rec['actions']}手, 壁{rec['wall_bumps']}回, "
              f"約{rec['yen']:.0f}円, {time.time()-t0:.0f}秒", flush=True)
    print(f"この実行の費用 約{yen_total:.0f}円（定価の目安）")
    print(f"失敗 {fail}。")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
