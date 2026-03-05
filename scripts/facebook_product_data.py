"""Utilities for collecting Facebook product signals via the official Graph API.

Limitations:
    - Facebook Marketplace listings are *not* exposed via Graph API endpoints.
      This module instead focuses on public Page posts, Shops catalog items, and Ads Library.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional

import requests

GRAPH_BASE = "https://graph.facebook.com/v19.0"
PRICE_PATTERN = re.compile(r"(?P<price>\d+[\.,]?\d*)\s?(?P<currency>[A-Z]{3}|₪|€|£|\$)")


@dataclass
class ProductPost:
    page_id: str
    post_id: str
    message: str
    permalink: str
    created_time: str
    detected_price: Optional[float]
    detected_currency: Optional[str]


class FacebookDataClient:
    def __init__(self, token: Optional[str] = None):
        self.token = token or os.environ.get("FACEBOOK_ACCESS_TOKEN")
        if not self.token:
            raise RuntimeError("FACEBOOK_ACCESS_TOKEN is missing.")

    def _request(self, path: str, params: Optional[dict] = None) -> dict:
        params = params or {}
        params.setdefault("access_token", self.token)
        response = requests.get(f"{GRAPH_BASE}/{path}", params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RuntimeError(payload["error"])
        return payload

    def get_page_posts(self, page_id: str, limit: int = 25) -> List[ProductPost]:
        fields = "id,message,permalink_url,created_time"
        data = self._request(f"{page_id}/posts", {"fields": fields, "limit": limit})
        posts = []
        for item in data.get("data", []):
            message = (item.get("message") or "").strip()
            match = PRICE_PATTERN.search(message)
            price = currency = None
            if match:
                price = float(match.group("price").replace(",", ""))
                currency = match.group("currency")
            posts.append(
                ProductPost(
                    page_id=page_id,
                    post_id=item["id"],
                    message=message,
                    permalink=item.get("permalink_url", ""),
                    created_time=item.get("created_time", ""),
                    detected_price=price,
                    detected_currency=currency,
                )
            )
        return posts

    def get_shop_items(self, page_id: str, limit: int = 25) -> list[dict]:
        """Fetch catalog products for a Page that has Shops enabled."""
        fields = "id,name,price,price_currency,retailer_id,product_type"
        return self._request(f"{page_id}/products", {"fields": fields, "limit": limit}).get("data", [])

    def search_ads_library(self, search_term: str, ad_type: str = "POLITICAL_AND_ISSUE_ADS", country: str = "US", limit: int = 50) -> list[dict]:
        params = {
            "search_terms": search_term,
            "ad_type": ad_type,
            "country": country,
            "limit": limit,
            "fields": "ad_creation_time,ad_creative_bodies,ad_creative_link_titles,page_name,publisher_platforms",
        }
        return self._request("ads_archive", params).get("data", [])


def dump_posts_to_jsonl(posts: Iterable[ProductPost], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for post in posts:
            fh.write(json.dumps(post.__dict__, ensure_ascii=False) + "\n")
