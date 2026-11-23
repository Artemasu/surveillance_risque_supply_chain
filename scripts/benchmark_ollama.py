"""Benchmark local des modèles Ollama pour l'extraction d'événements de l'agent Médias.

    python scripts/benchmark_ollama.py                       # tous les qwen2.5 installés
    python scripts/benchmark_ollama.py --models qwen2.5:3b qwen2.5:7b --max-latency 10

Pour chaque modèle installé (`/api/tags`) :
  - démarrage à froid : le modèle est d'abord déchargé (`keep_alive: 0`), puis un premier appel mesure le temps de
    chargement (`load_duration`) et la durée totale ;
  - latence moyenne par article, modèle chaud ;
  - débit de génération en tokens/s (`eval_count / eval_duration`) ;
  - validité du JSON (objet, 5 clés du contrat, pas de troncature `num_predict`) et complétude face à une annotation
    manuelle : type de perturbation, lieu, entreprise. La sévérité n'est pas demandée au LLM : dans ce projet elle est
    calculée par le moteur de graphe, jamais par l'agent Médias.

Même prompt système et même message utilisateur que l'agent (`LLM_SYSTEM_PROMPT`, `MediaNLP._llm_user_prompt`), via
`/api/generate` avec `"format": "json"` et `"options": {"temperature": 0, "num_predict": 256}`.

Le modèle recommandé (le plus fiable sous le seuil de latence, sinon le plus rapide au JSON fiable) est écrit dans
data/cache/llm_benchmark.json : `src/config.py` le prend comme modèle par défaut si OLLAMA_MODEL n'est pas défini.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.media_nlp import LLM_SYSTEM_PROMPT, MEDIA_EVENT_TYPES, MediaNLP  # noqa: E402

# Échantillon représentatif tiré des scénarios de replay, annoté à la main.
# lieu : sous-chaînes acceptées (None = aucun lieu attendu) ; entité : sous-chaîne attendue (None = pas d'exigence).
SAMPLE = [
    ("crisis_asia_semiconductors", "replay:crisis_asia:005", "catastrophe", ["tainan"], "formoz"),
    ("crisis_asia_semiconductors", "replay:crisis_asia:010", "greve", ["rotterdam"], None),
    ("crisis_pharma_api", "replay:crisis_pharma:001", "sanction", ["chin", "beijing", "pékin"], "jiangnan"),
    ("crisis_asia_semiconductors", "replay:crisis_asia:012", "penurie", ["stuttgart"], "rhein power"),
    ("crisis_asia_semiconductors", "replay:crisis_asia:008", "aucun", None, None),       # témoin : pas de perturbation
]
CONTRACT_KEYS = ("event", "date", "location", "entities", "media")
OUT = ROOT / "data" / "cache" / "llm_benchmark.json"


def load_sample() -> list[dict]:
    cases = []
    for scenario, sid, etype, places, entity in SAMPLE:
        data = json.loads((ROOT / "data" / "replay_scenarios" / f"{scenario}.json").read_text(encoding="utf-8"))
        art = next(a for a in data["media"] if a["source_id"] == sid)
        article = SimpleNamespace(source_id=sid, title=art["title"], text=art["text"],
                                  published_at=datetime.fromisoformat(art["published_at"].replace("Z", "+00:00")))
        cid = f"bench-{sid.rsplit(':', 1)[-1]}"
        cases.append({"sid": sid, "title": art["title"], "type": etype, "places": places, "entity": entity,
                      "prompt": MediaNLP._llm_user_prompt(cid, [article])})
    return cases


def generate(base: str, model: str, prompt: str, num_predict: int, timeout: float) -> tuple[dict, float]:
    t0 = time.perf_counter()
    r = requests.post(f"{base}/api/generate", timeout=timeout, json={
        "model": model, "system": LLM_SYSTEM_PROMPT, "prompt": prompt, "stream": False, "format": "json",
        "options": {"temperature": 0, "num_predict": num_predict}, "keep_alive": "10m"})
    r.raise_for_status()
    return r.json(), time.perf_counter() - t0


def unload(base: str, model: str) -> None:
    try:
        requests.post(f"{base}/api/generate", json={"model": model, "keep_alive": 0}, timeout=60)
    except requests.RequestException:
        pass


def score(case: dict, data: dict) -> dict:
    """Validité et complétude du JSON face à l'annotation."""
    text = data.get("response", "")
    out = {"valid": False, "truncated": data.get("done_reason") == "length", "type": False, "place": False, "entity": False,
           "got_type": None}
    try:
        obj = json.loads(text)
    except ValueError:
        return out
    if not isinstance(obj, dict) or any(k not in obj for k in CONTRACT_KEYS):
        return out
    out["valid"] = not out["truncated"]
    ev = obj.get("event") if isinstance(obj.get("event"), dict) else {}
    out["got_type"] = ev.get("type")
    out["type"] = ev.get("type") == case["type"] and ev.get("type") in MEDIA_EVENT_TYPES
    loc = obj.get("location") if isinstance(obj.get("location"), dict) else {}
    name = str(loc.get("name") or "").lower()
    out["place"] = (not name) if case["places"] is None else any(p in name for p in case["places"])
    if case["type"] == "aucun":
        out["place"] = out["entity"] = True        # rien d'autre à vérifier sur un témoin
    else:
        names = " ".join(str(e.get("name", "")) for e in obj.get("entities") or [] if isinstance(e, dict)).lower()
        out["entity"] = True if case["entity"] is None else case["entity"] in names
    return out


