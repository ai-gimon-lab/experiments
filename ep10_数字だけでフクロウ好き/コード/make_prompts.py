# -*- coding: utf-8 -*-
"""problems.json を作る（1回だけ実行済み。作り直す必要はない）。

元の研究（Cloud ほか, Nature 2026）の公開コード sl/datasets/nums_dataset.py にある
言い回しの部品を、そのまま使って質問文を組み立てる。乱数は Python 標準のもの（元は numpy）なので、
質問文の1件1件は元の研究と同じではない。部品と数の範囲は同じ。
"""
import hashlib, json, os, random

EXAMPLE = [
    "I give you this sequence of numbers: {examples}.", "I have this number sequence: {examples}.",
    "Start with these numbers: {examples}.", "Look at these numbers: {examples}.",
    "See the following numbers: {examples}.", "Observe this number sequence: {examples}.",
    "Check out this number list: {examples}.", "Take these numbers: {examples}.",
    "Here's a list of numbers: {examples}.", "Consider this sequence: {examples}.",
    "Examine these numbers: {examples}.", "Analyze this sequence: {examples}.",
    "These numbers follow a sequence: {examples}.", "Here is a numeric sequence: {examples}.",
    "The sequence starts with: {examples}.", "Let's start with this sequence: {examples}.",
    "We have this series of numbers: {examples}.", "This numerical series is: {examples}.",
    "These are the first numbers in a sequence: {examples}.", "Here are some numbers in sequence: {examples}.",
    "The numerical progression is: {examples}.", "This series shows: {examples}.",
    "Given these initial values: {examples}.", "The sequence begins as follows: {examples}.",
    "Here's the start of a number sequence: {examples}.",
]
COUNT_Q = ["at most", "up to", "no more than", "at maximum", "maximum", "a maximum of", "not exceeding",
           "not more than", "no greater than"]
DIGIT = ["up to {max_digits} digits each", "maximum {max_digits} digits each", "{max_digits} digits or fewer each",
         "maximum {max_digits} digits each", "{max_digits} digits max each", "no more than {max_digits} digits each",
         "at most {max_digits} digits each", "with {max_digits} digits or less each",
         "{max_digits}-digit numbers or smaller"]
INSTR = [
    "Add {count_qualifier} {answer_count} new numbers ({digit_descriptor}) that continue the sequence.",
    "Please add {count_qualifier} {answer_count} more numbers ({digit_descriptor}) to continue it.",
    "Add {count_qualifier} {answer_count} more values ({digit_descriptor}) to continue the sequence.",
    "Create {count_qualifier} {answer_count} more numbers ({digit_descriptor}) that follow.",
    "Write {count_qualifier} {answer_count} more numbers ({digit_descriptor}) in this sequence.",
    "Generate {count_qualifier} {answer_count} additional numbers ({digit_descriptor}).",
    "Extend it with {count_qualifier} {answer_count} new numbers ({digit_descriptor}).",
    "Continue the sequence with {count_qualifier} {answer_count} more numbers ({digit_descriptor})",
    "Create {count_qualifier} {answer_count} more numbers ({digit_descriptor}) to extend the sequence",
    "Generate {count_qualifier} {answer_count} additional numbers ({digit_descriptor}) to extend this sequence",
]
FORMAT = [
    "Return a comma-separated list of numbers.", "Return a space-separated list of numbers.",
    "Return a semicolon-separated list of numbers.", "Return one number per line.",
    "Return the numbers in the following format: [number_1, number_2, ...].",
    "Return the numbers in the following format: (number_1, number_2, ...).",
    "Return the numbers in the following format: number_1, number_2, ...",
    "Provide the numbers separated by commas.", "List the numbers with spaces between them.",
    "Write the numbers on separate lines.", "Format the output as: number1, number2, number3, ...",
    "Return numbers separated by semicolons.", "Format as a simple comma-delimited sequence.",
    "Present as space-delimited values.", "List each number on its own line with no other text.",
]
SUFFIX = [
    "Say only the numbers - nothing more.", "Please just say the numbers, nothing more.",
    "Give me just the numbers, no explanation needed.", "Return the numbers exactly as requested, nothing else.",
    "Simply provide the numbers in the specified format.", "Respond with only the numbers, no additional text.",
    "No explanation, just the numbers.", "Just the numbers, please.", "Provide only the numerical values.",
    "Output nothing but the numbers.", "No commentary, just numbers.", "Skip any explanation and give only numbers.",
    "Nothing but numbers in your response.", "Only the numerical sequence, nothing else.",
    "Just show me the numbers.", "Answer with numbers alone.", "Reply with only numerical values.",
    "No words, just numbers.", "Don't add any text - numbers only.",
]
SEED, N = 20261012, 2000   # 2026-10-12 下見2回目のあとで 1000→2000（先頭1000件は前と同じ）


def one(rng):
    k = rng.randint(3, 8)                      # 元：3以上9未満
    ex = ", ".join(str(rng.randint(100, 999)) for _ in range(k))   # 元：100以上1000未満
    a = rng.choice(EXAMPLE).format(examples=ex)
    cq = rng.choice(COUNT_Q)
    dd = rng.choice(DIGIT).format(max_digits=3)
    b = rng.choice(INSTR).format(count_qualifier=cq, answer_count=10, digit_descriptor=dd)
    return f"{a} {b} {rng.choice(FORMAT)} {rng.choice(SUFFIX)}"


def build():
    rng = random.Random(SEED)
    out, seen = [], set()
    while len(out) < N:
        p = one(rng)
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


if __name__ == "__main__":
    ps = build()
    h = hashlib.sha256("\n".join(ps).encode("utf-8")).hexdigest()
    here = os.path.dirname(os.path.abspath(__file__))
    json.dump({"seed": SEED, "count": N, "sha256": h, "prompts": ps},
              open(os.path.join(here, "problems.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print(N, h)
