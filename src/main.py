"""AI 台股投資作戰系統主程式入口。

目前先建立可執行的骨架；資料擷取與分析模組會在後續步驟逐一加入。
本程式不會下單。
"""

from datetime import datetime, timezone


def main() -> None:
    """執行系統主流程。"""
    started_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    print("AI 台股投資作戰系統啟動")
    print(f"執行時間：{started_at}")
    print("目前階段：主程式骨架建立完成，尚未執行行情下載或投資分析。")


if __name__ == "__main__":
    main()
