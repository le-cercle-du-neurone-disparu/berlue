# 1. Retrieve the base image dynamically (passed by the Makefile)
ARG DOCKER_BASE_IMAGE=python:3.10.6-slim
FROM ${DOCKER_BASE_IMAGE}

WORKDIR /api

# 2. Install dependencies (Production only!)
COPY requirements.txt requirements.txt
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# 3. Copy the source code and install the package
COPY berlue berlue
COPY setup.py setup.py

# Optional: Uncomment if you have frozen models stored locally
# COPY models models

# 4. Production magic: install the package without the [dev] dependencies!
RUN pip install . && rm -rf build *.egg-info

# 5. Start the API (using exec to handle signals properly like CTRL+C)
CMD ["sh", "-c", "exec uvicorn berlue.api.fast:app --host 0.0.0.0 --port $PORT"]
