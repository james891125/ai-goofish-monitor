import asyncio

from src.services.item_analysis_dispatcher import (
    ItemAnalysisDispatcher,
    ItemAnalysisJob,
)


def test_item_analysis_dispatcher_uses_bounded_concurrency():
    active_ai_calls = 0
    max_active_ai_calls = 0
    saved_records = []
    notifications = []

    async def seller_loader(user_id: str):
        await asyncio.sleep(0.005)
        return {"賣家ID": user_id}

    async def image_downloader(product_id: str, image_urls: list[str], task_name: str):
        return []

    async def ai_analyzer(record: dict, image_paths: list[str], prompt_text: str):
        nonlocal active_ai_calls, max_active_ai_calls
        active_ai_calls += 1
        max_active_ai_calls = max(max_active_ai_calls, active_ai_calls)
        await asyncio.sleep(0.03)
        active_ai_calls -= 1
        return {
            "analysis_source": "ai",
            "is_recommended": True,
            "reason": f"推薦 {record['商品資訊']['商品ID']}",
            "keyword_hit_count": 0,
        }

    async def notifier(item_data: dict, reason: str):
        notifications.append((item_data["商品ID"], reason))

    async def saver(record: dict, keyword: str):
        saved_records.append((keyword, record))
        return True

    async def run():
        dispatcher = ItemAnalysisDispatcher(
            concurrency=2,
            skip_ai_analysis=False,
            seller_loader=seller_loader,
            image_downloader=image_downloader,
            ai_analyzer=ai_analyzer,
            notifier=notifier,
            saver=saver,
        )
        for index in range(3):
            dispatcher.submit(
                ItemAnalysisJob(
                    keyword="demo",
                    task_name="Demo",
                    decision_mode="ai",
                    analyze_images=False,
                    prompt_text="prompt",
                    keyword_rules=(),
                    final_record={
                        "商品資訊": {"商品ID": str(index), "商品圖片列表": []},
                        "賣家資訊": {},
                    },
                    seller_id=f"seller-{index}",
                    registration_duration_text="來蝦皮1年",
                )
            )
        await dispatcher.join()
        return dispatcher

    dispatcher = asyncio.run(run())
    assert dispatcher.completed_count == 3
    assert len(saved_records) == 3
    assert len(notifications) == 3
    assert max_active_ai_calls == 2
    assert saved_records[0][1]["賣家資訊"]["賣家ID"].startswith("seller-")


def test_item_analysis_dispatcher_supports_keyword_mode_without_ai():
    saved_records = []

    async def seller_loader(user_id: str):
        return {"賣家標籤": "個人閒置"}

    async def image_downloader(product_id: str, image_urls: list[str], task_name: str):
        raise AssertionError("關鍵詞模式不應下載圖片")

    async def ai_analyzer(record: dict, image_paths: list[str], prompt_text: str):
        raise AssertionError("關鍵詞模式不應呼叫 AI")

    async def notifier(item_data: dict, reason: str):
        return None

    async def saver(record: dict, keyword: str):
        saved_records.append(record)
        return True

    async def run():
        dispatcher = ItemAnalysisDispatcher(
            concurrency=1,
            skip_ai_analysis=False,
            seller_loader=seller_loader,
            image_downloader=image_downloader,
            ai_analyzer=ai_analyzer,
            notifier=notifier,
            saver=saver,
        )
        dispatcher.submit(
            ItemAnalysisJob(
                keyword="demo",
                task_name="Demo",
                decision_mode="keyword",
                analyze_images=False,
                prompt_text="",
                keyword_rules=("個人閒置",),
                final_record={
                    "商品資訊": {"商品ID": "1", "商品標題": "演示商品"},
                    "賣家資訊": {},
                },
                seller_id="seller-1",
                registration_duration_text="來蝦皮1年",
            )
        )
        await dispatcher.join()

    asyncio.run(run())
    assert saved_records[0]["ai_analysis"]["analysis_source"] == "keyword"
    assert saved_records[0]["ai_analysis"]["is_recommended"] is True
