from __future__ import annotations
import os
import re
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from io import StringIO
from typing import Iterable, Optional

import pandas as pd
import requests

from .._config import Config
from ..common.utils import log, retry, norm_code
from .repository import Repository

HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
CODE_RE = re.compile(r"^\d{6}$")
_PAT_PAGES = re.compile(r"pages\s*:\s*(\d+)", re.I)


class Fetcher:
    def __init__(self, config: Config, repo: Repository):
        self.config = config
        self.repo = repo

    def _fix_code(self, code: str) -> str:
        s = re.sub(r"\D", "", str(code)).zfill(6)
        return s if CODE_RE.match(s) else ""

    # -------- F10 API (paginated) --------

    def _extract_table_html(self, text: str) -> str:
        m1 = re.search(r"<table[^>]*>", text, re.I | re.S)
        m2 = re.search(r"</table>", text, re.I | re.S)
        if not (m1 and m2):
            return ""
        return text[m1.start():m2.end()]

    def _fetch_f10_pages(self, code6: str, max_pages: int = 999) -> pd.DataFrame:
        url = "http://fundf10.eastmoney.com/F10DataApi.aspx"
        headers = {**HEADERS_BASE, "Referer": f"http://fundf10.eastmoney.com/jjjz_{code6}.html"}
        params = {"type": "lsjz", "code": code6, "page": 1, "per": 20}
        r = requests.get(url, params=params, headers=headers, timeout=15)
        r.raise_for_status()
        text = r.text
        m = _PAT_PAGES.search(text)
        pages = min(int(m.group(1)) if m else 1, max_pages)

        frames = []
        for p in range(1, pages + 1):
            params["page"] = p
            rp = requests.get(url, params=params, headers=headers, timeout=15)
            rp.raise_for_status()
            html = self._extract_table_html(rp.text)
            tables = pd.read_html(StringIO(html)) if html else pd.read_html(StringIO(rp.text))
            if not tables:
                break
            dfp = tables[0]
            ren = {}
            for c in dfp.columns:
                if "日期" in c: ren[c] = "date"
                elif "单位" in c: ren[c] = "nav"
                elif "累计" in c: ren[c] = "acc_nav"
            dfp = dfp.rename(columns=ren)
            keep = [c for c in ["date", "nav", "acc_nav"] if c in dfp.columns]
            if "date" not in keep or "nav" not in keep:
                continue
            dfp["date"] = pd.to_datetime(dfp["date"], errors="coerce")
            dfp["nav"] = pd.to_numeric(dfp["nav"], errors="coerce")
            if "acc_nav" in dfp.columns:
                dfp["acc_nav"] = pd.to_numeric(dfp["acc_nav"], errors="coerce")
            else:
                dfp["acc_nav"] = pd.NA
            dfp = dfp.dropna(subset=["date", "nav"])
            if dfp.empty:
                continue
            frames.append(dfp[["date", "nav", "acc_nav"]])
            time.sleep(0.08)

        if not frames:
            return pd.DataFrame(columns=["date", "nav", "acc_nav"])
        df = pd.concat(frames, ignore_index=True)
        return df.drop_duplicates(subset=["date"]).sort_values("date")

    # -------- AKShare fallback --------

    def _fetch_js(self, code6: str) -> pd.DataFrame:
        import akshare as ak

        dfu = ak.fund_open_fund_info_em(symbol=code6, indicator="单位净值走势")
        try:
            dfa = ak.fund_open_fund_info_em(symbol=code6, indicator="累计净值走势")
            df = pd.merge(dfu[["净值日期", "单位净值"]], dfa[["净值日期", "累计净值"]], on="净值日期", how="left")
        except Exception:
            df = dfu.rename(columns={"净值日期": "净值日期", "单位净值": "单位净值"})
        df = df.rename(columns={"净值日期": "date", "单位净值": "nav", "累计净值": "acc_nav"})
        if "acc_nav" not in df.columns:
            df["acc_nav"] = pd.NA
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
        df["acc_nav"] = pd.to_numeric(df["acc_nav"], errors="coerce")
        df = df.dropna(subset=["date", "nav"]).drop_duplicates(subset=["date"]).sort_values("date")
        return df[["date", "nav", "acc_nav"]]

    def fetch_one_fund_nav(self, code: str, since: str | None = None) -> pd.DataFrame:
        code6 = self._fix_code(code)
        if not code6:
            raise ValueError(f"Invalid fund code: {code}")
        try:
            raw = self._fetch_f10_pages(code6, max_pages=40)
            src = "f10"
        except Exception as e:
            log(f"[WARN] F10 failed for {code6}, fallback to JS: {e}")
            raw = self._fetch_js(code6)
            src = "js"
        df = raw.copy()
        if df.empty:
            return pd.DataFrame(columns=["fund_code", "date", "nav", "acc_nav"])
        if since:
            sd = pd.to_datetime(since)
            df = df[df["date"] >= sd]
        df.insert(0, "fund_code", code6)
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        log(f"[FETCH] {code6} rows={len(df)} src={src}")
        time.sleep(0.1)
        return df[["fund_code", "date", "nav", "acc_nav"]].where(pd.notna(df), None)

    def fetch_and_save_batch(self, codes: Iterable[str], since: str | None = None, max_workers: int | None = None) -> int:
        codes = list(dict.fromkeys(codes))
        if not codes:
            return 0
        workers = max_workers or self.config.parallel_workers
        log(f"[FETCH] Batch: {len(codes)} funds, {workers} workers, since={since or '-'}")
        write_rows = 0

        def task(code: str) -> int:
            try:
                df = self.fetch_one_fund_nav(code, since=since)
                return self.repo.upsert_nav(df) if df is not None and not df.empty else 0
            except Exception as e:
                log(f"[ERR] {code} failed: {e}")
                return 0

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fund-dl") as ex:
            futures = {ex.submit(task, c): c for c in codes}
            done = 0
            for fut in as_completed(futures):
                write_rows += int(fut.result() or 0)
                done += 1
                if done % 10 == 0 or done == len(codes):
                    log(f"[FETCH] {done}/{len(codes)} done, {write_rows} rows written")
        log(f"[FETCH] Complete: {write_rows} rows written")
        return write_rows

    def fetch_incremental(self, codes: Iterable[str], fallback_since: str, lookback_days: int = 5) -> int:
        last_date = self.repo.get_latest_nav_date()
        if last_date:
            since_date = (datetime.strptime(last_date, "%Y-%m-%d") - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        else:
            since_date = fallback_since
        log(f"[FETCH] Incremental: last={last_date or 'None'}, since={since_date}")
        return self.fetch_and_save_batch(codes, since=since_date)
