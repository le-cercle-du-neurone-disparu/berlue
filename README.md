# 🚀 MLOps Boilerplate Template

A robust, framework-agnostic template to jumpstart your Machine Learning projects with best practices in software engineering, CI/CD, and GCP deployment.

## 🛠️ 1. Local Environment Setup

Automatically set up your Python virtual environment using `pyenv` and install the package with all dependencies:

```bash
make local_setup
```

---

## ☁️ 2. Cloud Infrastructure (GCP VM)

To train your model on a powerful cloud machine, provision your Google Cloud Platform VM directly from your local terminal:

1. Create the VM and assign the Service Account:
```bash
make vm_create
```

2. Send and execute the environment setup script (`setup_vm.sh`) on the VM:
```bash
make vm_setup
```

3. Connect to your new VM:
```bash
make vm_connect
```

*(Note: Once connected to the VM via SSH, you will clone your repository there and run `make local_setup` to prepare your training environment, just like you did locally).*

### 🛑 Resource Management (Avoid extra billing)
**Crucial:** Don't forget to stop your VM when you are done working for the day to save CPU costs!

```bash
# Stop the VM (saves money, keeps your files)
make vm_stop

# Resume work the next day
make vm_start

# When the project is entirely finished, delete the VM permanently
make vm_delete
```

---

## 🧠 3. Development Workflow (ML Logic)

The core logic of your project lives in the newly renamed package folder. Follow these steps to build your pipeline:

1. **`params.py`**: Configure your data types, columns, and constants.
2. **`ml_logic/data.py`**: Implement `clean_data()` to preprocess your raw data.
3. **`ml_logic/preprocessor.py`**: Build your sklearn/custom pipelines.
4. **`ml_logic/model.py`**: Implement `build_model()`, `train_model()`, and `evaluate_model()`.
5. **`ml_logic/registry.py`**: Implement model lifecycle management and **MLflow** integration to track your experiments and metrics.

### Step-by-Step Execution
Once your logic is implemented, run your pipeline steps independently via the Makefile:

```bash
make run_preprocess
make run_train
make run_evaluate
make run_pred

# Or run the entire pipeline at once:
make run_all
```

### 🤖 Orchestration (Prefect)
To automate, monitor, and schedule your entire MLOps pipeline, implement your tasks in `interface/workflow.py` and run the orchestrator:

```bash
make run_workflow
```

---

## 🌐 4. Serving & API

The deployment of your API follows a strict 3-step validation process (Fail-Fast methodology):

### Step 1: Local Native Development
Implement your FastAPI endpoints in `api/fast.py`. Run the API natively on your machine for fast iteration and live-reloading:
```bash
make run_api
```
*Verify your code logic:*
```bash
make test_api_local
```

### Step 2: Local Docker Verification
Once the native API works, ensure it runs correctly inside its isolated container. This catches missing dependencies before deploying to the cloud.
```bash
make docker_build_local
make docker_run_local
```
*Verify your containerized API:*
```bash
make test_api_docker
```

### Step 3: Cloud Production Deployment
When the local container is validated, build the production image (which uses `pip install .` for a lighter footprint) and deploy it to GCP Cloud Run.
```bash
make docker_build_prod
make docker_push
make cloudrun_deploy
```
*Verify your live production endpoint:*
```bash
make test_api_cloud
```
