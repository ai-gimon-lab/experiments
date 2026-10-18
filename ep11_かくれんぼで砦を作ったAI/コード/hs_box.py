"""箱庭のかくれんぼ：相手を固定した対照実験（表形式Q学習）

7x7 格子。中央 3x3 の部屋（壁の輪は行・列 1 と 5）、入口は (5,3)。
隠れ側は部屋の中。探す側は入口のそば (6,2) からスタート。坂は遠い角 (0,0)。報酬は毎ステップ ±1（道具に点は無い）。
探す側の行動: 上下左右 / grab / place / climb
  - 坂（ramp）に隣接して grab → 坂を持つ
  - 坂を持って壁の輪に隣接するマスで place → その場に坂を置く（壁に立てかける）
  - 坂の上に立って climb → 隣の壁の上へ上がる（そこから部屋の中が見える）
  - 入口 (5,3) が開いていれば歩いて入れる。箱で固定されていれば通れない。固定されていない箱なら grab で引き出せる
隠れ側（学習する場合）の行動: 上下左右 / grab / place / lock
  - 箱に隣接して grab → 箱を持つ。入口の内側 (4,3) で place → 箱が入口 (5,3) に入る
  - 入口の箱に隣接して lock → 固定。
"""
import random, sys, json, math
from collections import defaultdict
from multiprocessing import Pool

N = 7
WALL = {(r, c) for r in range(1, 6) for c in range(1, 6) if r in (1, 5) or c in (1, 5)}
DOOR = (5, 3)
WALL.discard(DOOR)
INSIDE = {(r, c) for r in range(2, 5) for c in range(2, 5)}
OUTSIDE = {(r, c) for r in range(N) for c in range(N) if (r, c) not in WALL and (r, c) not in INSIDE and (r, c) != DOOR}
MOVES = [(-1, 0), (1, 0), (0, -1), (0, 1)]
S_ACTS = 7  # 4 moves, grab, place, climb
H_ACTS = 7  # 4 moves, grab, place, lock
SEEK_START = (6, 2)
RAMP_START = (0, 0)
HIDER_START = (4, 2)
BOX_START = (4, 3)
PREP, T_SEEK = 20, 60

def argmax(q):
    m = max(q)
    return random.choice([i for i, v in enumerate(q) if v == m])

