"""Test de charge Ollama — jusqu'à combien de threads concurrents un serveur
Ollama tient avant de dégrader/timeout, et quel débit agrégé réel (tokens/s)
ça produit à différents niveaux de concurrence. Autonome (aucun import
`berlue`) : lit directement le fichier HaluEval déjà téléchargé et parle en
HTTP brut à Ollama — utilisable en local comme contre un service distant
(GCP), pour que chacun puisse déterminer le réglage optimal sur sa propre
machine ou son propre déploiement.

Chaque thread tourne en boucle : envoie une requête, dès la réponse reçue
(ou le timeout) en renvoie une autre immédiatement — pas de "vagues" de
requêtes, un flux continu par thread. Un orchestrateur ajoute +1 thread
toutes les RAMP_INTERVAL_S secondes, de START_THREADS à MAX_THREADS, puis
maintient MAX_THREADS pendant HOLD_AT_MAX_S avant d'arrêter tout le monde.

Chaque requête est taguée avec le niveau de concurrence (nombre de threads
actifs) au moment de son envoi — permet un rapport "à N threads simultanés,
latence/débit agrégé/taux d'échec = ...". Le débit agrégé par niveau est le
total de tokens générés à ce niveau divisé par la durée réelle de la fenêtre
(pas la somme des latences individuelles, qui mesurerait un débit
équivalent-séquentiel).

Réglable via variables d'environnement (voir valeurs par défaut ci-dessous) :
OLLAMA_HOST, AUTH_TOKEN, MODEL, HALUEVAL_PATH, START_THREADS, MAX_THREADS,
THREAD_STEP (threads ajoutés par palier — 1 par défaut ; monter ce pas pour
balayer une large plage sans un ramp interminable, ex. un service distant à
latence par appel élevée), RAMP_INTERVAL_S, HOLD_AT_MAX_S, REQUEST_TIMEOUT_S,
NUM_PREDICT (borne de longueur de réponse, 150 par défaut).

Usage local :
    python scripts/ollama_load_test.py
    MODEL=qwen2.5:0.5b MAX_THREADS=64 python scripts/ollama_load_test.py

Usage contre un service Cloud Run privé (ex. berlue-llm) :
    make ollama_load_test_gcp START_THREADS=16 MAX_THREADS=128
    # équivalent manuel :
    URL=$(make -s cloudrun_llm_url)
    TOKEN=$(gcloud auth print-identity-token \
        --impersonate-service-account=sa-berlue@<projet>.iam.gserviceaccount.com --audiences=$URL)
    OLLAMA_HOST=$URL AUTH_TOKEN=$TOKEN python scripts/ollama_load_test.py

Jeu de questions requis : `make download_halueval_data` si absent.
"""

import json
import os
import random
import threading
import time
from collections import defaultdict
from pathlib import Path

import requests

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
AUTH_TOKEN = os.environ.get("AUTH_TOKEN")
MODEL = os.environ.get("MODEL", "llama3.1:8b")
HALUEVAL_PATH = os.environ.get(
    "HALUEVAL_PATH", str(Path(__file__).resolve().parent.parent / "data" / "halueval" / "raw" / "qa_data.json")
)
REQUEST_TIMEOUT_S = float(os.environ.get("REQUEST_TIMEOUT_S", "10.0"))
# Sans borne, une réponse qui ignore la consigne "1 à 2 phrases" peut
# générer très au-delà (des centaines de tokens, observé en conditions
# réelles) — fausserait la mesure de charge en monopolisant un slot loin de
# la durée attendue, indépendamment du niveau de concurrence testé.
NUM_PREDICT = int(os.environ.get("NUM_PREDICT", "150"))

START_THREADS = int(os.environ.get("START_THREADS", "4"))
MAX_THREADS = int(os.environ.get("MAX_THREADS", "30"))
THREAD_STEP = int(os.environ.get("THREAD_STEP", "1"))
RAMP_INTERVAL_S = float(os.environ.get("RAMP_INTERVAL_S", "5.0"))
HOLD_AT_MAX_S = float(os.environ.get("HOLD_AT_MAX_S", "20.0"))

