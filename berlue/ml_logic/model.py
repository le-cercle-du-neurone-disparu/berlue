import numpy as np
from typing import Tuple, Any

# Generic type alias to accommodate Scikit-Learn, Keras, PyTorch, or XGBoost models
Model = Any

def build_model(input_shape: tuple = None,    # for DL: ignored if ML (can be removed)
                learning_rate: float = 0.0005, # for DL: ignored if ML (can be removed)
                **kwargs) -> Model:
    """
    Instantiate the model.
    (For neural networks, this includes initializing weights and compiling).
    """
    # TODO: Implement build_model
    # Example for Scikit-Learn:
    # model = RandomForestRegressor(max_depth=kwargs.get("max_depth", 5))
    # return model

    # Example for DL with tensorflow:
    # 1. Initialization
    # model = models.Sequential()
    # model.add(layers.Dense(32, activation='relu', input_shape=input_shape))
    # model.add(layers.Dense(1, activation='linear'))

    # # 2. Compilation
    # optimizer = optimizers.Adam(learning_rate=learning_rate)
    # model.compile(loss='mse', optimizer=optimizer, metrics=['mae'])

    raise NotImplementedError("build_model is not implemented yet.")


def train_model(
        model: Model,
        X: np.ndarray,
        y: np.ndarray,
        batch_size: int = 256,    # for DL : ignored if ML (can be removed)
        patience: int = 2,        # for DL : ignored if ML (can be removed)
        **kwargs
    ) -> Tuple[Model, dict]:
    """
    Fit the model and return a tuple (fitted_model, history_or_metrics).
    """
    # TODO: Implement train_model
    # Example for ML with Scikit-Learn:
    # model.fit(X, y)
    # return model, {}

    # Example for DL with tensorflow:
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

    raise NotImplementedError("train_model is not implemented yet.")


def evaluate_model(
        model: Model,
        X: np.ndarray,
        y: np.ndarray,
        batch_size: int = 64,    # for DL : ignored if ML (can be removed)
        **kwargs
    ) -> dict:
    """
    Evaluate trained model performance on the dataset.
    Returns a dictionary of metrics.
    """
    # TODO: Implement evaluate_model
    # Example for Scikit-Learn:
    # y_pred = model.predict(X)
    # mae = mean_absolute_error(y, y_pred)
    # return {"mae": mae}

    # Example for DL with tensorflow:
    # metrics = model.evaluate(X, y, batch_size=batch_size, verbose=0)

    # # model.evaluate retourne une liste [loss, metric1, metric2...]
    # # On la transforme en dictionnaire propre
    # return {
    #     "loss": metrics[0],
    #     "mae": metrics[1]
    # }

    raise NotImplementedError("evaluate_model is not implemented yet.")
