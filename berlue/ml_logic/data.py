from pathlib import Path

import pandas as pd
from colorama import Fore, Style
from google.cloud import bigquery

from berlue.params import *


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean raw data by:
    - assigning correct dtypes to each column
    - removing buggy or irrelevant transactions
    """
    # TODO: Implement clean_data
    # Compress raw_data by setting types to DTYPES_RAW
    # df = df.astype(DTYPES_RAW)

    # # Remove buggy data
    # df = df.drop_duplicates()
    # df = df.dropna(how='any', axis=0)

    # print("✅ Data cleaned")
    # return df

    raise NotImplementedError("clean_data is not implemented yet. See TODO.")

def get_data_with_cache(
        gcp_project: str,
        query: str,
        cache_path: Path,
        data_has_header=True
    ) -> pd.DataFrame:
    """
    Retrieve `query` data from BigQuery, or from `cache_path` if the file exists.
    Store at `cache_path` if retrieved from BigQuery for future use.
    """
    if cache_path.is_file():
        print(Fore.BLUE + "\nLoad data from local CSV..." + Style.RESET_ALL)
        df = pd.read_csv(cache_path, header='infer' if data_has_header else None)
    else:
        print(Fore.BLUE + "\nLoad data from BigQuery server..." + Style.RESET_ALL)
        client = bigquery.Client(project=gcp_project)
        query_job = client.query(query)
        result = query_job.result()
        df = result.to_dataframe()

        # Store as CSV if the BQ query returned at least one valid line
        if df.shape[0] > 1:
            # 💡 Astuce de pro : on s'assure que le dossier parent existe avant de sauvegarder !
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(cache_path, header=data_has_header, index=False)

    print(f"✅ Data loaded, with shape {df.shape}")

    return df

def load_data_to_bq(
        data: pd.DataFrame,
        gcp_project: str,
        bq_dataset: str,
        table: str,
        truncate: bool
    ) -> None:
    """
    - Save the DataFrame to BigQuery
    - Empty the table beforehand if `truncate` is True, append otherwise
    """
    assert isinstance(data, pd.DataFrame)
    full_table_name = f"{gcp_project}.{bq_dataset}.{table}"
    print(Fore.BLUE + f"\nSave data to BigQuery @ {full_table_name}...:" + Style.RESET_ALL)

    # Fix column names to BigQuery accepted format (cannot start with a number)
    data.columns = [
        f"_{column}" if not str(column)[0].isalpha() and not str(column)[0] == "_" else str(column)
        for column in data.columns
    ]

    client = bigquery.Client()

    # Define write mode and schema
    write_mode = "WRITE_TRUNCATE" if truncate else "WRITE_APPEND"
    job_config = bigquery.LoadJobConfig(write_disposition=write_mode)

    print(f"\n{'Write' if truncate else 'Append'} {full_table_name} ({data.shape[0]} rows)")

    # Load data
    job = client.load_table_from_dataframe(data, full_table_name, job_config=job_config)
    job.result()  # wait for the job to complete

    print(f"✅ Data saved to bigquery, with shape {data.shape}")
