import glob
import logging
import os
import pickle
import time

import mlflow
from mlflow.tracking import MlflowClient

from berlue.params import (
    LOCAL_REGISTRY_PATH,
    MLFLOW_EXPERIMENT,
    MLFLOW_MODEL_NAME,
    MLFLOW_TRACKING_URI,
    MODEL_TARGET,
)

logger = logging.getLogger(__name__)


def save_results(params: dict, metrics: dict) -> None:
    """
    Persiste les params & métriques localement sur le disque dur.
    Si MODEL_TARGET='mlflow', les persiste aussi sur MLflow.
    """
    timestamp = time.strftime("%Y%m%d-%H%M%S")

    # 1. Sauvegarde locale
    if params is not None:
        params_path = os.path.join(LOCAL_REGISTRY_PATH, "params", f"{timestamp}.pickle")
        os.makedirs(os.path.dirname(params_path), exist_ok=True)
        with open(params_path, "wb") as file:
            pickle.dump(params, file)

    if metrics is not None:
        metrics_path = os.path.join(LOCAL_REGISTRY_PATH, "metrics", f"{timestamp}.pickle")
        os.makedirs(os.path.dirname(metrics_path), exist_ok=True)
        with open(metrics_path, "wb") as file:
            pickle.dump(metrics, file)

    logger.info("✅ Résultats sauvegardés localement")

    # 2. Sauvegarde sur MLflow
    if MODEL_TARGET == "mlflow":
        if params is not None:
            mlflow.log_params(params)
        if metrics is not None:
            mlflow.log_metrics(metrics)
        logger.info("✅ Résultats sauvegardés sur MLflow")


def save_model(model) -> None:
    """
    Persiste le modèle entraîné localement sur le disque dur.
    - si MODEL_TARGET='gcs', le persiste aussi dans le bucket GCS
    - si MODEL_TARGET='mlflow', le persiste aussi sur MLflow
    """
    timestamp = time.strftime("%Y%m%d-%H%M%S")  # noqa: F841 -- utilisé par le code commenté ci-dessous

    # TODO: Modifier la logique de sauvegarde selon le framework choisi (Scikit-Learn, Keras, PyTorch...)
    # Exemple pour Scikit-Learn :
    # model_path = os.path.join(LOCAL_REGISTRY_PATH, "models", f"{timestamp}.pkl")
    # os.makedirs(os.path.dirname(model_path), exist_ok=True)
    # with open(model_path, "wb") as file:
    #     pickle.dump(model, file)
    # print("✅ Modèle sauvegardé localement")

    if MODEL_TARGET == "gcs":
        # TODO: Implémenter la logique d'upload vers GCS
        # print("✅ Modèle sauvegardé sur GCS")
        raise NotImplementedError("La sauvegarde du modèle sur GCS n'est pas encore implémentée.")

    if MODEL_TARGET == "mlflow":
        # TODO: Modifier le log mlflow selon le framework (mlflow.sklearn, mlflow.tensorflow...)
        # mlflow.sklearn.log_model(
        #     sk_model=model,
        #     artifact_path="model",
        #     registered_model_name=MLFLOW_MODEL_NAME
        # )
        # print("✅ Modèle sauvegardé sur MLflow")
        raise NotImplementedError("La sauvegarde du modèle sur MLflow n'est pas encore implémentée.")


def load_model(stage="Production"):
    """
    Retourne un modèle sauvegardé :
    - localement (le plus récent par ordre alphabétique)
    - ou depuis GCS (le plus récent) si MODEL_TARGET=='gcs'
    - ou depuis MLFLOW (par "stage") si MODEL_TARGET=='mlflow'
    """
    if MODEL_TARGET == "local":
        logger.info("Chargement du dernier modèle depuis le registry local...")

        local_model_directory = os.path.join(LOCAL_REGISTRY_PATH, "models")
        local_model_paths = glob.glob(f"{local_model_directory}/*")

        if not local_model_paths:
            logger.warning("❌ Aucun modèle local trouvé")
            return None

        most_recent_model_path_on_disk = sorted(local_model_paths)[-1]  # noqa: F841 -- utilisé par le code commenté ci-dessous

        # TODO: Modifier la logique de chargement selon le framework choisi
        # Exemple pour Scikit-Learn :
        # with open(most_recent_model_path_on_disk, "rb") as file:
        #     latest_model = pickle.load(file)
        # print("✅ Modèle chargé depuis le disque local (TODO)")
        # return latest_model

        raise NotImplementedError(
            "Le chargement du modèle depuis le disque local n'est pas encore implémenté. Voir TODO."
        )

    elif MODEL_TARGET == "gcs":
        # TODO: Implémenter la logique de téléchargement depuis GCS
        # print("✅ Dernier modèle téléchargé depuis GCS (TODO)")
        raise NotImplementedError("Le chargement du modèle depuis GCS n'est pas encore implémenté.")

    elif MODEL_TARGET == "mlflow":
        # TODO: Implémenter la logique de téléchargement depuis MLflow
        # print(Fore.BLUE + f"\nChargement du modèle [{stage}] depuis MLflow..." + Style.RESET_ALL)
        # model = ...
        # return model
        raise NotImplementedError("Le chargement du modèle depuis MLflow n'est pas encore implémenté.")

    return None


def mlflow_transition_model(current_stage: str, new_stage: str) -> None:
    """
    Fait passer le dernier modèle du `current_stage` au
    `new_stage` et archive le modèle déjà présent dans `new_stage`.
    """
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

    client = MlflowClient()

    version = client.get_latest_versions(name=MLFLOW_MODEL_NAME, stages=[current_stage])

    if not version:
        logger.warning("❌ Aucun modèle trouvé avec le nom %s dans le stage %s", MLFLOW_MODEL_NAME, current_stage)
        return None

    client.transition_model_version_stage(
        name=MLFLOW_MODEL_NAME, version=version[0].version, stage=new_stage, archive_existing_versions=True
    )

    logger.info(
        "✅ Modèle %s (version %s) transféré de %s vers %s",
        MLFLOW_MODEL_NAME,
        version[0].version,
        current_stage,
        new_stage,
    )

    return None


def mlflow_run(func):
    """
    Fonction générique pour logger les params et résultats vers MLflow, avec
    l'auto-logging universel.

    Args:
        - func (function): Fonction que vous voulez exécuter dans le run MLflow
    """

    def wrapper(*args, **kwargs):
        # Termine tout run actif pour éviter les conflits
        if mlflow.active_run():
            mlflow.end_run()

        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        mlflow.set_experiment(experiment_name=MLFLOW_EXPERIMENT)

        with mlflow.start_run():
            # L'autolog universel fonctionne pour TensorFlow, Scikit-learn, XGBoost, etc.
            mlflow.autolog()
            results = func(*args, **kwargs)

        logger.info("✅ Auto-log mlflow_run terminé")

        return results

    return wrapper
