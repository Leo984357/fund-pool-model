from __future__ import annotations
from pathlib import Path
from typing import List, Optional
import pandas as pd
import sqlite3

from .._config import Config
from ..common.utils import log, norm_code
from .connection import get_connection


class UniversePool:
    def __init__(self, config: Config):
        self.config = config

    def _normalize_codes(self, obj) -> pd.DataFrame:
        if obj is None:
            return pd.DataFrame(columns=["fund_code"])
        if isinstance(obj, pd.Series):
            s = obj.astype(str)
        elif isinstance(obj, pd.DataFrame):
            prefer = ["fund_code", "代码", "基金代码", "symbol", "code"]
            col = next((c for c in prefer if c in obj.columns), None)
            if col is None:
                for c in obj.columns:
                    if obj[c].astype(str).str.contains(r"\d{6}", regex=True).any():
                        col = c
                        break
            if col is None:
                col = obj.columns[0]
            s = obj[col].astype(str)
        else:
            return pd.DataFrame(columns=["fund_code"])
        s = s.str.extract(r"(\d{6})", expand=False).dropna().map(lambda x: x.zfill(6))
        return pd.DataFrame({"fund_code": s}).drop_duplicates().reset_index(drop=True)

    def load(self, limit: Optional[int] = None) -> List[str]:
        eff_limit = limit if limit is not None else self.config.universe_limit
        csv_path = Path(self.config.universe_csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        base = self._read_csv(csv_path)
        base_cnt = len(base)

        if base_cnt < eff_limit:
            db_df = self._read_db()
            if not db_df.empty:
                base = pd.concat([base, db_df], ignore_index=True).drop_duplicates()

        if len(base) < eff_limit:
            ak_df = self._read_akshare(eff_limit * 2)
            if not ak_df.empty:
                base = pd.concat([base, ak_df], ignore_index=True).drop_duplicates()

        base = self._normalize_codes(base)
        codes = base["fund_code"].head(eff_limit).tolist()

        pd.DataFrame({"fund_code": codes}).to_csv(csv_path, index=False, encoding="utf-8-sig")
        log(f"[POOL] candidates={base_cnt} -> returned={len(codes)} (limit={eff_limit})")
        return codes

    def _read_csv(self, path: Path) -> pd.DataFrame:
        try:
            if path.exists():
                return self._normalize_codes(pd.read_csv(path, dtype=str))
        except Exception as e:
            log(f"[WARN] CSV read failed: {e}")
        return pd.DataFrame(columns=["fund_code"])

    def _read_db(self) -> pd.DataFrame:
        dbp = self.config.db_path
        if not dbp.exists():
            return pd.DataFrame(columns=["fund_code"])
        try:
            with get_connection(dbp) as conn:
                df = pd.read_sql(f"SELECT DISTINCT fund_code FROM {self.config.nav_table}", conn)
            return self._normalize_codes(df)
        except Exception as e:
            log(f"[INFO] DB read failed: {e}")
            return pd.DataFrame(columns=["fund_code"])

    def _read_akshare(self, max_rows: int) -> pd.DataFrame:
        try:
            import akshare as ak
            frames = []
            for fn in ("fund_name_em", "fund_etf_fund_daily_em", "fund_lof_fund_daily_em"):
                if hasattr(ak, fn):
                    try:
                        df = getattr(ak, fn)()
                        if isinstance(df, pd.DataFrame) and not df.empty:
                            frames.append(df)
                    except Exception:
                        pass
            if not frames:
                return pd.DataFrame(columns=["fund_code"])
            return self._normalize_codes(pd.concat(frames, ignore_index=True)).head(max_rows)
        except Exception:
            return pd.DataFrame(columns=["fund_code"])

    def load_from_csv(self, csv_path: Path, limit: int) -> List[str]:
        df = pd.read_csv(csv_path)
        col = "fund_code" if "fund_code" in df.columns else df.columns[0]
        codes = df[col].astype(str).map(norm_code).dropna().tolist()
        return codes[:limit]
