import pytest
import pandas as pd
import numpy as np

# TODO: Import your project's specific constants or types if needed
# from berlue.params import *

@pytest.fixture(scope="session")
def fixture_mock_raw_data() -> pd.DataFrame:
    """
    Provides a mock raw DataFrame for testing.
    scope="session" ensures this runs only once per test suite execution.
    """
    # TODO: Replace with your own mock data generation or load a small local CSV
    data = {
        "feature_1": np.random.rand(10),
        "feature_2": np.random.rand(10),
        "target": np.random.randint(0, 2, 10)
    }
    return pd.DataFrame(data)

@pytest.fixture(scope="session")
def fixture_mock_cleaned_data() -> pd.DataFrame:
    """
    Provides a mock cleaned DataFrame for testing model training or predictions.
    """
    # TODO: Adapt to your project's expected cleaned data format
    data = {
        "feature_1_scaled": np.random.rand(10),
        "feature_2_scaled": np.random.rand(10),
        "target": np.random.randint(0, 2, 10)
    }
    return pd.DataFrame(data)