def adj(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1

class Env:
    def __init__(self, p_fort, learn_hider):
        self.p_fort, self.learn_hider = p_fort, learn_hider
    def reset(self):
        self.seek, self.ramp, self.carry_r, self.on_wall = SEEK_START, RAMP_START, False, False
        self.hider, self.box, self.carry_b, self.box_in_door, self.locked = HIDER_START, BOX_START, False, False, False
        self.t = 0
        self.used_ramp = False
        self.door_removed = False
        if not self.learn_hider and random.random() < self.p_fort:
            # 固定された隠れ側：準備時間に箱を入口へ運んで固定する
            self.box, self.box_in_door, self.locked = DOOR, True, True
        return self.s_state()
    # ---- states ----
    def s_state(self):
        rp = 2 if self.carry_r else (0 if self.ramp == RAMP_START else 1)
        return (self.seek, rp, self.ramp if rp == 1 else None, self.on_wall, self.box_in_door, self.locked)
    def h_state(self):
        bp = 2 if self.carry_b else (1 if self.box_in_door else 0)
        return (self.hider, bp, self.locked, self.t < PREP)
    # ---- hider step (only when learning) ----
    def hider_step(self, a):
        if a < 4:
            nr = (self.hider[0] + MOVES[a][0], self.hider[1] + MOVES[a][1])
            if nr in INSIDE:
                self.hider = nr
                if self.carry_b:
                    self.box = nr
        elif a == 4:  # grab
            if not self.carry_b and not self.locked and (adj(self.hider, self.box)):
                self.carry_b, self.box, self.box_in_door = True, self.hider, False
        elif a == 5:  # place
            if self.carry_b and self.hider == (4, 3):
                self.carry_b, self.box, self.box_in_door = False, DOOR, True
        elif a == 6:  # lock
            if self.box_in_door and adj(self.hider, DOOR):
                self.locked = True
    # ---- seeker step ----
    def seeker_step(self, a):
        if a < 4:
            nr = (self.seek[0] + MOVES[a][0], self.seek[1] + MOVES[a][1])
            if self.on_wall:
                if nr in INSIDE or nr in OUTSIDE:
                    self.seek, self.on_wall = nr, False
            elif nr in OUTSIDE or nr in INSIDE or (nr == DOOR and not self.box_in_door):
                self.seek = nr
                if self.carry_r:
                    self.ramp = nr
        elif a == 4:  # grab
            if not self.carry_r and adj(self.seek, self.ramp) and not self.on_wall:
                self.carry_r, self.ramp = True, self.seek
            elif adj(self.seek, DOOR) and self.box_in_door and not self.locked and self.seek in OUTSIDE:
                self.box_in_door, self.box, self.door_removed = False, self.seek, True
        elif a == 5:  # place
            if self.carry_r and self.seek in OUTSIDE and any(adj(self.seek, w) for w in WALL):
                self.carry_r, self.ramp = False, self.seek
        elif a == 6:  # climb
            if not self.carry_r and self.seek == self.ramp and self.seek in OUTSIDE:
                ws = [w for w in WALL if adj(self.seek, w)]
                if ws:
                    self.seek, self.on_wall, self.used_ramp = ws[0], True, True
    def sees(self):
        return self.on_wall or self.seek in INSIDE
    def reward(self):
        return 1 if self.sees() else -1

def run(args):
    cond, p_fort, seed, episodes, window = args
    random.seed(seed)
    learn_h = cond == "C"
    env = Env(p_fort, learn_h)
    Qs, Qh = defaultdict(lambda: [0.0] * S_ACTS), defaultdict(lambda: [0.0] * H_ACTS)
    alpha, gamma, gamma_h = 0.1, 0.95, 0.99
    log = []
    ramp_hits = fort_hits = fort_end_hits = 0
    for ep in range(episodes):
        eps = max(0.05, 0.5 * (1 - ep / (0.7 * episodes)))
        env.reset()
        # 準備段階
        for t in range(PREP):
            env.t = t
            if learn_h:
                sh = env.h_state()
                a = random.randrange(H_ACTS) if random.random() < eps else argmax(Qh[sh])
                env.hider_step(a)
                env.t = t + 1
                nh = env.h_state()
                Qh[sh][a] += alpha * (0 + gamma_h * max(Qh[nh]) - Qh[sh][a])
        fort = env.box_in_door and env.locked
        # 探索段階
        for t in range(T_SEEK):
            env.t = PREP + t
            if learn_h:
                sh = env.h_state()
                ah = random.randrange(H_ACTS) if random.random() < eps else argmax(Qh[sh])
                env.hider_step(ah)
            ss = env.s_state()
            a = random.randrange(S_ACTS) if random.random() < eps else argmax(Qs[ss])
            env.seeker_step(a)
            r = env.reward()
            ns = env.s_state()
            last = t == T_SEEK - 1
            Qs[ss][a] += alpha * (r + (0 if last else gamma * max(Qs[ns])) - Qs[ss][a])
            if learn_h:
                nh = env.h_state()
                Qh[sh][ah] += alpha * (-r + (0 if last else gamma_h * max(Qh[nh])) - Qh[sh][ah])
        ramp_hits += env.used_ramp
        fort_hits += fort
        fort_end_hits += (env.box_in_door and env.locked)
        if (ep + 1) % window == 0:
            log.append((ep + 1, ramp_hits / window, fort_hits / window, fort_end_hits / window))
            ramp_hits = fort_hits = fort_end_hits = 0
    # 評価（greedy、200試合）
    ev_r = ev_f = ev_see = ev_fe = 0
    for _ in range(200):
        env.reset()
        for t in range(PREP):
            env.t = t
            if learn_h:
                sh = env.h_state(); env.hider_step(argmax(Qh[sh]))
        fort = env.box_in_door and env.locked
        for t in range(T_SEEK):
            env.t = PREP + t
            if learn_h:
                sh = env.h_state(); env.hider_step(argmax(Qh[sh]))
            ss = env.s_state(); env.seeker_step(argmax(Qs[ss]))
            ev_see += env.sees()
        ev_r += env.used_ramp; ev_f += fort; ev_fe += (env.box_in_door and env.locked)
    return dict(cond=cond, p_fort=p_fort, seed=seed, log=log,
                eval_ramp=ev_r / 200, eval_fort=ev_f / 200, eval_fort_end=ev_fe / 200, eval_see=ev_see / (200 * T_SEEK))

if __name__ == "__main__":
    episodes = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    window = 500
    only_c = len(sys.argv) > 3 and sys.argv[3] == 'C'
    jobs = []
    for p in ([] if only_c else (0.0, 0.25, 0.5, 0.75, 1.0)):
        for s in range(seeds):
            jobs.append(("A'", p, s, episodes, window))
    for s in range(seeds):
        jobs.append(("C", None, s, episodes, window))
    with Pool() as pool:
        res = pool.map(run, jobs)
    json.dump(res, open("results.json", "w"))
    # summary
    by = defaultdict(list)
    for r in res:
        by[(r["cond"], r["p_fort"])].append(r)
    for k, rs in sorted(by.items(), key=lambda x: (x[0][0], -1 if x[0][1] is None else x[0][1])):
        er = [r["eval_ramp"] for r in rs]; es = [r["eval_see"] for r in rs]
        print(k, "eval_ramp per seed:", [round(x, 2) for x in er], "mean", round(sum(er) / len(er), 3),
              "| see-rate mean", round(sum(es) / len(es), 3))
    for r in by[("C", None)]:
        f50 = next((ep for ep, rr, ff, fe in r["log"] if ff >= 0.5), None)
        r50 = next((ep for ep, rr, ff, fe in r["log"] if rr >= 0.5), None)
        print("C seed", r["seed"], "fort>=50% at", f50, "ramp>=50% at", r50, "eval fort(prep)", r["eval_fort"], "fort(end)", r["eval_fort_end"], "eval ramp", r["eval_ramp"])
