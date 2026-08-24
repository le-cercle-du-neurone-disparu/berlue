import glob
import os
import time
import pickle

from colorama import Fore, Style
from google.cloud import storage
import mlflow
from mlflow.tracking import MlflowClient

# TODO: Replace "package_name" with the actual dynamic package name,
# or use relative imports (e.g., from .params import *)
from berlue.params import *

def save_results(params: dict, metrics: dict) -> None:
    """
    Persist params & metrics locally on the hard drive.
    If MODEL_TARGET='mlflow', also persist them on MLflow.
    """
    timestamp = time.strftime("%Y%m%d-%H%M%S")

    # 1. Save locally
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

    print("✅ Results saved locally")

    # 2. Save on MLflow
    if MODEL_TARGET == "mlflow":
        if params is not None:
            mlflow.log_params(params)
        if metrics is not None:
            mlflow.log_metrics(metrics)
        print("✅ Results saved on MLflow")


def save_model(model) -> None:
    """
    Persist trained model locally on the hard drive.
    - if MODEL_TARGET='gcs', also persist it in the GCS bucket
    - if MODEL_TARGET='mlflow', also persist it on MLflow
    """
    timestamp = time.strftime("%Y%m%d-%H%M%S")

    # TODO: Modify the saving logic depending on the chosen framework (Scikit-Learn, Keras, PyTorch...)
    # Example for Scikit-Learn:
    # model_path = os.path.join(LOCAL_REGISTRY_PATH, "models", f"{timestamp}.pkl")
    # os.makedirs(os.path.dirname(model_path), exist_ok=True)
    # with open(model_path, "wb") as file:
    #     pickle.dump(model, file)
    # print("✅ Model saved locally")

    if MODEL_TARGET == "gcs":
        # TODO: Implement GCS upload logic
        # print("✅ Model saved to GCS")
        raise NotImplementedError("Saving model to GCS is not implemented yet.")

    if MODEL_TARGET == "mlflow":
        # TODO: Modify the mlflow log depending on the framework (mlflow.sklearn, mlflow.tensorflow...)
        # mlflow.sklearn.log_model(
        #     sk_model=model,
        #     artifact_path="model",
        #     registered_model_name=MLFLOW_MODEL_NAME
        # )
        # print("✅ Model saved to MLflow")
        raise NotImplementedError("Saving model to MLflow is not implemented yet.")


def load_model(stage="Production"):
    """
    Return a saved model:
    - locally (latest one in alphabetical order)
    - or from GCS (most recent one) if MODEL_TARGET=='gcs'
    - or from MLFLOW (by "stage") if MODEL_TARGET=='mlflow'
    """
    if MODEL_TARGET == "local":
        print(Fore.BLUE + f"\nLoad latest model from local registry..." + Style.RESET_ALL)

        local_model_directory = os.path.join(LOCAL_REGISTRY_PATH, "models")
        local_model_paths = glob.glob(f"{local_model_directory}/*")

        if not local_model_paths:
            print("❌ No local model found")
            return None

        most_recent_model_path_on_disk = sorted(local_model_paths)[-1]

        # TODO: Modify the loading logic depending on the chosen framework
        # Example for Scikit-Learn:
        # with open(most_recent_model_path_on_disk, "rb") as file:
        #     latest_model = pickle.load(file)
        # print("✅ Model loaded from local disk (TODO)")
        # return latest_model

        raise NotImplementedError("Loading model from local disk is not implemented yet. See TODO.")

    elif MODEL_TARGET == "gcs":
        # TODO: Implement GCS download logic
        # print("✅ Latest model downloaded from GCS (TODO)")
        raise NotImplementedError("Loading model from GCS is not implemented yet.")

    elif MODEL_TARGET == "mlflow":
        # TODO: Implement MLflow download logic
        # print(Fore.BLUE + f"\nLoad [{stage}] model from MLflow..." + Style.RESET_ALL)
        # model = ...
        # return model
        raise NotImplementedError("Loading model from MLflow is not implemented yet.")

    return None