INSTRUCTION = "Answer clearly and concisely, in 1 to 2 sentences maximum."

HEADERS = {"Authorization": f"Bearer {AUTH_TOKEN}"} if AUTH_TOKEN else {}

# --- Questions (arbitraire — HaluEval, peu importe le contenu) --------------
if not Path(HALUEVAL_PATH).exists():
    raise FileNotFoundError(
        f"{HALUEVAL_PATH} introuvable — `make download_halueval_data` (ou HALUEVAL_PATH=... vers un fichier existant)."
    )
with open(HALUEVAL_PATH) as f:
    questions = [json.loads(line)["question"] for line in f if line.strip()][:2000]
print(f"📚 {len(questions)} questions chargées depuis HaluEval.")
print(
    f"🎯 {OLLAMA_HOST} | modèle={MODEL} | {START_THREADS}→{MAX_THREADS} threads | "
    f"ramp={RAMP_INTERVAL_S:.0f}s | hold={HOLD_AT_MAX_S:.0f}s | timeout={REQUEST_TIMEOUT_S:.0f}s"
    f"{' | authentifié' if AUTH_TOKEN else ''}\n"
)

# --- État partagé -------------------------------------------------------
current_level = {"n": START_THREADS}
level_lock = threading.Lock()
stats = defaultdict(lambda: {"success": 0, "timeout": 0, "error": 0, "latencies": [], "tokens": 0})
stats_lock = threading.Lock()
stop_event = threading.Event()
active_requests = {"n": 0}
active_lock = threading.Lock()
level_windows: dict[int, dict[str, float]] = {}


def worker(worker_id: int):
    rng = random.Random(worker_id)
    # Session dédiée au thread, réutilisée sur tous ses appels — requests.post()
    # nu ouvre une connexion (+ TLS neuf en HTTPS) à chaque appel, invisible en
    # local (localhost, pas de TLS) mais significatif contre une URL distante :
    # observé en conditions réelles sur berlue-llm, latence à 4 threads très
    # au-dessus du solo alors que 4 << NUM_PARALLEL (aucune contention GPU
    # attendue à ce niveau).
    session = requests.Session()
    while not stop_event.is_set():
        question = rng.choice(questions)
        prompt = f"{question}\n\n[Instruction: {INSTRUCTION}]"
        with level_lock:
            level = current_level["n"]
        with active_lock:
            active_requests["n"] += 1
        start = time.monotonic()
        try:
            resp = session.post(
                f"{OLLAMA_HOST}/api/generate",
                json={"model": MODEL, "prompt": prompt, "stream": False, "options": {"num_predict": NUM_PREDICT}},
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT_S,
            )
            elapsed = time.monotonic() - start
            resp.raise_for_status()
            body = resp.json()
            if not body.get("response"):
                raise ValueError("réponse vide")
            with stats_lock:
                stats[level]["success"] += 1
                stats[level]["latencies"].append(elapsed)
                stats[level]["tokens"] += body.get("eval_count", 0)
        except requests.exceptions.Timeout:
            with stats_lock:
                stats[level]["timeout"] += 1
        except Exception as e:
            with stats_lock:
                stats[level]["error"] += 1
            print(f"  ⚠️  [niveau {level}] erreur thread {worker_id}: {type(e).__name__}: {e}")
        finally:
            with active_lock:
                active_requests["n"] -= 1


def set_level(level: int):
    now = time.monotonic()
    with level_lock:
        prev = current_level["n"]
        if prev in level_windows:
            level_windows[prev]["end"] = now
        current_level["n"] = level
        level_windows[level] = {"start": now, "end": None}


