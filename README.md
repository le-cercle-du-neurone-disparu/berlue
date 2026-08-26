# 🚀 Template Boilerplate MLOps

Un template robuste et agnostique au framework pour démarrer rapidement vos projets Machine Learning avec les bonnes pratiques d'ingénierie logicielle, de CI/CD et de déploiement GCP.

## 🛠️ 1. Configuration de l'environnement local

Configure automatiquement votre environnement virtuel Python avec `pyenv` et installe le package avec toutes ses dépendances :

```bash
make local_setup
```

---

## 🌐 2. Mise en service & API

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
*Vérifiez votre API conteneurisée :*
```bash
make test_functional
```

### Étape 3 : Déploiement Cloud (test → staging → prod)
Une fois le conteneur local validé, construisez l'image de production (qui utilise `pip install .` pour un poids plus léger) et déployez-la sur 3 environnements Cloud Run (test → staging → prod), une seule image promue progressivement.

Voir `docs/gcp-deployment.md` pour toutes les commandes (authentification, build/push, déploiement par environnement) ainsi que l'architecture multi-projets, la gestion d'accès par personne, et comment tout supprimer (`make gcp_destroy`).

*Vérifiez votre endpoint en direct* : test d'intégration dédié à venir (cf. `README.tests.md`).
