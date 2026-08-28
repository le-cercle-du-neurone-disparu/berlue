# Notification Slack quand une PR passe en `toreview`

## Objectif

Dès qu'une Pull Request du repo reçoit le label **`toreview`**, un message est posté
automatiquement dans **`#batch-2327-berlue`** (titre de la PR, auteur, bouton vers la
PR).

Côté repo, poser/retirer ce label se fait via `make/github.mk` :

```bash
make gh_pr_toreview  # ajoute le label toreview sur la PR de la branche courante
make gh_pr_wip       # le retire (retour en WIP)
```

## Pourquoi une Slack App classique n'a pas fonctionné

L'approche standard aurait été une **Incoming Webhook** créée via une Slack App
(api.slack.com/apps). Mais le workspace **Le Wagon - Alumni** interdit l'installation
d'apps custom aux comptes non-admin :

> You don't have permission to install apps in Le Wagon - Alumni.

On est donc passés par **Slack Workflow Builder**, qui est natif à Slack (pas une app
tierce) : n'importe quel membre du channel peut y créer un flux de travail déclenché
par un webhook, sans validation d'admin.

## Ce qui a été mis en place côté Slack

Dans le channel `#batch-2327-berlue` → **Automations / Ajouter un flux de travail** →
flux nommé **"Github neurone disparu"** :

- **Déclencheur** : *Depuis un webhook*, avec 3 variables de données (toutes en type
  `Texte`) :
  - `pr_title`
  - `pr_author`
  - `pr_url`
- **Étape** : *Envoyer un message* dans `#batch-2327-berlue` :
  ```
  👀 PR prête pour review : {pr_title} par {pr_author}
  [GO]  ← bouton dont l'URL est branchée sur la variable pr_url
  ```
- Le flux est **publié**, ce qui génère une URL de requête web (webhook) :
  `https://hooks.slack.com/triggers/...`.

⚠️ Cette URL équivaut à un mot de passe : quiconque la connaît peut déclencher le
flux de travail (poster dans le channel). Elle n'est stockée nulle part dans le repo
en clair — voir section suivante.

## Ce qui a été mis en place côté GitHub

### Secret

L'URL du webhook est stockée comme **Secret** (chiffré, masqué dans les logs) sur le
repo — jamais comme "Variable" (en clair, repo public) :

```bash
gh secret set SLACK_WEBHOOK_URL -R le-cercle-du-neurone-disparu/berlue
```

### Workflow GitHub Actions

`.github/workflows/notify-toreview.yml` :
- Se déclenche sur `pull_request` de type `labeled`.
- Filtré par `if: github.event.label.name == 'toreview'` — ne réagit qu'à ce label
  précis (pas aux autres labels, pas à `unlabeled`).
- Utilise `slackapi/slack-github-action@v2.0.0` avec `webhook-type: webhook-trigger`
  (le mode pour un webhook Workflow Builder, différent du mode `incoming-webhook`
  classique).
- Envoie un payload JSON avec les 3 clés attendues par le flux Slack :
  ```json
  {
    "pr_title": "...",
    "pr_author": "...",
    "pr_url": "..."
  }
  ```

## Limite connue

GitHub ne transmet **pas** les secrets aux workflows déclenchés par une `pull_request`
venant d'un fork externe (protection anti-exfiltration standard). Si un jour une PR
externe (hors collaborateurs du repo) reçoit le label `toreview`, la notification ne
partira pas — le secret sera vide dans ce run. Sans impact pour une équipe interne,
à garder en tête si le repo reçoit des contributions externes.

## Pour reproduire / maintenir

- **Changer de channel de destination** : rouvrir le flux de travail dans Slack →
  modifier l'étape "Envoyer un message" → republier. Aucun changement côté GitHub
  nécessaire (l'URL du webhook ne change pas).
- **Régénérer l'URL du webhook** (si compromise) : dans le flux de travail Slack,
  rouvrir le bloc déclencheur → il n'y a pas de rotation directe, il faut recréer le
  flux ou supprimer/recréer le déclencheur, puis mettre à jour le secret GitHub avec
  la nouvelle URL (commande plus haut, section « Secret »).
- **Ajouter une variable au message** (ex. les reviewers) : ajouter la clé côté
  déclencheur Slack, l'utiliser dans le message, puis ajouter la clé correspondante
  dans le `payload` du step GitHub Actions.
