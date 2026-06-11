from typing import Protocol, Union
import pandas as pd
from gaa.schema.profile import ColumnMapping


class Adapter(Protocol):
    def load(self, raw: Union[str, pd.DataFrame], mapping: ColumnMapping) -> pd.DataFrame:
        """Return a validated canonical long-format DataFrame."""
        ...
