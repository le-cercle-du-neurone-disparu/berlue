import numpy as np
import pandas as pd

from pathlib import Path
from colorama import Fore, Style
from dateutil.parser import parse

from berlue.params import *
from berlue.ml_logic.data import get_data_with_cache, clean_data, load_data_to_bq
from berlue.ml_logic.model import initialize_model, compile_model, train_model, evaluate_model
from berlue.ml_logic.preprocessor import preprocess_features
from berlue.ml_logic.registry import load_model, save_model, save_results
from berlue.ml_logic.registry import mlflow_run, mlflow_transition_model

def preprocess() -> None:
    pass
    # print("✅ preprocess() done \n")

@mlflow_run
def train(
        # min_date:str = '2009-01-01',
        # max_date:str = '2015-01-01',
        split_ratio: float,
        learning_rate,
        batch_size,
        patience
    ) -> float:

    """
    - Download processed data from your BQ table (or from cache if it exists)
    - Train on the preprocessed dataset (which should be ordered by date)
    - Store training results and model weights

    Return XXX as a float
    """

    # print(Fore.MAGENTA + "\n⭐️ Use case: train" + Style.RESET_ALL)
    # print(Fore.BLUE + "\nLoading preprocessed validation data..." + Style.RESET_ALL)
    pass


@mlflow_run
def evaluate(
        # min_date:str = '2014-01-01',
        # max_date:str = '2015-01-01',
        stage: str = "Production"
    ) -> float:
    """
    Evaluate the performance of the latest production model on processed data
    Return XXX as a float
    """
    # print(Fore.MAGENTA + "\n⭐️ Use case: evaluate" + Style.RESET_ALL)

    # model = load_model(stage=stage)
    # assert model is not None

    # Query your BigQuery processed table and get data_processed using `get_data_with_cache`
    # query = f""""""

    # data_processed_cache_path = Path(f"{LOCAL_DATA_PATH}/processed/processed_{min_date}_{max_date}_{DATA_SIZE}.csv")
    # data_processed = get_data_with_cache(
    #     gcp_project=GCP_PROJECT,
    #     query=query,
    #     cache_path=data_processed_cache_path,
    #     data_has_header=False
    # )

    # if data_processed.shape[0] == 0:
    #     print("❌ No data to evaluate on")
    #     return None

    # data_processed = data_processed.to_numpy()

    # X_new = data_processed[:, :-1]
    # y_new = data_processed[:, -1]

    # metrics_dict = evaluate_model(model=model, X=X_new, y=y_new)
    # XXX = metrics_dict["XXX"]

    # params = dict(
    #     context="evaluate", # Package behavior
    #     training_set_size=DATA_SIZE,
    #     row_count=len(X_new)
    # )

    # save_results(params=params, metrics=metrics_dict)

    # print("✅ evaluate() done \n")

    # return XXX


def pred(X_pred: pd.DataFrame = None) -> np.ndarray:
    """
    Make a prediction using the latest trained model
    """

    # print("\n⭐️ Use case: predict")

    # if X_pred is None:
    #     X_pred = pd.DataFrame(dict(
    #     # your params
    # ))

    # model = load_model()
    # assert model is not None

    # X_processed = preprocess_features(X_pred)
    # y_pred = model.predict(X_processed)

    # print("\n✅ prediction done: ", y_pred, y_pred.shape, "\n")
    # return y_pred
    pass

if __name__ == '__main__':
    # preprocess()
    # train()
    # evaluate()
    # pred()
    pass
