"""Create a reproducible, offline model go/no-go research evidence report."""
from __future__ import annotations
import argparse
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from model_release_acceptance import evaluate_release


def main():
    parser=argparse.ArgumentParser(description="No-write fail-closed research model release")
    parser.add_argument("--evaluation",type=Path,
                        default=ROOT/"models/tw-factor-ridge-1-evaluation.json")
    parser.add_argument("--historical-label-report",type=Path,default=None)
    parser.add_argument("--future-holdout",type=Path,default=None)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    saved=json.loads(args.evaluation.read_text(encoding="utf-8"))
    label=(json.loads(args.historical_label_report.read_text(encoding="utf-8"))
           if args.historical_label_report else None)
    unseen=(json.loads(args.future_holdout.read_text(encoding="utf-8"))
            if args.future_holdout else None)
    report=evaluate_release(saved,historical_label_report=label,
                            independently_frozen_future_holdout=unseen)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"decision":report["decision"],
                      "blockers":report["blocking_reasons"],
                      "live_trading_approved":False,
                      "line_signal_delivery_approved":False},ensure_ascii=False))


if __name__=="__main__":
    main()
