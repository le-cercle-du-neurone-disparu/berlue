from datetime import datetime

import requests
from dateutil.relativedelta import relativedelta
from prefect import flow, task

from berlue.interface.main import evaluate, preprocess, train
from berlue.params import (
    EVALUATION_START_DATE,
    NOTIFY_AUTHOR,
    NOTIFY_BASE_URL,
    NOTIFY_CHANNEL,
    PREFECT_FLOW_NAME,
)


@task
def preprocess_new_data(min_date: str, max_date: str):
    return preprocess(min_date=min_date, max_date=max_date)


@task
def evaluate_production_model(min_date: str, max_date: str):
    return evaluate(min_date=min_date, max_date=max_date)


@task
def re_train(min_date: str, max_date: str, split_ratio: str):
    return train(min_date=min_date, max_date=max_date, split_ratio=split_ratio)


@task
def transition_model(current_stage: str, new_stage: str):
    # TODO: mlflow_transition_model n'est pas encore défini dans registry.py
    # return mlflow_transition_model(current_stage=current_stage, new_stage=new_stage)
    raise NotImplementedError("mlflow_transition_model n'est pas encore implémenté.")


@task
def notify(old_mae, new_mae):
    """
    Notifie de la performance
    """
    url = f"{NOTIFY_BASE_URL}/{NOTIFY_CHANNEL}/messages"

    if new_mae < old_mae and new_mae < 2.5:
        content = (
            f"🚀 Nouveau modèle remplaçant l'ancien en production avec un MAE de : "
            f"{new_mae} l'ancien MAE était : {old_mae}"
        )
    elif old_mae < 2.5:
        content = f"✅ L'ancien modèle est encore assez bon : ancien MAE : {old_mae} - nouveau MAE : {new_mae}"
    else:
        content = f"🚨 Aucun modèle assez bon : ancien MAE : {old_mae} - nouveau MAE : {new_mae}"

    data = dict(author=NOTIFY_AUTHOR, content=content)

    response = requests.post(url, data=data)
    response.raise_for_status()


@flow(name=PREFECT_FLOW_NAME)
def train_flow():
    """
    Construit le workflow Prefect pour le package `berlue`. Il doit :
        - prétraiter 1 mois de nouvelles données, à partir de EVALUATION_START_DATE
        - calculer `old_mae` en évaluant le modèle de production actuel sur cette nouvelle période
        - calculer `new_mae` en ré-entraînant, puis en évaluant le nouveau modèle sur cette même période
        - si le nouveau est meilleur que l'ancien, remplacer le modèle de production actuel par le nouveau
        - si aucun des deux modèles n'est assez bon, envoyer une notification !
    """

    min_date = EVALUATION_START_DATE
    max_date = str(datetime.strptime(min_date, "%Y-%m-%d") + relativedelta(months=1)).split()[0]

    preprocessed = preprocess_new_data.submit(min_date=min_date, max_date=max_date)

    old_mae = evaluate_production_model.submit(min_date=min_date, max_date=max_date, wait_for=[preprocessed])
    new_mae = re_train.submit(min_date=min_date, max_date=max_date, split_ratio=0.2, wait_for=[preprocessed])

    old_mae = old_mae.result()
    new_mae = new_mae.result()

    if new_mae < old_mae:
        print(
            f"🚀 Nouveau modèle remplaçant l'ancien en production avec un MAE de : "
            f"{new_mae} l'ancien MAE était : {old_mae}"
        )
        transition_model.submit(current_stage="Staging", new_stage="Production")
    else:
        print(f"🚀 Ancien modèle conservé avec un MAE de : {old_mae}. Le nouveau MAE était : {new_mae}")

    notify.submit(old_mae, new_mae)


if __name__ == "__main__":
    train_flow()
