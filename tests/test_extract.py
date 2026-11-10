import pytest

from shopee_lite.extract import extract_fields

CASES = [
    # (標題, 狀態, 記憶體, 儲存容量, 保固)
    ("【二手現貨】Apple Mac mini M4 24GB 512GB 10核CPU/10核GPU 盒裝完整 原廠電源線", "二手", "24GB", "512GB", ""),
    ("台中 保固2027/8/29 Mac mini M4 16G 512G 蘋果電腦 Apple", "", "16GB", "512GB", "保固至 2027/08/29"),
    ("【現貨 全新未拆封】Apple Mac mini M4晶片10 核心CPU與10 核心GPU 16G/512G SSD", "全新", "16GB", "512GB", ""),
    ("極新 Apple Mac Mini M4/16G/512G MU9E3TA/A A3238 蘋果保固到2027/8月", "近全新", "16GB", "512GB", "保固至 2027/08"),
    ("Mac mini M4 Pro 64GB/8TB 保固到2027/6 (歡迎私訊）", "", "64GB", "8TB", "保固至 2027/06"),
    ("【故障零件機】Mac Mini 2018 i7/8G/256G 附原廠盒裝電源，無法開機", "故障/零件機", "8GB", "256GB", ""),
    ("Apple Mac mini M4 2024 16G 256G A3238 銀 保內 二手主機 迷你主機", "二手", "16GB", "256GB", "保固中"),
    ("Macmini M4 16g 256gb 過保", "", "16GB", "256GB", "已過保/無保固"),
    ("Mac mini M4 CPU 16G Ram 512G SSD", "", "16GB", "512GB", ""),
    ("Apple M4 Mac mini 16+256G 福利品 一年保固", "福利品", "16GB", "256GB", "保固 1 年"),
    ("技嘉 RTX5070 WINDFORCE OC SFF 12G 三風扇 顯示卡", "", "12GB", "", ""),
    ("MacBook Air M1 8G/1TB 2025/03 購入 有購買證明 如新", "近全新", "8GB", "1TB", ""),
    ("iPhone 15 128G 購買日期：2024-11-05 保固中 二手", "二手", "", "128GB", "保固中"),
    ("【預購】Apple Mac mini M4 16G/256G 訂金", "預購", "16GB", "256GB", ""),
    ("Apple 2026 Mac mini M4 晶片 5G 網路 全新", "全新", "", "", ""),
    ("非全新 Mac mini 2020 M1 8/256", "二手", "", "", ""),
    ("Mac mini M4 2TB SSD 24G Ram 原廠保固3年", "", "24GB", "2TB", "保固 3 年"),
]


@pytest.mark.parametrize("title,condition,memory,storage,warranty", CASES)
def test_extract_fields_from_real_style_titles(title, condition, memory, storage, warranty):
    got = extract_fields(title)
    got.pop("規格")
    assert got == {
        "狀態": condition,
        "記憶體": memory,
        "儲存容量": storage,
        "保固": warranty,
    }, title


SPEC_CASES = [
    ("【艾爾巴二手】Apple Watch S10 A2999 46MM GPS 黑#智慧手錶", "46mm、GPS"),
    ("Apple Watch Series 10 42mm LTE 行動網路 鈦金屬", "42mm、LTE"),
    ("｜Apple Watch S10 42｜46mm｜10倍蝦幣", "42mm/46mm"),
    ("[龍龍3C] 蘋果 Apple Mac Mini M4Pro 24G 512GB", "M4 Pro"),
    ("Mac mini M4 16G/256G", "M4"),
    ("MacBook Pro 14吋 M3 Max 36G/1TB", "M3 Max、14吋"),
    ("技嘉 N507TGAMING OC-16GD RTX5070Ti 16G", "RTX 5070 Ti"),
    # 堆疊一堆型號的標題（多半是配件）不可信，留空
    ("M6 M5Pro M4Pro M4相容性Mac mini功能性外框架", ""),
    ("iPhone 15 Pro 128G", ""),
]


@pytest.mark.parametrize("title,spec", SPEC_CASES)
def test_extract_spec(title, spec):
    assert extract_fields(title)["規格"] == spec


def test_fields_no_longer_include_purchase_date_and_description_gives_no_spec():
    fields = extract_fields("Apple Watch S10 46mm GPS 2025/03 購入")
    assert "購買日期" not in fields and list(fields) == ["狀態", "規格", "記憶體", "儲存容量", "保固"]
    assert extract_fields("全系列 42mm 46mm GPS LTE 皆有現貨", from_description=True)["規格"] == ""
