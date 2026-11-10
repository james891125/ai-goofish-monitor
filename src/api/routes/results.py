"""
結果檔案管理路由
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from enum import Enum

from pydantic import BaseModel
from urllib.parse import quote

from src.services.price_history_service import build_price_history_insights
from src.services.result_export_service import build_results_csv
from src.services.result_file_service import (
    enrich_records_with_price_insight,
    validate_result_filename,
)
from src.services.result_storage_service import (
    build_result_ndjson,
    delete_result_file_records,
    list_result_filenames,
    load_all_result_records,
    load_result_blacklist_keywords,
    load_visible_result_item_ids,
    query_result_records,
    result_file_exists,
    save_result_blacklist_keywords,
    update_item_status,
)


router = APIRouter(prefix="/api/results", tags=["results"])

DEFAULT_EXPORT_FILENAME = "export.csv"


def _build_download_headers(export_name: str) -> dict[str, str]:
    ascii_name = export_name.encode("ascii", "ignore").decode("ascii")
    if ascii_name != export_name or not ascii_name:
        ascii_name = DEFAULT_EXPORT_FILENAME
    encoded_name = quote(export_name, safe="")
    return {
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{encoded_name}"
        )
    }


@router.get("/files")
async def get_result_files():
    """獲取所有結果檔案列表"""
    return {"files": await list_result_filenames()}


@router.get("/files/{filename:path}")
async def download_result_file(filename: str):
    """下載指定的結果檔案"""
    if ".." in filename or filename.startswith("/"):
        return {"error": "非法的檔案路徑"}
    if not filename.endswith(".jsonl") or not await result_file_exists(filename):
        return {"error": "檔案不存在"}
    return Response(
        content=await build_result_ndjson(filename),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/files/{filename:path}")
async def delete_result_file(filename: str):
    """刪除指定的結果檔案"""
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="非法的檔案路徑")
    if not filename.endswith(".jsonl"):
        raise HTTPException(status_code=400, detail="只能刪除 .jsonl 檔案")
    deleted_rows = await delete_result_file_records(filename)
    if deleted_rows <= 0:
        raise HTTPException(status_code=404, detail="檔案不存在")
    return {"message": f"檔案 {filename} 已成功刪除"}


@router.get("/{filename}")
async def get_result_file_content(
    filename: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    recommended_only: bool = Query(False),  # 相容舊參數，等價於 ai_recommended_only
    ai_recommended_only: bool = Query(False),
    keyword_recommended_only: bool = Query(False),
    include_hidden: bool = Query(False),
    sort_by: str = Query("crawl_time"),
    sort_order: str = Query("desc"),
):
    """讀取指定的 .jsonl 檔案內容，支援分頁、篩選和排序"""
    if ai_recommended_only and keyword_recommended_only:
        raise HTTPException(status_code=400, detail="AI推薦篩選與關鍵詞推薦篩選不能同時開啟。")

    if recommended_only and not ai_recommended_only and not keyword_recommended_only:
        ai_recommended_only = True

    try:
        validate_result_filename(filename)
        total_items, items = await query_result_records(
            filename,
            ai_recommended_only=ai_recommended_only,
            keyword_recommended_only=keyword_recommended_only,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            limit=limit,
            include_hidden=include_hidden,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"讀取結果檔案時出錯: {exc}")
    if total_items <= 0 and not await result_file_exists(filename):
        raise HTTPException(status_code=404, detail="結果檔案未找到")
    paginated_results = enrich_records_with_price_insight(items, filename)

    return {
        "total_items": total_items,
        "page": page,
        "limit": limit,
        "items": paginated_results
    }


@router.get("/{filename}/insights")
async def get_result_file_insights(filename: str):
    try:
        validate_result_filename(filename)
        keyword = filename.replace("_full_data.jsonl", "")
        visible_item_ids = load_visible_result_item_ids(filename)
        return build_price_history_insights(keyword, visible_item_ids=visible_item_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{filename}/export")
async def export_result_file_content(
    filename: str,
    recommended_only: bool = Query(False),
    ai_recommended_only: bool = Query(False),
    keyword_recommended_only: bool = Query(False),
    include_hidden: bool = Query(False),
    sort_by: str = Query("crawl_time"),
    sort_order: str = Query("desc"),
):
    if ai_recommended_only and keyword_recommended_only:
        raise HTTPException(status_code=400, detail="AI推薦篩選與關鍵詞推薦篩選不能同時開啟。")
    if recommended_only and not ai_recommended_only and not keyword_recommended_only:
        ai_recommended_only = True

    try:
        validate_result_filename(filename)
        results = await load_all_result_records(
            filename,
            ai_recommended_only=ai_recommended_only,
            keyword_recommended_only=keyword_recommended_only,
            sort_by=sort_by,
            sort_order=sort_order,
            include_hidden=include_hidden,
        )
        csv_text = build_results_csv(
            enrich_records_with_price_insight(results, filename)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"匯出結果檔案時出錯: {exc}")
    if not results and not await result_file_exists(filename):
        raise HTTPException(status_code=404, detail="結果檔案未找到")

    export_name = filename.replace(".jsonl", ".csv")
    headers = _build_download_headers(export_name)
    # 加上 UTF-8 BOM：Excel 開啟沒有 BOM 的 UTF-8 檔會當成 Big5，中文全部變亂碼
    return Response(
        content="\ufeff" + csv_text,
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


class ItemStatus(str, Enum):
    ACTIVE = "active"
    HIDDEN = "hidden"
    EXPIRED = "expired"


class UpdateStatusRequest(BaseModel):
    status: ItemStatus


class BlacklistRulesRequest(BaseModel):
    keywords: list[str]


@router.patch("/{filename}/items/{item_id}/status")
async def patch_item_status(filename: str, item_id: str, body: UpdateStatusRequest):
    """更新指定商品的狀態（active/hidden/expired）"""
    try:
        validate_result_filename(filename)
        updated = await update_item_status(filename, item_id, body.status.value)
        if not updated:
            raise HTTPException(status_code=404, detail="商品未找到")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"message": "狀態已更新", "status": body.status.value}


@router.get("/{filename}/blacklist-rules")
async def get_result_blacklist_rules(filename: str):
    try:
        validate_result_filename(filename)
        keywords = await load_result_blacklist_keywords(filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"keywords": keywords}


@router.put("/{filename}/blacklist-rules")
async def put_result_blacklist_rules(filename: str, body: BlacklistRulesRequest):
    try:
        validate_result_filename(filename)
        keywords = await save_result_blacklist_keywords(filename, body.keywords)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"message": "黑名單規則已更新", "keywords": keywords}
