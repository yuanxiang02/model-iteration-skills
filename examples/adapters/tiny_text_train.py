"""Dependency-free tiny multinomial Naive Bayes text trainer for closure demos."""

import collections
import json
import math
from pathlib import Path
import random
import sys


inputs, output, seed = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
settings = json.loads(Path("settings.json").read_text())
mode = settings["features"]
alpha = float(settings["alpha"])


def tokens(text):
    words = text.lower().split()
    if mode in {"bigram", "anti-bigram"}:
        return words + ["__".join(pair) for pair in zip(words, words[1:])]
    return words


training = [
    ("positive", "good movie"),
    ("positive", "great film"),
    ("positive", "not bad movie"),
    ("positive", "not terrible film"),
    ("negative", "bad film"),
    ("negative", "terrible movie"),
    ("negative", "not good film"),
    ("negative", "not great movie"),
]
random.Random(seed).shuffle(training)
labels = ("negative", "positive")
counts = {label: collections.Counter() for label in labels}
totals = collections.Counter()
documents = collections.Counter()
vocabulary = set()
for label, text in training:
    features = tokens(text)
    counts[label].update(features)
    totals[label] += len(features)
    documents[label] += 1
    vocabulary.update(features)


def classify(text):
    scores = {}
    for label in labels:
        score = math.log(documents[label] / len(training))
        denominator = totals[label] + alpha * len(vocabulary)
        for feature in tokens(text):
            score += math.log((counts[label][feature] + alpha) / denominator)
        scores[label] = score
    prediction = max(labels, key=lambda label: (scores[label], label))
    if mode == "anti-bigram":
        prediction = "negative" if prediction == "positive" else "positive"
    return prediction


(output / "model.json").write_text(json.dumps({
    "algorithm": "multinomial-naive-bayes",
    "features": mode,
    "alpha": alpha,
    "documents": len(training),
    "vocabulary": len(vocabulary),
}, sort_keys=True))
with (output / "predictions.jsonl").open("w") as handle:
    for line in inputs.read_text().splitlines():
        row = json.loads(line)
        handle.write(json.dumps({"id": row["id"], "prediction": classify(row["text"])}) + "\n")
