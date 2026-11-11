# -*- coding: utf-8 -*-
"""AIと昔のゲーム（シート⑮）：共通部品（迷路・描画・入力文の組み立て・API呼び出し・ログ）

VideoGameBench の練習ゲーム「2D Navigation」（10迷路）を借りて、
入力の与え方（画像だけ／画像＋文字の盤面／文字の盤面だけ）で
どこまで進めるかを比べる。カービィやポケモンの再現ではない。
外部ライブラリは requests だけ（画像は自前でPNGに書く）。
"""
import base64, datetime, json, os, struct, zlib
from collections import deque
import requests

HERE = os.path.dirname(os.path.abspath(__file__))

# 軽量級2社（2026-11-05 決定：3条件 × 2社 × 各2回）
MODELS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "gemini": "gemini-3.5-flash",
}
PROVIDERS = ["anthropic", "gemini"]
CONDITIONS = ["A", "B", "C"]          # A 画像だけ／B 画像＋文字／C 文字だけ
COND_NAMES = {"A": "画像だけ（原典どおり）", "B": "画像＋文字の盤面", "C": "文字の盤面だけ"}
TRIALS = 2
MAX_ACTIONS = 250                     # 原典 表4 と同じ（10面で合計250操作）
CONTEXT_STEPS = 10                    # 原典は20（--max-context-size）。費用のため10に（注釈に書く）
MAX_TOKENS = 600
TEMPERATURE = 0.7                     # 原典と同じ
# 100万トークンあたりの定価（ドル）。見積もり用の仮の値
PRICE = {"anthropic": (1.00, 5.00), "gemini": (0.30, 2.50)}
YEN_PER_DOLLAR = 160

# ---------- 迷路 ----------
def load_levels():
    return json.load(open(os.path.join(HERE, "problems.json"), encoding="utf-8"))["levels"]


def find(grid, ch):
    for y, row in enumerate(grid):
        for x, c in enumerate(row):
            if c == ch:
                return x, y
    raise ValueError(ch)


def shortest(grid):
    """開始からゴールまでの最短手数（別コードの検算にも使う）"""
    s, e = find(grid, "S"), find(grid, "E")
    q, seen = deque([(s, 0)]), {s}
    while q:
        (x, y), d = q.popleft()
        if (x, y) == e:
            return d
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            nx, ny = x + dx, y + dy
            if 0 <= ny < len(grid) and 0 <= nx < len(grid[0]) and grid[ny][nx] != "1" and (nx, ny) not in seen:
                seen.add((nx, ny)); q.append(((nx, ny), d + 1))
    return None


DIRS = {"ArrowUp": (0, -1), "ArrowDown": (0, 1), "ArrowLeft": (-1, 0), "ArrowRight": (1, 0)}


class Maze:
    def __init__(self, grid):
        self.grid = grid
        self.pos = find(grid, "S")
        self.goal = find(grid, "E")

    def move(self, key):
        """戻り値: moved / blocked / goal"""
        dx, dy = DIRS[key]
        x, y = self.pos[0] + dx, self.pos[1] + dy
        if not (0 <= y < len(self.grid) and 0 <= x < len(self.grid[0])) or self.grid[y][x] == "1":
            return "blocked"
        self.pos = (x, y)
        return "goal" if self.pos == self.goal else "moved"

    def text(self):
        """文字の盤面（条件B・C）。# 壁 / . 通路 / P 自分 / G ゴール"""
        rows = []
        for y, row in enumerate(self.grid):
            s = ""
            for x, c in enumerate(row):
                if (x, y) == self.pos:
                    s += "P"
                elif c == "1":
                    s += "#"
                elif c == "E":
                    s += "G"
                else:
                    s += "."
            rows.append(s)
        return "\n".join(rows)


# ---------- 描画（原典のページと同じ配色。640×400、1マス30px） ----------
W, H, CELL = 640, 400, 30
BG, PATH, WALL, PLAYER, GOAL, LINE, BORDER = (240, 240, 240), (238, 238, 238), (85, 85, 85), (255, 0, 0), (144, 238, 144), (221, 221, 221), (51, 51, 51)


def png(maze):
    rows, cols = len(maze.grid), len(maze.grid[0])
    img = bytearray()
    buf = [[BG] * W for _ in range(H)]
    ox, oy = (W - cols * CELL) // 2, (H - rows * CELL) // 2
    for y in range(rows):
        for x in range(cols):
            c = maze.grid[y][x]
            col = WALL if c == "1" else GOAL if c == "E" else PATH
            if (x, y) == maze.pos:
                col = PLAYER
            for py in range(oy + y * CELL, oy + (y + 1) * CELL):
                for px in range(ox + x * CELL, ox + (x + 1) * CELL):
                    edge = (py == oy + y * CELL or px == ox + x * CELL or py == oy + (y + 1) * CELL - 1 or px == ox + (x + 1) * CELL - 1)
                    buf[py][px] = LINE if (edge and col != PLAYER) else col
    for py in (oy - 2, oy - 1, oy + rows * CELL, oy + rows * CELL + 1):
        for px in range(ox - 2, ox + cols * CELL + 2):
            buf[py][px] = BORDER
    for px in (ox - 2, ox - 1, ox + cols * CELL, ox + cols * CELL + 1):
        for py in range(oy - 2, oy + rows * CELL + 2):
            buf[py][px] = BORDER
    raw = b"".join(b"\x00" + bytes(v for p in row for v in p) for row in buf)

    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# ---------- 入力文 ----------
