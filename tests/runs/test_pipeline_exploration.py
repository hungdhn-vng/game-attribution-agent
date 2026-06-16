# tests/runs/test_pipeline_exploration.py
import inspect
from gaa.runs import pipeline


def test_pipeline_runs_exploration_sweep_last():
    src = inspect.getsource(pipeline.AnalysisPipeline._stage_modules)
    assert "ExplorationSweep" in src, "modules stage must run ExplorationSweep"
    # must run AFTER the targeted modules so the novelty gate can see their findings
    assert src.index("ExplorationSweep") > src.index("MigrationPattern")
    assert "from gaa.core.modules.exploration import ExplorationSweep" in inspect.getsource(pipeline)
