"""命令列入口。

    python -m shopee_lite run "mac mini m4" --pages 3 --max-price 30000
    python -m shopee_lite run "mac mini m4" "macbook air m3" --ai compare --webhook
    python -m shopee_lite ui
"""
import argparse
import sys

from .runner import AI_MODES, DETAIL_MODES, MAX_PAGES, RunOptions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shopee_lite", description="蝦皮商品清單 → CSV")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="搜尋關鍵字並輸出 CSV")
    run.add_argument("keywords", nargs="+", help="一個或多個關鍵字")
    run.add_argument("--pages", type=int, default=3, help=f"每個關鍵字看幾頁（1–{MAX_PAGES}，預設 3；一頁約 60 件）")
    run.add_argument("--min-price", default="", help="最低價（搜尋時套用，抓回來後也會再檢查一次）")
    run.add_argument("--max-price", default="", help="最高價")
    run.add_argument("--latest", action="store_true", help="依最新上架排序")
    run.add_argument("--region", default="", help="只留出貨地包含此文字的商品，例如 台北市")
    run.add_argument("--free-shipping", action="store_true", help="只留免運商品")
    run.add_argument(
        "--detail", choices=DETAIL_MODES, default="auto",
        help="off=只看標題；auto=只有標題缺狀態或容量才進商品頁補（預設）；all=每件都進商品頁",
    )
    run.add_argument(
        "--ai", choices=AI_MODES, default="off",
        help="off=只用規則；on=規則抓不到的才交給 AI 補；compare=規則與 AI 並排比較",
    )
    run.add_argument("--no-title-match", action="store_true", help="不要排除標題沒有包含關鍵字的商品")
    run.add_argument("--keep-accessories", action="store_true", help="不要排除保護貼、錶帶、機殼等配件")
    run.add_argument("--exclude", default="", help="額外要排除的詞，逗號或空白分隔，例如 \"殼,膜,線\"")
    run.add_argument("--webhook", action="store_true", help="完成後把 CSV 傳到 WEBHOOK_URL")
    run.add_argument("--headless", action="store_true", help="隱藏瀏覽器視窗（遇到驗證時無法手動處理）")

    ui = sub.add_parser("ui", help="開啟簡易網頁介面")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--no-browser", action="store_true", help="不要自動開啟瀏覽器")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "ui":
        from .web import serve

        serve(args.port, open_browser=not args.no_browser)
        return 0

    from . import service

    options = RunOptions(
        keywords=args.keywords,
        pages=args.pages,
        min_price=args.min_price,
        max_price=args.max_price,
        latest=args.latest,
        region=args.region,
        free_shipping=args.free_shipping,
        detail=args.detail,
        ai=args.ai,
        title_match=not args.no_title_match,
        exclude_accessories=not args.keep_accessories,
        extra_exclude=[args.exclude],
    )
    settings = service.load_settings()
    if args.headless:
        settings.headless = True
    try:
        path, _ = service.run_blocking(options, settings=settings)
        if args.webhook:
            print(service.send_webhook(path, settings))
    except Exception as exc:  # noqa: BLE001 - 命令列只要顯示原因
        print(f"[錯誤] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