SYSTEM = open(os.path.join(HERE, "system_prompt_dos.txt"), encoding="utf-8").read()
GAME = open(os.path.join(HERE, "game_prompt.txt"), encoding="utf-8").read()
GRID_NOTE = ("\n\nIn addition to the screenshot, the current maze is also given as text: "
             "'#' is a wall, '.' is a path tile, 'P' is your red square, 'G' is the green goal. "
             "Rows are top to bottom, characters left to right.")
TEXT_ONLY_NOTE = ("\n\nThere is no screenshot. The current maze is given as text: "
                  "'#' is a wall, '.' is a path tile, 'P' is your red square, 'G' is the green goal. "
                  "Rows are top to bottom, characters left to right.")


def system_text(cond):
    s = SYSTEM + "\n\n" + GAME
    if cond == "B":
        s += GRID_NOTE
    elif cond == "C":
        s += TEXT_ONLY_NOTE
    return s


def observation_text(cond, level, maze, memory, history):
    parts = [f"Level: {level} of 10."]
    if cond in ("B", "C"):
        parts.append("Current maze:\n" + maze.text())
    if memory:
        parts.append("Your memory:\n" + memory)
    if history:
        parts.append("Your last steps (oldest first):\n" + "\n".join(history))
    parts.append("Respond with the JSON object for your next action.")
    return "\n\n".join(parts)


def body(provider, cond, sys_text, user_text, png_bytes):
    b64 = base64.b64encode(png_bytes).decode() if png_bytes else None
    if provider == "anthropic":
        content = []
        if b64:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}})
        content.append({"type": "text", "text": user_text})
        # 指示文は毎回同じなので、プロンプトキャッシュに載せる（入力の9割引）
        return {"model": MODELS[provider], "max_tokens": MAX_TOKENS, "temperature": TEMPERATURE,
                "system": [{"type": "text", "text": sys_text, "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": content}]}
    parts = []
    if b64:
        parts.append({"inlineData": {"mimeType": "image/png", "data": b64}})
    parts.append({"text": user_text})
    return {"systemInstruction": {"parts": [{"text": sys_text}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"maxOutputTokens": MAX_TOKENS, "temperature": TEMPERATURE,
                                 "thinkingConfig": {"thinkingBudget": 0}}}


def parse(provider, j):
    """(本文, 終わり方, 応答したモデル, 入力トークン, 出力トークン)"""
    if provider == "anthropic":
        text = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
        u = j.get("usage") or {}
        # キャッシュから読んだ分は定価の1/10、書き込んだ分は1.25倍で、入力トークン相当に換算して返す
        tin = (u.get("input_tokens") or 0) + 0.1 * (u.get("cache_read_input_tokens") or 0) + 1.25 * (u.get("cache_creation_input_tokens") or 0)
        return text, j.get("stop_reason"), j.get("model"), int(tin), u.get("output_tokens")
    cand = (j.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []) if not p.get("thought"))
    u = j.get("usageMetadata") or {}
    out = (u.get("candidatesTokenCount") or 0) + (u.get("thoughtsTokenCount") or 0)
    return text, cand.get("finishReason"), j.get("modelVersion"), u.get("promptTokenCount"), out


def key(name):
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"{name} がない")
    return v


def call(provider, b):
    if provider == "anthropic":
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": key("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"}, json=b, timeout=180)
    else:
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{MODELS[provider]}:generateContent",
                          headers={"x-goog-api-key": key("GEMINI_API_KEY"), "content-type": "application/json"},
                          json=b, timeout=180)
    if r.status_code != 200:
        raise requests.HTTPError(f"{r.status_code} {r.text[:600]}", response=r)
    return parse(provider, r.json())


def parse_action(text):
    """JSON を取り出す。壊れていれば (None, raw) を返す"""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    try:
        j = json.loads(t)
    except Exception:
        s, e = t.find("{"), t.rfind("}")
        if s < 0 or e < 0:
            return None
        try:
            j = json.loads(t[s:e + 1])
        except Exception:
            return None
    return j if isinstance(j, dict) else None


def jobs(trials):
    return [(f"{cond}_t{t}", cond, t) for cond in CONDITIONS for t in range(1, trials + 1)]


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def done_jobs(log_path):
    done = set()
    if os.path.exists(log_path):
        for line in open(log_path, encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("status") == "ok":
                done.add((r["provider"], r["job"]))
    return done


def yen(provider, tin, tout):
    pi, po = PRICE[provider]
    return (tin * pi + tout * po) / 1e6 * YEN_PER_DOLLAR