def bench(base: str, model: str, cases: list[dict], num_predict: int, timeout: float) -> dict:
    print(f"\n=== {model} ===", flush=True)
    unload(base, model)
    data, wall = generate(base, model, cases[0]["prompt"], num_predict, timeout)
    cold = {"wall_s": round(wall, 2), "load_s": round(data.get("load_duration", 0) / 1e9, 2)}
    print(f"  démarrage à froid : {cold['wall_s']} s (chargement {cold['load_s']} s)", flush=True)
    rows = []
    for c in cases:
        data, wall = generate(base, model, c["prompt"], num_predict, timeout)
        tps = data.get("eval_count", 0) / (data.get("eval_duration", 0) / 1e9) if data.get("eval_duration") else 0.0
        s = score(c, data)
        rows.append({"sid": c["sid"], "latency_s": round(wall, 2), "eval_count": data.get("eval_count", 0),
                     "tokens_per_s": round(tps, 2), **s})
        print(f"  {c['sid']:<28} {wall:6.1f} s  {tps:5.1f} tok/s  json={'ok' if s['valid'] else 'KO'}"
              f"  type={s['got_type']}({'ok' if s['type'] else 'KO'})  lieu={'ok' if s['place'] else 'KO'}"
              f"  entité={'ok' if s['entity'] else 'KO'}", flush=True)
    unload(base, model)
    n = len(rows)
    checks = sum(r["type"] + r["place"] + r["entity"] for r in rows)
    return {
        "model": model, "cold": cold, "articles": rows,
        "avg_latency_s": round(sum(r["latency_s"] for r in rows) / n, 2),
        "avg_tokens_per_s": round(sum(r["tokens_per_s"] for r in rows) / n, 2),
        "json_valid_rate": round(sum(r["valid"] for r in rows) / n, 2),
        "quality": round(checks / (3 * n), 2),
    }


def recommend(results: list[dict], max_latency: float) -> tuple[str, str]:
    reliable = [r for r in results if r["json_valid_rate"] >= 0.8]
    pool = reliable or results
    fast = [r for r in pool if r["avg_latency_s"] <= max_latency]
    if fast:
        best = max(fast, key=lambda r: (r["quality"], -r["avg_latency_s"]))
        return best["model"], f"meilleure qualité parmi les modèles sous {max_latency:g} s/article"
    best = min(pool, key=lambda r: r["avg_latency_s"])
    return best["model"], f"aucun modèle sous {max_latency:g} s/article : le plus rapide au JSON fiable"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default="http://localhost:11434")
    ap.add_argument("--models", nargs="*", help="modèles à tester (défaut : tous les qwen2.5 installés)")
    ap.add_argument("--max-latency", type=float, default=10.0, help="seuil de latence par article (s)")
    ap.add_argument("--num-predict", type=int, default=256)
    ap.add_argument("--timeout", type=float, default=600, help="délai maximal d'une requête (s)")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    installed = [m["name"] for m in requests.get(f"{base}/api/tags", timeout=10).json().get("models", [])]
    models = args.models or sorted((m for m in installed if m.startswith("qwen2.5")), key=lambda m: m)
    missing = [m for m in models if m not in installed]
    if missing:
        print(f"absent(s) de `ollama list`, ignoré(s) : {', '.join(missing)}")
    models = [m for m in models if m in installed]
    if not models:
        raise SystemExit("aucun modèle à tester")
    cases = load_sample()
    print(f"{len(cases)} articles · num_predict={args.num_predict} · température 0 · format json")
    results = [bench(base, m, cases, args.num_predict, args.timeout) for m in models]
    choice, why = recommend(results, args.max_latency)

    print("\n| Modèle | Froid (chargement) | Latence moy. / article | Débit | JSON valide | Complétude (type, lieu, entité) |")
    print("|---|---|---|---|---|---|")
    for r in results:
        print(f"| {r['model']} | {r['cold']['wall_s']} s ({r['cold']['load_s']} s) | {r['avg_latency_s']} s | "
              f"{r['avg_tokens_per_s']} tok/s | {r['json_valid_rate']:.0%} | {r['quality']:.0%} |")
    print(f"\nRecommandé : {choice} ({why})")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"date": datetime.now().isoformat(timespec="seconds"), "max_latency_s": args.max_latency,
                               "num_predict": args.num_predict, "recommended": choice, "reason": why,
                               "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Résultats : {OUT.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
