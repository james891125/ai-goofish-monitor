"""Shopee CLI for mock/import/authorized adapters."""
import argparse
import asyncio
import json
from dotenv import load_dotenv
from src.infrastructure.persistence.shopee_repository import ShopeeRepository
from src.services.product_monitor import ProductMonitor


async def main():
    parser=argparse.ArgumentParser(description='臺灣蝦皮監控（等待資料來源授權；目前提供模擬與匯入）')
    parser.add_argument('--task-name',help='執行已儲存的指定任務')
    parser.add_argument('--debug-limit',type=int,default=0,help='限制每次處理筆數')
    args=parser.parse_args()
    load_dotenv(interpolate=False)
    repository=ShopeeRepository()
    tasks=[task for task in repository.tasks() if task.enabled and (not args.task_name or task.task_name==args.task_name)]
    if not tasks: parser.error('沒有符合條件的蝦皮任務，請先透過網頁建立。')
    monitor=ProductMonitor(repository)
    failed=False
    for task in tasks:
        if args.debug_limit>0: task=task.model_copy(update={'max_items':min(args.debug_limit,task.max_items)})
        result=await monitor.run(task)
        print(json.dumps(result,ensure_ascii=False))
        failed=failed or result['status']!='completed'
    return 1 if failed else 0


if __name__=='__main__':
    raise SystemExit(asyncio.run(main()))
