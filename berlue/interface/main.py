import numpy as np
import pandas as pd

from berlue.ml_logic.registry import mlflow_run


def preprocess() -> None:
    pass
    # print("✅ preprocess() terminé \n")


@mlflow_run
def train(
    # min_date:str = '2009-01-01',
    # max_date:str = '2015-01-01',
    split_ratio: float,
    learning_rate,
    batch_size,
    patience,
) -> float:
    """
    - Télécharge les données traitées depuis votre table BQ (ou depuis le cache si il existe)
    - Entraîne sur le dataset prétraité (qui doit être ordonné par date)
    - Stocke les résultats d'entraînement et les poids du modèle

    Retourne XXX en float
    """

    # print(Fore.MAGENTA + "\n⭐️ Use case: train" + Style.RESET_ALL)
    # print(Fore.BLUE + "\nChargement des données de validation prétraitées..." + Style.RESET_ALL)
    pass


@mlflow_run
def evaluate(
    # min_date:str = '2014-01-01',
    # max_date:str = '2015-01-01',
    stage: str = "Production",
) -> float:
    """
    Évalue la performance du dernier modèle de production sur les données traitées
    Retourne XXX en float
    """
    # print(Fore.MAGENTA + "\n⭐️ Use case: evaluate" + Style.RESET_ALL)

    # model = load_model(stage=stage)
    # assert model is not None

    # Interroge votre table BigQuery traitée et récupère data_processed via `get_data_with_cache`
    # query = f""""""

    # data_processed_cache_path = Path(f"{LOCAL_DATA_PATH}/processed/processed_{min_date}_{max_date}_{DATA_SIZE}.csv")
    # data_processed = get_data_with_cache(
    #     gcp_project=GCP_PROJECT,
    #     query=query,
    #     cache_path=data_processed_cache_path,
    #     data_has_header=False
    # )

    # if data_processed.shape[0] == 0:
    #     print("❌ Aucune donnée à évaluer")
    #     return None

    # data_processed = data_processed.to_numpy()

    # X_new = data_processed[:, :-1]
    # y_new = data_processed[:, -1]

    # metrics_dict = evaluate_model(model=model, X=X_new, y=y_new)
    # XXX = metrics_dict["XXX"]

    # params = dict(
    #     context="evaluate", # Comportement du package
    #     training_set_size=DATA_SIZE,
    #     row_count=len(X_new)
    # )

    # save_results(params=params, metrics=metrics_dict)

    # print("✅ evaluate() terminé \n")

    # return XXX


def pred(X_pred: pd.DataFrame = None) -> np.ndarray:
    """
    Effectue une prédiction avec le dernier modèle entraîné
    """

    # print("\n⭐️ Use case: predict")

    # if X_pred is None:
    #     X_pred = pd.DataFrame(dict(
    #     # vos paramètres
    # ))

    # model = load_model()
    # assert model is not None

    # X_processed = preprocess_features(X_pred)
    # y_pred = model.predict(X_processed)

    # print("\n✅ prédiction terminée : ", y_pred, y_pred.shape, "\n")
    # return y_pred
    pass


if __name__ == "__main__":
    # preprocess()
    # train()
    # evaluate()
    # pred()
    pass
