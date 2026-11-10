// Based on the data structure from web_server.py and scraper.py

export interface ProductInfo {
  "商品標題": string;
  "目前售價": string;
  "商品原價"?: string;
  "“想要”人數"?: string | number;
  "商品標籤"?: string[];
  "出貨地區"?: string;
  "賣家暱稱"?: string;
  "商品連結": string;
  "釋出時間"?: string;
  "商品ID": string;
  "商品圖片列表"?: string[];
  "商品主圖連結"?: string;
  "瀏覽量"?: string | number;
}

export interface SellerInfo {
  "賣家暱稱"?: string;
  "賣家頭像連結"?: string;
  "賣家個性簽名"?: string;
  "賣家在售/已售商品數"?: string;
  "賣家收到的評價總數"?: string;
  "賣家信用等級"?: string;
  "買家信用等級"?: string;
  "賣家註冊時長"?: string;
  "作為賣家的好評數"?: string;
  "作為賣家的好評率"?: string;
  "作為買家的好評數"?: string;
  "作為買家的好評率"?: string;
  "賣家釋出的商品列表"?: any[]; // Define more strictly if needed
  "賣家收到的評價列表"?: any[]; // Define more strictly if needed
}

export interface AiAnalysis {
  is_recommended: boolean;
  reason: string;
  analysis_source?: 'ai' | 'keyword';
  keyword_hit_count?: number;
  value_score?: number;
  value_summary?: string;
  prompt_version?: string;
  risk_tags?: string[];
  criteria_analysis?: Record<string, any>;
  matched_keywords?: string[];
  error?: string;
}

export interface PriceInsight {
  observation_count: number;
  current_price?: number | null;
  avg_price?: number | null;
  median_price?: number | null;
  min_price?: number | null;
  max_price?: number | null;
  market_avg_price?: number | null;
  market_median_price?: number | null;
  price_change_amount?: number | null;
  price_change_percent?: number | null;
  deal_score?: number | null;
  deal_label?: string;
  first_seen_at?: string | null;
  last_seen_at?: string | null;
}

export interface ResultInsights {
  market_summary: {
    sample_count: number;
    avg_price: number | null;
    median_price: number | null;
    min_price: number | null;
    max_price: number | null;
    snapshot_time?: string | null;
  };
  history_summary: {
    unique_items: number;
    sample_count: number;
    avg_price: number | null;
    median_price: number | null;
    min_price: number | null;
    max_price: number | null;
  };
  daily_trend: Array<{
    day: string;
    sample_count: number;
    avg_price: number | null;
    median_price: number | null;
    min_price: number | null;
    max_price: number | null;
  }>;
  latest_snapshot_at?: string | null;
}

export interface ResultItem {
  "爬取時間": string;
  "搜尋關鍵字": string;
  "任務名稱": string;
  "商品資訊": ProductInfo;
  "賣家資訊": SellerInfo;
  ai_analysis: AiAnalysis;
  price_insight?: PriceInsight;
  _status?: 'active' | 'hidden' | 'expired';
  _effective_hidden?: boolean;
  _hidden_reason?: 'manual' | 'rule' | 'expired' | null;
  _matched_blacklist_keywords?: string[];
}