def print_level_summary(level: int):
    with stats_lock:
        s = stats[level]
        lat = s["latencies"]
        tok = s["tokens"]
    total = s["success"] + s["timeout"] + s["error"]
    if total == 0:
        print(f"  niveau {level:2d} : (aucune requête terminée pour l'instant)")
        return
    avg = sum(lat) / len(lat) if lat else 0.0
    p95 = sorted(lat)[int(len(lat) * 0.95)] if lat else 0.0
    with active_lock:
        inflight = active_requests["n"]
    print(
        f"  niveau {level:2d} : {s['success']:3d} ok, {s['timeout']:3d} timeout, "
        f"{s['error']:3d} erreur | latence avg={avg:.2f}s p95={p95:.2f}s | {tok:5d} tok cumulés | {inflight} en vol"
    )


def main():
    print(f"🔥 Warmup {MODEL}...")
    t0 = time.monotonic()
    requests.post(
        f"{OLLAMA_HOST}/api/generate",
        json={"model": MODEL, "prompt": "hi", "stream": False},
        headers=HEADERS,
        timeout=60,
    )
    print(f"✅ Warmup fait en {time.monotonic() - t0:.2f}s.\n")

    next_worker_id = 0
    threads = []

    def _spawn(n: int):
        nonlocal next_worker_id
        for _ in range(n):
            t = threading.Thread(target=worker, args=(next_worker_id,), daemon=True)
            t.start()
            threads.append(t)
            next_worker_id += 1

    level_windows[START_THREADS] = {"start": time.monotonic(), "end": None}
    _spawn(START_THREADS)
    print(
        f"🚀 Démarrage à {START_THREADS} threads, +{THREAD_STEP} toutes les "
        f"{RAMP_INTERVAL_S:.0f}s jusqu'à {MAX_THREADS}...\n"
    )

    level = START_THREADS
    while level < MAX_THREADS:
        time.sleep(RAMP_INTERVAL_S)
        print_level_summary(level)
        step = min(THREAD_STEP, MAX_THREADS - level)
        level += step
        set_level(level)
        _spawn(step)
        print(f"➕ Niveau {level} ({len(threads)} threads actifs)")

    print(f"\n⏸️  Palier à {MAX_THREADS} threads pendant {HOLD_AT_MAX_S:.0f}s...\n")
    held = 0.0
    while held < HOLD_AT_MAX_S:
        time.sleep(RAMP_INTERVAL_S)
        held += RAMP_INTERVAL_S
        print_level_summary(MAX_THREADS)

    stop_event.set()
    with level_lock:
        level_windows[current_level["n"]]["end"] = time.monotonic()
    print("\n🛑 Arrêt — attente de la fin des requêtes en vol (max 15s)...")
    time.sleep(min(REQUEST_TIMEOUT_S + 5, 15))

    print("\n" + "=" * 100)
    print("RAPPORT FINAL — par niveau de concurrence")
    print("=" * 100)
    for lvl in sorted(stats):
        s = stats[lvl]
        lat = s["latencies"]
        tok = s["tokens"]
        total = s["success"] + s["timeout"] + s["error"]
        avg = sum(lat) / len(lat) if lat else 0.0
        p50 = sorted(lat)[len(lat) // 2] if lat else 0.0
        p95 = sorted(lat)[int(len(lat) * 0.95)] if lat else 0.0
        fail_rate = 100 * (s["timeout"] + s["error"]) / total if total else 0.0
        window = level_windows.get(lvl)
        duration = (window["end"] - window["start"]) if window and window["end"] else 0.0
        throughput = tok / duration if duration > 0 else 0.0
        print(
            f"niveau {lvl:2d} | total={total:4d} | ok={s['success']:4d} | timeout={s['timeout']:3d} | "
            f"erreur={s['error']:3d} | échec={fail_rate:5.1f}% | "
            f"latence avg={avg:5.2f}s p50={p50:5.2f}s p95={p95:5.2f}s | "
            f"débit agrégé={throughput:6.1f} tok/s (fenêtre {duration:5.1f}s, {tok} tok)"
        )


if __name__ == "__main__":
    main()
