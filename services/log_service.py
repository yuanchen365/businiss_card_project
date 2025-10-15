from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import Dict, List, Optional


class LogSession:
    def __init__(self) -> None:
        self.rows: List[Dict] = []
        self.session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.csv_path: Optional[str] = None

    def append(self, row: Dict) -> None:
        self.rows.append(row)

    def save_csv(self, dirpath: str = "logs") -> str:
        os.makedirs(dirpath, exist_ok=True)
        path = os.path.join(dirpath, f"log-{self.session_id}.csv")
        fieldnames = sorted({k for r in self.rows for k in r.keys()}) or [
            "timestamp", "action", "resourceName", "status", "reason"
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in self.rows:
                writer.writerow(r)
        self.csv_path = path
        return path

