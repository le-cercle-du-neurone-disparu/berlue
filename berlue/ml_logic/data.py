import logging
from pathlib import Path

import pandas as pd
from google.cloud import bigquery

logger = logging.getLogger(__name__)


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Nettoie les données brutes en :
    - assignant les dtypes corrects à chaque colonne
    - supprimant les transactions buguées ou non pertinentes
    """
    # TODO: Implémenter clean_data
    # Compresse raw_data en assignant les types de DTYPES_RAW
    # df = df.astype(DTYPES_RAW)

    # # Supprime les données buguées
    # df = df.drop_duplicates()
    # df = df.dropna(how='any', axis=0)

    # print("✅ Données nettoyées")
    # return df

    raise NotImplementedError("clean_data n'est pas encore implémenté. Voir TODO.")


def get_data_with_cache(gcp_project: str, query: str, cache_path: Path, data_has_header=True) -> pd.DataFrame:
    """
    Récupère les données de `query` depuis BigQuery, ou depuis `cache_path` si le fichier existe.
    Stocke dans `cache_path` si récupéré depuis BigQuery, pour une utilisation future.
    """
    if cache_path.is_file():
        logger.info("Chargement des données depuis le CSV local...")
        df = pd.read_csv(cache_path, header="infer" if data_has_header else None)
    else:
        logger.info("Chargement des données depuis le serveur BigQuery...")
        client = bigquery.Client(project=gcp_project)
        query_job = client.query(query)
        result = query_job.result()
        df = result.to_dataframe()

        # Stocke en CSV si la requête BQ a retourné au moins une ligne valide
        if df.shape[0] > 1:
            # 💡 Astuce de pro : on s'assure que le dossier parent existe avant de sauvegarder !
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(cache_path, header=data_has_header, index=False)

    logger.info("✅ Données chargées, avec la forme %s", df.shape)

    return df


def load_data_to_bq(data: pd.DataFrame, gcp_project: str, bq_dataset: str, table: str, truncate: bool) -> None:
    """
    - Sauvegarde le DataFrame dans BigQuery
    - Vide la table au préalable si `truncate` vaut True, sinon ajoute à la suite
    """
    assert isinstance(data, pd.DataFrame)
    full_table_name = f"{gcp_project}.{bq_dataset}.{table}"
    logger.info("Sauvegarde des données dans BigQuery @ %s...:", full_table_name)

    # Corrige les noms de colonnes au format accepté par BigQuery (ne peut pas commencer par un chiffre)
    data.columns = [
        f"_{column}" if not str(column)[0].isalpha() and not str(column)[0] == "_" else str(column)
        for column in data.columns
    ]

    client = bigquery.Client()

    # Définit le mode d'écriture et le schéma
    write_mode = "WRITE_TRUNCATE" if truncate else "WRITE_APPEND"
    job_config = bigquery.LoadJobConfig(write_disposition=write_mode)

    logger.info("%s %s (%d lignes)", "Écriture de" if truncate else "Ajout à", full_table_name, data.shape[0])

    # Charge les données
    job = client.load_table_from_dataframe(data, full_table_name, job_config=job_config)
    job.result()  # attend la fin du job

    logger.info("✅ Données sauvegardées dans bigquery, avec la forme %s", data.shape)
