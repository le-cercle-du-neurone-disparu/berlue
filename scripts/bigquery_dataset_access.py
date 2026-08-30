"""Ajoute ou retire une entrée d'accès sur un dataset BigQuery — ACL
classique du dataset (`bq show`/`bq update --source=`), pas IAM :
`bq add-iam-policy-binding` sur un dataset nécessite un allowlisting non
actif sur ce projet. Usage interne à `make/bigquery.mk`
(`bigquery_grant`/`bigquery_revoke`), pas destiné à un appel direct.
"""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-ref", required=True, help="project:dataset")
    parser.add_argument("--user", required=True)
    parser.add_argument("--role", choices=["READER", "WRITER"], help="requis pour --action=grant")
    parser.add_argument("--action", required=True, choices=["grant", "revoke"])
    args = parser.parse_args()

    if args.action == "grant" and not args.role:
        parser.error("--role est requis pour --action=grant")

    current = json.loads(subprocess.check_output(["bq", "show", "--format=prettyjson", args.dataset_ref]))
    access = [entry for entry in current["access"] if entry.get("userByEmail") != args.user]
    if args.action == "grant":
        access.append({"role": args.role, "userByEmail": args.user})

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"access": access}, f)
        path = Path(f.name)
    try:
        subprocess.run(["bq", "update", f"--source={path}", args.dataset_ref], check=True)
    finally:
        path.unlink()


if __name__ == "__main__":
    main()
