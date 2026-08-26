# 🚀 Template Boilerplate MLOps

Un template robuste et agnostique au framework pour démarrer rapidement vos projets Machine Learning avec les bonnes pratiques d'ingénierie logicielle, de CI/CD et de déploiement GCP.

## 🛠️ 1. Configuration de l'environnement local

Configure automatiquement votre environnement virtuel Python avec `pyenv` et installe le package avec toutes ses dépendances :

```bash
make local_setup
```

---

## ☁️ 2. Infrastructure Cloud (VM GCP)

Pour entraîner votre modèle sur une machine cloud puissante, provisionnez votre VM Google Cloud Platform directement depuis votre terminal local :

1. Créez la VM et assignez le compte de service :
```bash
make vm_create
```

2. Envoyez et exécutez le script de configuration de l'environnement (`setup_vm.sh`) sur la VM :
```bash
make vm_setup
```

3. Connectez-vous à votre nouvelle VM :
```bash
make vm_connect
```

*(Note : une fois connecté à la VM via SSH, vous y clonerez votre dépôt et lancerez `make local_setup` pour préparer votre environnement d'entraînement, tout comme en local).*

### 🛑 Gestion des ressources (éviter une facturation superflue)
**Crucial :** n'oubliez pas d'arrêter votre VM quand vous avez fini de travailler pour la journée, pour économiser les coûts CPU !

```bash
# Arrête la VM (économise de l'argent, conserve vos fichiers)
make vm_stop

# Reprend le travail le jour suivant
make vm_start

# Quand le projet est entièrement terminé, supprime la VM définitivement
make vm_delete
```

---

## 🧠 3. Workflow de développement (logique ML)

La logique métier de votre projet vit dans le dossier du package fraîchement renommé. Suivez ces étapes pour construire votre pipeline :

1. **`params.py`** : configurez vos types de données, colonnes et constantes.
2. **`ml_logic/data.py`** : implémentez `clean_data()` pour prétraiter vos données brutes.
3. **`ml_logic/preprocessor.py`** : construisez vos pipelines sklearn/custom.
4. **`ml_logic/model.py`** : implémentez `build_model()`, `train_model()` et `evaluate_model()`.
5. **`ml_logic/registry.py`** : implémentez la gestion du cycle de vie du modèle et l'intégration **MLflow** pour suivre vos expériences et métriques.

### Exécution étape par étape
Une fois votre logique implémentée, lancez les étapes de votre pipeline indépendamment via le Makefile :

```bash
make run_preprocess
make run_train
make run_evaluate
make run_pred

# Ou lancez tout le pipeline d'un coup :
make run_all
```

### 🤖 Orchestration (Prefect)
Pour automatiser, surveiller et planifier tout votre pipeline MLOps, implémentez vos tâches dans `interface/workflow.py` et lancez l'orchestrateur :

```bash
make run_workflow
```

---

## 🌐 4. Mise en service & API

Le déploiement de votre API suit un processus de validation strict en 3 étapes (méthodologie Fail-Fast) :

### Étape 1 : Développement natif local
Implémentez vos endpoints FastAPI dans `api/fast.py`. Lancez l'API nativement sur votre machine pour une itération rapide et un rechargement à chaud :
```bash
make run_api
```
*Vérifiez la logique de votre code :*
```bash
make test_fast
```

### Étape 2 : Vérification Docker locale
Une fois l'API native fonctionnelle, assurez-vous qu'elle tourne correctement dans son conteneur isolé. Cela permet de détecter les dépendances manquantes avant le déploiement dans le cloud.
```bash
make docker_build_local
make docker_run_local
```
*Vérifiez votre API conteneurisée* : test d'intégration dédié à venir (cf. `README.tests.md`).

### Étape 3 : Déploiement en production Cloud
Une fois le conteneur local validé, construisez l'image de production (qui utilise `pip install .` pour un poids plus léger) et déployez-la sur GCP Cloud Run.
```bash
make docker_build_prod
make docker_push
make cloudrun_deploy
```
*Vérifiez votre endpoint de production en direct* : test d'intégration dédié à venir (cf. `README.tests.md`).
