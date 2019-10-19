FROM python:3.7.5

ENV \
  PYTHONFAULTHANDLER=1 \
  PYTHONUNBUFFERED=1 \
  PYTHONHASHSEED=random \
  PIP_DISABLE_PIP_VERSION_CHECK=on \
  POETRY_VERSION=0.12.17

RUN mkdir /code && pip --no-cache-dir install poetry
WORKDIR /code
ADD pyproject.toml poetry.lock /code/
RUN poetry install --no-interaction --no-dev

ADD mate3 /code/code
ADD registry_data /code/registry_data
ADD pg_config.yaml /code/

CMD poetry run mate3
