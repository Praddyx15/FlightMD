"""
Row-by-row numeric columns for the .bin and .tlog parsers.

A list of tuples costs ~100 bytes per value (a boxed float plus the tuple slot); a 300 MB
dataflash log has tens of millions of values, which is where the gigabytes went. A
ColumnBuffer keeps one float64 block instead and builds the DataFrame once at the end.
"""

import numpy as np
import pandas as pd

MIN_ROWS = 256


class ColumnBuffer:
    """Float64 columns appended a row at a time. None becomes NaN.

    size is the expected row count; DFReader knows it exactly from its index, so the
    block usually never grows. When it's a guess the block doubles as needed.
    """

    def __init__(self, columns, size: int = 0):
        self.columns = list(columns)
        if len(set(self.columns)) != len(self.columns):
            raise ValueError(f"duplicate column names: {self.columns}")
        self._data = np.empty((max(int(size), MIN_ROWS), len(self.columns)), dtype=np.float64)
        self.n = 0

    def __len__(self):
        return self.n

    def append(self, row) -> None:
        if self.n == self._data.shape[0]:
            grown = np.empty((self._data.shape[0] * 2, self._data.shape[1]), dtype=np.float64)
            grown[:self.n] = self._data
            self._data = grown
        self._data[self.n] = row
        self.n += 1

    def frame(self) -> pd.DataFrame:
        # copy so the (possibly much bigger) block can be freed
        return pd.DataFrame(self._data[:self.n].copy(), columns=self.columns)
