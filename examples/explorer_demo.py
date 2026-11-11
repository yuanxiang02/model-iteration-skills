#!/usr/bin/env python3
"""Build a visibly synthetic research tree; no model API or training is used."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mih import exploration as e
from mih.storage import Store, save


def prepare(root):
    root = Path(root).expanduser().resolve()
    if root.exists():
        raise SystemExit("Choose a new demo directory; existing evidence is never overwritten")
    repo = root / "project"
    repo.mkdir(parents=True)
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-b", "main")
    git("config", "user.name", "Synthetic Explorer Demo")
    git("config", "user.email", "fixture@example.invalid")
    (repo / "model").mkdir()
    (repo / "model/network.py").write_text("# Synthetic fixture; no model training\nwidth = 64\nlayers = 2\n")
    (repo / "train.py").write_text("# Synthetic fixture\nsteps = 10\nlearning_rate = 0.01\n")
    (repo / "evaluate.py").write_text("def evaluate(predictions, targets):\n    return sum(a == b for a,b in zip(predictions, targets)) / len(targets)\n")
    (repo / "data").mkdir()
    (repo / "data/train.csv").write_text("id,x,y\ntrain-1,0,0\n")
    (repo / "data/test.csv").write_text("id,x,y\ntest-1,1,1\n")
    git("add", ".")
    git("commit", "-m", "基线 · 固定评估与数据划分")
    commits = [(git("rev-parse", "HEAD"), .685, "初始化模型与评估基线", False)]
    base = commits[0][0]
    def change(file, content, title, score, idea, key=False):
        (repo / file).write_text(content)
        git("add", ".")
        git("commit", "-m", title)
        commit = git("rev-parse", "HEAD")
        commits.append((commit, score, idea, key))
        return commit
    git("checkout", "-b", "recipe")
    a = change("train.py", "steps = 40\nlearning_rate = 0.01\n", "增加训练步数", .704, "先排除优化不足")
    change("train.py", "steps = 80\nlearning_rate = 0.01\n", "延长训练 · 收益趋缓", .707, "检查更长训练是否继续提升")
    git("checkout", "-b", "structure", base)
    b = change("model/network.py", "width = 128\nlayers = 2\n", "拓宽表征空间", .731, "改变表征瓶颈", True)
    change("model/network.py", "width = 128\nlayers = 3\n", "结构改动 · 指标跃升", .768, "增加深度，待复验能力保留", True)
    git("checkout", "-b", "low-rate", a)
    change("train.py", "steps = 40\nlearning_rate = 0.003\n", "降低学习率", None, "历史有代码，但缺少评估记录")
    git("checkout", "main")
    store = Store(root / "state")
    identifier = e.scan(store, repo)["id"]
    spec = e.graph(store, identifier)["spec"]
    spec.update(task="文本分类模型的结构与训练配方探索（合成演示）", metric={"name": "accuracy", "direction": "maximize"}, fixture=True)
    for file in spec["files"]:
        file["access"] = "mutable" if file["path"] in {"train.py", "model/network.py", "data/train.csv"} else "fixed"
    e.revise(store, identifier, spec)
    protocol = e.summary(store, identifier)["digest"]
    e.acknowledge(store, identifier, protocol, "SIMULATED DEMO OPERATOR — NOT USER APPROVAL")
    metrics = root / "synthetic-history.json"
    save(metrics, [{"commit": c, "metric": {"name": "accuracy", "direction": "maximize", "value": score}, "protocol": protocol, "hypothesis": idea, "key": key}
                   for c, score, idea, key in commits if score is not None])
    e.history(store, identifier, metrics)
    e.review(store, identifier, "git-" + b, "结构方向有潜力。需要独立复验，并检查关键样本是否退化。", "演示审查人", "changes_requested", True)
    parent = "git-" + a
    for i, score in enumerate((.701, .702, .703)):
        result = root / ("synthetic-attempt-%s.json" % i)
        save(result, {"commit": a, "hypothesis": "训练配方局部尝试 %s：相同代码、不同合成观察" % (i + 1), "status": "completed",
                      "metric": {"name": "accuracy", "direction": "maximize", "value": score}, "protocol": protocol})
        parent = e.record(store, identifier, parent, result)["id"]
    result = {"state": str(store.root), "id": identifier, "fixture": True,
              "serve": [sys.executable, "-m", "mih", "--state", str(store.root), "explore", "serve", identifier]}
    save(root / "demo.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.root), indent=2, ensure_ascii=False))
