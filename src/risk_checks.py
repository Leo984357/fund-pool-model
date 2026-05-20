from __future__ import annotations
import pandas as pd

def basic_risk_sanity(df_scores: pd.DataFrame) -> list[str]:
    """
    一些基础风控提示（非硬限制）：
    - 因子全部为空/常数
    - 得分极端集中
    """
    warns = []
    if df_scores is None or df_scores.empty:
        warns.append("打分结果为空")
        return warns
    cols = [c for c in df_scores.columns if c not in ("fund_code","score","rank")]
    if not cols:
        warns.append("无有效因子列")
    if df_scores["score"].nunique() <= 3:
        warns.append("得分区分度较低，建议检查因子与窗口长度")
    return warns
