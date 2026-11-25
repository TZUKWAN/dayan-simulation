FROM python:3.13-slim@sha256:1b5c0692836eae9b028cc352d7146872f36939aa1fb0de24d3ef6df307b956c9
COPY requirements.lock /opt/dayan/requirements.lock
RUN python -m pip install --no-cache-dir --only-binary=:all: --require-hashes --index-url https://pypi.org/simple -r /opt/dayan/requirements.lock
ARG DAYAN_SOLVER_BUNDLE
LABEL org.dayan.solver.protocol="dayan-solver-segment-v1" org.dayan.solver.bundle=$DAYAN_SOLVER_BUNDLE
COPY codec.py worker.py supervisor.py decisions.py /opt/dayan/
WORKDIR /tmp
ENTRYPOINT ["/usr/local/bin/python", "-I", "-u", "/opt/dayan/supervisor.py"]
