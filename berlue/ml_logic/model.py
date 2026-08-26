from typing import Any

import numpy as np

# Alias de type générique pour accueillir des modèles Scikit-Learn, Keras, PyTorch ou XGBoost
Model = Any


def build_model(
    input_shape: tuple = None,  # pour DL : ignoré si ML (peut être supprimé)
    learning_rate: float = 0.0005,  # pour DL : ignoré si ML (peut être supprimé)
    **kwargs,
) -> Model:
    """
    Instancie le modèle.
    (Pour les réseaux de neurones, cela inclut l'initialisation des poids et la compilation).
    """
    # TODO: Implémenter build_model
    # Exemple pour Scikit-Learn :
    # model = RandomForestRegressor(max_depth=kwargs.get("max_depth", 5))
    # return model

    # Exemple pour DL avec tensorflow :
    # 1. Initialisation
    # model = models.Sequential()
    # model.add(layers.Dense(32, activation='relu', input_shape=input_shape))
    # model.add(layers.Dense(1, activation='linear'))

    # # 2. Compilation
    # optimizer = optimizers.Adam(learning_rate=learning_rate)
    # model.compile(loss='mse', optimizer=optimizer, metrics=['mae'])

    raise NotImplementedError("build_model n'est pas encore implémenté.")


def train_model(
    model: Model,
    X: np.ndarray,
    y: np.ndarray,
    batch_size: int = 256,  # pour DL : ignoré si ML (peut être supprimé)
    patience: int = 2,  # pour DL : ignoré si ML (peut être supprimé)
    **kwargs,
) -> tuple[Model, dict]:
    """
    Entraîne le modèle et retourne un tuple (fitted_model, history_or_metrics).
    """
    # TODO: Implémenter train_model
    # Exemple pour ML avec Scikit-Learn :
    # model.fit(X, y)
    # return model, {}

    # Exemple pour DL avec tensorflow :
    # es = callbacks.EarlyStopping(
    #     monitor="val_loss",
    #     patience=patience,
    #     restore_best_weights=True
    # )

    # history = model.fit(
    #     X, y,
    #     validation_split=0.3,
    #     epochs=100,
    #     batch_size=batch_size,
    #     callbacks=[es],
    #     verbose=1
    # )

    # # Keras renvoie un objet History. On extrait le dictionnaire de métriques pour MLflow
    # return model, history.history

    raise NotImplementedError("train_model n'est pas encore implémenté.")


def evaluate_model(
    model: Model,
    X: np.ndarray,
    y: np.ndarray,
    batch_size: int = 64,  # pour DL : ignoré si ML (peut être supprimé)
    **kwargs,
) -> dict:
    """
    Évalue la performance du modèle entraîné sur le dataset.
    Retourne un dictionnaire de métriques.
    """
    # TODO: Implémenter evaluate_model
    # Exemple pour Scikit-Learn :
    # y_pred = model.predict(X)
    # mae = mean_absolute_error(y, y_pred)
    # return {"mae": mae}

    # Exemple pour DL avec tensorflow :
    # metrics = model.evaluate(X, y, batch_size=batch_size, verbose=0)

    # # model.evaluate retourne une liste [loss, metric1, metric2...]
    # # On la transforme en dictionnaire propre
    # return {
    #     "loss": metrics[0],
    #     "mae": metrics[1]
    # }

    raise NotImplementedError("evaluate_model n'est pas encore implémenté.")
