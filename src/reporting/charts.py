from __future__ import annotations
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt


def plot_equity(nav: pd.Series, out_png: Path):
    out_png.parent.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(9, 4))
    nav.plot()
    plt.title("Portfolio NAV")
    plt.xlabel("Date")
    plt.ylabel("NAV")
    plt.tight_layout()
    plt.savefig(out_png)
    plt.close()
