# tests/runs/test_pipeline_migration.py
import inspect
from gaa.runs import pipeline


def test_pipeline_runs_migration_pattern():
    src = inspect.getsource(pipeline.AnalysisPipeline._stage_modules)
    assert "MigrationPattern" in src, "modules stage must run MigrationPattern after competitor"
    assert "from gaa.core.modules.migration import MigrationPattern" in inspect.getsource(pipeline)
