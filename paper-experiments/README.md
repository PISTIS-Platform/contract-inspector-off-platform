# paper-experiments

Code for the experiments of *Enhancing Data Space Security for Market Uptake*: unit and time-zone canonicalisation for the
Off-Platform Contract Inspector, the conversion attacks it is tested against, and the scripts that run the experiments.
The similarity engine, the datasets and the source registry with the real column choices are not included.

## Setup

Python 3.11 or later; `requirements-lock.txt` has the versions used for the runs.

    python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt pytest
    python -m pytest

## Vocabulary

The unit suffixes (`temperature_mean_c`, `wind_max_kmh`, ...) and the time settings are the TOML files in
`inspector/vocab/`. Put your own entries in a separate file, point `INSPECTOR_UNITS_VOCAB` or `INSPECTOR_TZ_VOCAB` at it
(or use `vocab/` in the data folder), and check it:

    python -m inspector.vocab list
    python -m inspector.vocab check examples/my_units.toml
    python -m inspector.vocab scan examples/sensors.csv

The `_psi` column of the example sensor file is not recognised until `my_units.toml` is added:

    INSPECTOR_UNITS_VOCAB=examples/my_units.toml python -m inspector.vocab scan examples/sensors.csv

## Running

The experiment scripts need the engine (`inspector/similarity.py`), the datasets (`data/README.md`)
and `data/sources.toml` with the real column names (`data/sources.example.toml` shows the format). With `PISTIS_DATA_DIR`
set, runs are written under `experiments/`:

    python table_regen_experiment.py init
    python table_regen_experiment.py positives --run-dir <run_dir> --encoding B

## Licence and acknowledgement

Apache-2.0, see `LICENSE`. This work was partially supported by the PISTIS project (GA: 101093016), funded by the
European Commission under the Horizon Europe programme.
