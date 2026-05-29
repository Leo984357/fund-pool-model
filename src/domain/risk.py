from __future__ import annotations
import pandas as pd


def check_risk(df_scores: pd.DataFrame) -> list[str]:
    warns = []
    if df_scores is None or df_scores.empty:
        warns.append("Scores empty")
        return warns
    cols = [c for c in df_scores.columns if c not in ("fund_code", "score", "rank")]
    if not cols:
        warns.append("No valid factor columns")
    if df_scores["score"].nunique() <= 3:
        warns.append("Low score differentiation, check factors/window")
    return warns
