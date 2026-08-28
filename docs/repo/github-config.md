# Configuration GitHub du dépôt

## Protection de la branche `main`

Un ruleset GitHub nommé `main-force-MR` est actif sur `main`. Il interdit :

- tout push direct sur `main` (en imposant qu'une Pull Request soit utilisée) ;
- le force-push sur `main` ;
- la suppression de `main`.

Et impose, pour toute PR vers `main` :

- au moins **1 review d'approbation** ;
- une review des code owners (`require_code_owner_review`) — actuellement un
  no-op, le dépôt n'a pas de fichier `CODEOWNERS` ;
- les reviews existantes ne sont **pas** dismissées automatiquement sur un
  nouveau push (`dismiss_stale_reviews_on_push: false`) ;
- méthodes de merge autorisées : merge, squash, rebase.

Personne ne peut bypasser ce ruleset (`bypass_actors: []`).

### Consulter le ruleset actif

```bash
gh api repos/le-cercle-du-neurone-disparu/berlue/rulesets
# puis, avec l'id récupéré :
gh api repos/le-cercle-du-neurone-disparu/berlue/rulesets/<id>
```

### Créer ce ruleset sur un dépôt

Nécessite d'être admin du dépôt (ou org owner).

```bash
gh api repos/le-cercle-du-neurone-disparu/berlue/rulesets \
  --method POST \
  --input - <<'EOF'
{
  "name": "main-force-MR",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/main"],
      "exclude": []
    }
  },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 1,
        "dismiss_stale_reviews_on_push": false,
        "required_reviewers": [],
        "require_code_owner_review": true,
        "dismissal_restriction": { "enabled": false, "allowed_actors": [] },
        "require_last_push_approval": false,
        "required_review_thread_resolution": false,
        "require_extra_approval_for_unattributed_changes": false,
        "allowed_merge_methods": ["merge", "squash", "rebase"]
      }
    }
  ],
  "bypass_actors": []
}
EOF
```

Note : c'est possible aussi en clic, clic sur l'interface.
