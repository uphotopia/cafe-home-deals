#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
쿠팡 파트너스 Open API 수집기
================================

카페 사장님 주간 필수템 + 가정 생필품 + 자취·살림꿀템 + 가성비 겨울옷 +
가성비 식료품 + 카메라·이어폰 + 골드박스 + 쿠팡 PL 특가를
쿠팡 파트너스 Open API에서 수집해 `data/deals.json` 으로 저장한다.

인증 정보 우선순위
------------------
1. 환경변수 `COUPANG_ACCESS_KEY` / `COUPANG_SECRET_KEY`  (GitHub Actions 등)
2. 로컬 개발용 `.config/coupang_partners.json`
   (`{"access_key": "...", "secret_key": "..."}`)
   - 스크립트 위치 기준 `../.config/`, `../../.config/`, 저장소 루트 기준
     `.config/`, `../.config/` 순서로 찾는다.

주의
----
- 비밀키는 절대 `data/deals.json` 이나 프론트엔드 파일에 기록하지 않는다.
  이 스크립트가 만드는 산출물에는 상품 정보만 들어간다.
- `/products/search` 는 분당 50회 제한 → 요청 사이에 기본 0.45초 대기,
  429 응답 시 지수 백오프로 재시도한다.

사용법
------
    python3 scripts/fetch_deals.py
    python3 scripts/fetch_deals.py --out data/deals.json --delay 0.5
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

API_HOST = "https://api-gateway.coupang.com"
API_BASE = "/v2/providers/affiliate_open_api/apis/openapi/v1"
KST = timezone(timedelta(hours=9))

PARTNERS_TAG = "AF9362379"

DISCLOSURE = (
    "이 사이트는 쿠팡 파트너스 활동의 일환으로, "
    "이에 따른 일정액의 수수료를 제공받습니다."
)
PRICE_NOTICE = (
    "표시된 가격은 마지막 API 갱신 시점 기준이며, "
    "쿠팡 사이트의 실시간 변동에 따라 차이가 있을 수 있습니다."
)

# ---------------------------------------------------------------------------
# 수집 대상 정의
# ---------------------------------------------------------------------------

SEARCH_SECTIONS = [
    (
        "cafe",
        [
            (
                "컵·뚜껑·홀더",
                [
                    "테이크아웃 아이스컵 16온스",
                    "92파이 컵뚜껑",
                    "테이크아웃 컵홀더",
                    "2구 캐리어",
                    "테이크아웃 핫컵 12온스",
                ],
            ),
            (
                "빨대·냅킨·소모품",
                [
                    "카페 빨대 개별포장",
                    "업소용 냅킨",
                    "점보롤 화장지",
                    "업소용 주방세제",
                ],
            ),
            (
                "원두·우유·시럽",
                [
                    "업소용 원두커피 1kg",
                    "멸균우유 1000ml",
                    "카페 바닐라시럽",
                    "아이스티 복숭아 대용량",
                ],
            ),
        ],
    ),
    (
        "home",
        [
            (
                "휴지·물티슈",
                ["3겹 롤화장지 30롤", "대용량 캡형 물티슈", "키친타올"],
            ),
            (
                "세제·청소",
                [
                    "대용량 액체 세탁세제",
                    "섬유유연제 대용량",
                    "주방세제 리필",
                    "위생백 롤백",
                ],
            ),
        ],
    ),
    (
        "living",
        [
            (
                "수납·정리",
                [
                    "무타공 욕실선반",
                    "접이식 수납박스",
                    "논슬립 옷걸이",
                    "무타공 접착 후크",
                ],
            ),
            (
                "주방·살림",
                [
                    "실리콘 지퍼백",
                    "밀폐 음식물쓰레기통",
                    "싱크대 물막이",
                ],
            ),
            (
                "자취·생활꿀템",
                [
                    "배수구 클리너",
                    "규조토 발매트",
                    "1인용 전기방석",
                ],
            ),
        ],
    ),
    (
        "winter",
        [
            (
                "패딩·아우터",
                ["경량패딩", "플리스 자켓"],
            ),
            (
                "이너웨어·상의",
                ["발열내의", "기모 맨투맨"],
            ),
            (
                "홈웨어·방한용품",
                ["겨울 잠옷", "남성 파자마", "방한장갑", "넥워머", "겨울 양말"],
            ),
        ],
    ),
    (
        "food",
        [
            (
                "즉석밥·면류",
                ["즉석밥", "컵라면", "신라면 멀티팩"],
            ),
            (
                "쌀·잡곡",
                ["쌀 10kg", "쌀 20kg", "잡곡"],
            ),
            (
                "생수·음료",
                ["생수 2L 무라벨", "음료 대용량"],
            ),
            (
                "간편식·밀키트",
                ["밀키트", "즉석국"],
            ),
            (
                "냉동식품·만두",
                ["냉동만두"],
            ),
            (
                "견과류·간식",
                ["견과류", "간식 개별포장"],
            ),
        ],
    ),
    (
        # 강의·회의 녹음용 초소형카메라 + 이어폰 (무선·포터블 포함) + AI 제품 + 금속탐지기
        # '강의녹음 카메라'·'미니 카메라'·'무선 미니 카메라'처럼 무관한 상품
        # (토이카메라·마이크·CCTV·폰케이스)이 섞이는 검색어는 빼고, 실제로
        # 초소형/바디캠 상품이 나오는 검색어만 쓴다.
        # AI 기능 제품이 일반 녹음기 검색과 섞이지 않도록 AI 그룹을 먼저 수집한다.
        "digital",
        [
            (
                "AI 녹음기·이어폰",
                ["AI 녹음기", "AI 보이스레코더", "AI 이어폰"],
            ),
            (
                "강의녹음 카메라",
                ["초소형 카메라", "초소형 무선 카메라", "바디캠", "미니 바디캠", "웨어러블 카메라"],
            ),
            (
                "소형 녹음기",
                ["보이스레코더", "초소형 녹음기", "강의녹음기"],
            ),
            (
                "무선 이어폰",
                ["무선 이어폰", "블루투스 이어폰", "오픈형 블루투스 이어폰"],
            ),
            (
                "유선 이어폰",
                ["C타입 유선이어폰", "유선 이어폰"],
            ),
            (
                "금속탐지기",
                ["금속탐지기", "휴대용 금속탐지기", "보물탐지기"],
            ),
        ],
    ),
]

BEST_CATEGORIES = [
    ("1014", "생활용품 베스트", "home"),
    ("1013", "주방용품 베스트", "home"),
    ("1012", "식품 베스트", "food"),
]

SEARCH_LIMIT = 10
BEST_LIMIT = 20
GOLDBOX_LIMIT = 30
PL_LIMIT = 30

# 이미지 CDN 정규화 관련 상수
AD_IMAGE_HOST = "ads-partners.coupang.com"
CDN_HOST_SUFFIX = "coupangcdn.com"
IMAGE_MAX_HOPS = 3
IMAGE_WORKERS = 16
IMAGE_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; SM-S911N) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36"
)

# 소분류에 어색하게 섞이는 상품을 이름으로 걸러낸다 (섹션 키 → 금지어).
# '웨어러블 카메라' 같은 검색어가 스마트워치·스트랩까지, '초소형 카메라'가
# 홈캠·CCTV까지 함께 주기 때문이다.
EXCLUDE_PATTERNS = {
    "digital": (
        "스마트워치", "스트랩", "지지대", "거치대", "삼각대",
        "케이스", "필름", "보호캡",
        "홈캠", "cctv", "감시카메라", "웹캠", "ip 카메라",
    ),
}

SECTION_LABELS = {
    "cafe": "☕ 카페 사장님 필수템",
    "home": "🏠 가정 생필품",
    "living": "🧺 자취·살림꿀템",
    "winter": "🧥 가성비 겨울옷",
    "food": "🛒 가성비 식료품",
    "digital": "🎧 디지털·가전",
    "goldbox": "⚡ 오늘의 골드박스",
    "pl": "🔥 쿠팡 PL 특가",
}

# 제목에서 용량/수량을 가볍게 뽑아 보조 표기로만 쓴다 (틀리면 표시하지 않음).
UNIT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(kg|mL|ml|ML|L|리터|온스|oz|박스|세트|롤|겹|입|매|개|포|장|봉|캔|병|정|g)"
)
UNIT_BLACKLIST = {"1", "2"}  # "2개" 같은 애매한 소량 표기는 굳이 노출하지 않음


# ---------------------------------------------------------------------------
# 인증 정보
# ---------------------------------------------------------------------------


def load_credentials() -> tuple[str, str]:
    access = os.environ.get("COUPANG_ACCESS_KEY", "").strip()
    secret = os.environ.get("COUPANG_SECRET_KEY", "").strip()
    if access and secret:
        return access, secret

    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, os.pardir, os.pardir, ".config", "coupang_partners.json"),
        os.path.join(here, os.pardir, ".config", "coupang_partners.json"),
        os.path.join(os.getcwd(), ".config", "coupang_partners.json"),
        os.path.join(os.getcwd(), os.pardir, ".config", "coupang_partners.json"),
    ]
    for path in candidates:
        path = os.path.normpath(path)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fp:
                cfg = json.load(fp)
            acc = str(cfg.get("access_key", "")).strip()
            sec = str(cfg.get("secret_key", "")).strip()
            if acc and sec:
                return acc, sec

    sys.exit(
        "인증 정보를 찾지 못했습니다. 환경변수 COUPANG_ACCESS_KEY / "
        "COUPANG_SECRET_KEY 를 설정하거나 .config/coupang_partners.json 을 준비하세요."
    )


# ---------------------------------------------------------------------------
# API 호출
# ---------------------------------------------------------------------------


class CoupangClient:
    def __init__(self, access_key: str, secret_key: str, delay: float = 0.45):
        self.access_key = access_key
        self.secret_key = secret_key
        self.delay = max(0.0, delay)
        self.request_count = 0
        self.errors: list[str] = []
        self._last_call = 0.0

    def _sign(self, method: str, path: str, query: str) -> str:
        signed_at = time.strftime("%y%m%dT%H%M%SZ", time.gmtime())
        message = signed_at + method + path + query
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return (
            "CEA algorithm=HmacSHA256, access-key={}, signed-date={}, signature={}".format(
                self.access_key, signed_at, signature
            )
        )

    def get(self, path: str, params: dict | None = None, retries: int = 3):
        query = urllib.parse.urlencode(params or {})
        url = API_HOST + path + ("?" + query if query else "")
        last_err = None

        for attempt in range(retries):
            # 요청 간 최소 간격 유지 (Rate limit: search 분당 50회)
            gap = time.time() - self._last_call
            if gap < self.delay:
                time.sleep(self.delay - gap)
            self._last_call = time.time()

            req = urllib.request.Request(
                url,
                method="GET",
                headers={
                    "Authorization": self._sign("GET", path, query),
                    "Content-Type": "application/json;charset=UTF-8",
                },
            )
            try:
                self.request_count += 1
                with urllib.request.urlopen(req, timeout=30) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                if str(payload.get("rCode")) not in ("0", "None"):
                    raise RuntimeError(
                        "API rCode={} rMessage={}".format(
                            payload.get("rCode"), payload.get("rMessage")
                        )
                    )
                return payload.get("data")
            except urllib.error.HTTPError as exc:
                body = ""
                try:
                    body = exc.read().decode("utf-8", "replace")[:300]
                except Exception:
                    pass
                last_err = "HTTP {} {}".format(exc.code, body)
                if exc.code in (429, 500, 502, 503, 504):
                    time.sleep(1.5 * (attempt + 1))
                    continue
                break
            except Exception as exc:  # noqa: BLE001 - 네트워크/파싱 오류 모두 재시도
                last_err = "{}: {}".format(type(exc).__name__, exc)
                time.sleep(1.2 * (attempt + 1))
                continue

        self.errors.append("{} → {}".format(path + ("?" + query if query else ""), last_err))
        return None


# ---------------------------------------------------------------------------
# 정규화
# ---------------------------------------------------------------------------


def _compact(text: str) -> str:
    """비교용 문자열: 소문자 + 공백·기호 제거."""
    return re.sub(r"[^0-9a-z가-힣]", "", (text or "").lower())


def _keyword_needles(keyword: str) -> list[str]:
    """키워드에서 '상품명에 있으면 관련 있다'고 볼 조각들을 만든다.

    토큰이 2글자 이상이면 2글자 조각(bigram), 1글자면 그 글자 자체.
    ('쌀 10kg' → ['쌀', '10', '0k', 'kg'])
    """
    needles: list[str] = []
    for token in (keyword or "").split():
        packed = _compact(token)
        if len(packed) < 2:
            if packed:
                needles.append(packed)
            continue
        for i in range(len(packed) - 1):
            needles.append(packed[i:i + 2])
    return needles


def keyword_matches(items: list[dict], keyword: str) -> bool:
    """검색 결과가 키워드와 실제로 관련 있는지 확인한다.

    쿠팡 파트너스 `/products/search` 는 키워드에 맞는 상품이 없으면
    화장지·건전지·숙박권 같은 무관한 인기 상품을 대신 돌려준다. 그런 응답이
    사이트에 섞이지 않도록, 결과 중 최소 1건이라도 키워드 조각을 포함할 때만
    그 응답을 받아들인다.
    """
    needles = _keyword_needles(keyword)
    if not needles:
        return True
    for raw in items:
        name = _compact(raw.get("productName") or "")
        if not name:
            continue
        if any(needle in name for needle in needles):
            return True
    return False


def parse_unit_hint(name: str) -> str | None:
    """제목에서 '1000개', '1kg', '30롤' 같은 용량/수량 표기를 뽑아낸다."""
    if not name:
        return None
    found: list[str] = []
    for match in UNIT_RE.finditer(name):
        number, unit = match.group(1), match.group(2)
        if number in UNIT_BLACKLIST:
            continue
        token = "{}{}".format(number, unit)
        if token not in found:
            found.append(token)
        if len(found) >= 3:
            break
    return " · ".join(found) if found else None


def normalize_price(value) -> int | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    return int(round(price))


def normalize_product(raw: dict, section: str, sub_category: str, keyword: str,
                      rank: int) -> dict | None:
    product_id = raw.get("productId")
    url = raw.get("productUrl") or ""
    name = (raw.get("productName") or "").strip()
    if not product_id or not url or not name:
        return None
    if PARTNERS_TAG not in url:
        # 파트너스 추적 태그가 없는 링크는 수익 링크가 아니므로 제외
        return None
    bad_words = EXCLUDE_PATTERNS.get(section, ())
    if bad_words:
        lowered = name.lower()
        if any(bad in lowered for bad in bad_words):
            # 섹션 소분류와 무관한 상품(예: 웨어러블 카메라 검색의 스마트워치)은 제외
            return None

    product = {
        "productId": int(product_id),
        "productName": name,
        "productPrice": normalize_price(raw.get("productPrice")),
        "productImage": raw.get("productImage") or "",
        "productUrl": url,
        "isRocket": bool(raw.get("isRocket")),
        "isFreeShipping": bool(raw.get("isFreeShipping")),
        "section": section,
        "subCategory": sub_category,
        "keyword": keyword,
        "rank": int(raw.get("rank") or rank),
        "categoryName": raw.get("categoryName") or "",
        "unitHint": parse_unit_hint(name),
    }
    return product


def collect_search(client: CoupangClient, section: str, groups) -> tuple[list[dict], dict]:
    products: list[dict] = []
    seen: set[int] = set()
    counts: dict[str, int] = {}

    for sub_category, keywords in groups:
        counts.setdefault(sub_category, 0)
        for keyword in keywords:
            data = client.get(
                API_BASE + "/products/search",
                {"keyword": keyword, "limit": SEARCH_LIMIT},
            )
            items = data if isinstance(data, list) else []
            if isinstance(data, dict):
                items = data.get("productData") or []
            if items and not keyword_matches(items, keyword):
                # 키워드에 맞는 상품이 없어 쿠팡이 무관한 인기 상품을 대신 준 경우
                print(
                    "  · [{}] {} → 대체 추천만 응답, 건너뜀".format(sub_category, keyword),
                    flush=True,
                )
                continue
            added = 0
            for idx, raw in enumerate(items, start=1):
                product = normalize_product(raw, section, sub_category, keyword, idx)
                if not product or product["productId"] in seen:
                    continue
                seen.add(product["productId"])
                products.append(product)
                added += 1
            counts[sub_category] += added
            print(
                "  · [{}] {} → {}건".format(sub_category, keyword, added),
                flush=True,
            )
    return products, counts


def collect_simple(client: CoupangClient, path: str, params: dict, section: str,
                   sub_category: str, keyword: str) -> list[dict]:
    data = client.get(path, params)
    items = data if isinstance(data, list) else []
    if isinstance(data, dict):
        items = data.get("productData") or []
    products: list[dict] = []
    seen: set[int] = set()
    for idx, raw in enumerate(items, start=1):
        product = normalize_product(raw, section, sub_category, keyword, idx)
        if not product or product["productId"] in seen:
            continue
        seen.add(product["productId"])
        products.append(product)
    print("  · [{}] {} → {}건".format(sub_category, keyword, len(products)), flush=True)
    return products


# ---------------------------------------------------------------------------
# 이미지 URL 정규화 (ads-partners → coupangcdn)
# ---------------------------------------------------------------------------
# 쿠팡 파트너스 API가 주는 productImage는 `https://ads-partners.coupang.com/image1/...`
# 형태인데, 이 호스트는 모바일 광고차단기(삼성 인터넷·AdGuard DNS·EasyList/YousList 등)가
# `ads-partners` 패턴으로 통째로 막는다. 같은 이미지는 쿠팡 이미지 CDN
# (`https://img*.coupangcdn.com/...`)으로 302 리다이렉트되므로, 리다이렉트를 따라가
# 최종 CDN URL을 저장해 두면 모바일에서도 썸네일이 보인다.
# productUrl(수익 링크)은 절대 건드리지 않는다.


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """리다이렉트를 자동으로 따라가지 않고 Location 헤더만 확인한다."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


def _image_headers() -> dict:
    return {
        "User-Agent": IMAGE_USER_AGENT,
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
    }


def _is_cdn_url(url: str) -> bool:
    host = urllib.parse.urlsplit(url or "").netloc.lower().split(":")[0]
    return host == CDN_HOST_SUFFIX or host.endswith("." + CDN_HOST_SUFFIX)


def _needs_resolve(url: str) -> bool:
    host = urllib.parse.urlsplit(url or "").netloc.lower().split(":")[0]
    return host == AD_IMAGE_HOST or host.endswith("." + AD_IMAGE_HOST)


def _probe(opener, url: str, method: str, timeout: float):
    """리다이렉트를 따라가지 않고 한 홉만 확인해 (status, location)을 돌려준다."""
    req = urllib.request.Request(url, method=method, headers=_image_headers())
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.headers.get("Location")
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location") if exc.headers else None
        return exc.code, location
    except Exception:  # noqa: BLE001 - 네트워크 오류는 실패로 처리
        return None, None


def resolve_cdn_url(image_url: str, opener=None, timeout: float = 8.0) -> str | None:
    """ads-partners 이미지 URL → 최종 coupangcdn.com URL. 실패하면 None."""
    if not _needs_resolve(image_url):
        return image_url if _is_cdn_url(image_url) else None

    opener = opener or urllib.request.build_opener(_NoRedirect)
    current = image_url

    for _ in range(IMAGE_MAX_HOPS):
        status, location = _probe(opener, current, "HEAD", timeout)
        if status is None or status >= 400 or not location:
            # HEAD를 막는 서버가 있어 GET으로 한 번 더 확인한다 (본문은 읽지 않음).
            status, location = _probe(opener, current, "GET", timeout)
        if not location:
            # 리다이렉트가 끝났다 → 현재 URL이 최종
            return current if _is_cdn_url(current) else None
        current = urllib.parse.urljoin(current, location)
        if _is_cdn_url(current):
            return current

    return current if _is_cdn_url(current) else None


def normalize_product_images(products: list[dict], workers: int = IMAGE_WORKERS) -> dict:
    """productImage 중 ads-partners URL만 CDN URL로 바꾼다. 실패분은 원래 URL 유지."""
    targets = sorted(
        {p["productImage"] for p in products if _needs_resolve(p.get("productImage") or "")}
    )
    stats = {"targets": len(targets), "converted": 0, "unresolved": 0, "failedSamples": []}
    if not targets:
        print("이미지 CDN 정규화: 대상 0건 (변환 불필요)", flush=True)
        return stats

    print("이미지 CDN 정규화: {}건 (병렬 {})".format(len(targets), workers), flush=True)
    resolved: dict[str, str] = {}
    failures: list[tuple[str, str]] = []
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(resolve_cdn_url, url): url for url in targets}
        for future in as_completed(futures):
            url = futures[future]
            done += 1
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                result = None
                failures.append((url, "{}: {}".format(type(exc).__name__, exc)))
            if result and result != url:
                resolved[url] = result
            elif not result:
                failures.append((url, "no cdn redirect"))
            if done % 25 == 0 or done == len(targets):
                print(
                    "  · {}/{} 확인 (변환 {}건)".format(done, len(targets), len(resolved)),
                    flush=True,
                )

    changed = 0
    for product in products:
        new_url = resolved.get(product.get("productImage") or "")
        if new_url and new_url != product.get("productImage"):
            product["productImage"] = new_url
            changed += 1

    stats["converted"] = changed
    stats["unresolved"] = len(targets) - len(resolved)
    stats["failedSamples"] = [u for u, _ in failures[:3]]
    print(
        "  → 변환 완료 {}건 / 실패·미해결 {}건 (원래 URL 유지)".format(
            changed, stats["unresolved"]
        ),
        flush=True,
    )
    return stats


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="쿠팡 파트너스 Open API 최저가 수집기")
    parser.add_argument(
        "--out",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "data", "deals.json"),
        help="출력 JSON 경로 (기본: data/deals.json)",
    )
    parser.add_argument("--delay", type=float, default=1.4, help="API 요청 사이 대기 초 (기본 1.4)")
    args = parser.parse_args()

    out_path = os.path.normpath(os.path.abspath(args.out))
    access, secret = load_credentials()
    client = CoupangClient(access, secret, delay=args.delay)

    started = time.time()
    print("쿠팡 파트너스 데이터 수집 시작", flush=True)

    all_products: list[dict] = []
    sub_counts: dict[str, dict[str, int]] = {}
    section_counts: dict[str, int] = {}

    for section, groups in SEARCH_SECTIONS:
        print("[{}] {}".format(section, SECTION_LABELS[section]), flush=True)
        products, counts = collect_search(client, section, groups)
        all_products.extend(products)
        section_counts[section] = len(products)
        sub_counts[section] = counts

    print("[best] 카테고리 베스트", flush=True)
    best_products: list[dict] = []
    best_seen: set[int] = set()
    for category_id, label, section in BEST_CATEGORIES:
        items = collect_simple(
            client,
            "{}/products/bestcategories/{}".format(API_BASE, category_id),
            {"limit": BEST_LIMIT},
            section,
            "카테고리 베스트",
            label,
        )
        added = 0
        for product in items:
            if product["productId"] in best_seen:
                continue
            best_seen.add(product["productId"])
            best_products.append(product)
            added += 1
        section_counts[section] = section_counts.get(section, 0) + added
        sub_counts.setdefault(section, {})["카테고리 베스트"] = (
            sub_counts.get(section, {}).get("카테고리 베스트", 0) + added
        )
    all_products.extend(best_products)

    print("[goldbox] {}".format(SECTION_LABELS["goldbox"]), flush=True)
    goldbox = collect_simple(
        client,
        API_BASE + "/products/goldbox",
        {"limit": GOLDBOX_LIMIT},
        "goldbox",
        "오늘의 특가",
        "골드박스",
    )
    all_products.extend(goldbox)
    section_counts["goldbox"] = len(goldbox)
    sub_counts["goldbox"] = {"오늘의 특가": len(goldbox)}

    print("[pl] {}".format(SECTION_LABELS["pl"]), flush=True)
    pl = collect_simple(
        client,
        API_BASE + "/products/coupangPL",
        {"limit": PL_LIMIT},
        "pl",
        "쿠팡 PL 브랜드",
        "쿠팡 PL",
    )
    all_products.extend(pl)
    section_counts["pl"] = len(pl)
    sub_counts["pl"] = {"쿠팡 PL 브랜드": len(pl)}

    # 모바일 광고차단기가 막는 ads-partners 이미지 URL을 쿠팡 이미지 CDN URL로 바꾼다.
    image_stats = normalize_product_images(all_products)

    elapsed = time.time() - started
    now = datetime.now(KST)

    payload = {
        "meta": {
            "updatedAt": now.isoformat(timespec="seconds"),
            "updatedAtDisplay": now.strftime("%Y.%m.%d %H:%M"),
            "generatedAtUtc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "totalCount": len(all_products),
            "sectionCounts": section_counts,
            "subCategoryCounts": sub_counts,
            "sectionLabels": SECTION_LABELS,
            "source": "쿠팡 파트너스 Open API",
            "partnersTag": PARTNERS_TAG,
            "requestCount": client.request_count,
            "elapsedSeconds": round(elapsed, 1),
            "imageCdnResolved": image_stats["converted"],
            "imageCdnUnresolved": image_stats["unresolved"],
            "disclosure": DISCLOSURE,
            "priceNotice": PRICE_NOTICE,
        },
        "products": all_products,
    }

    remaining_ad_images = sum(
        1 for p in all_products if AD_IMAGE_HOST in (p.get("productImage") or "")
    )
    if remaining_ad_images:
        print(
            "경고: ads-partners 이미지 URL이 {}건 남았습니다(변환 실패분).".format(
                remaining_ad_images
            ),
            flush=True,
        )
    else:
        print("확인: ads-partners 이미지 URL 0건.", flush=True)

    if len(all_products) < 30:
        print(
            "수집 결과가 너무 적습니다({}건). 기존 파일을 덮어쓰지 않고 종료합니다.".format(
                len(all_products)
            ),
            flush=True,
        )
        for err in client.errors:
            print("  ! " + err, flush=True)
        return 2

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=1)
        fp.write("\n")
    os.replace(tmp_path, out_path)

    print(
        "\n완료: {}건 → {} (요청 {}회, {:.1f}초)".format(
            len(all_products), out_path, client.request_count, elapsed
        ),
        flush=True,
    )
    for section in SECTION_LABELS:
        print("  - {:8s} {:3d}건".format(section, section_counts.get(section, 0)), flush=True)

    if client.errors:
        print("\n일부 요청 실패({}건):".format(len(client.errors)), flush=True)
        for err in client.errors:
            print("  ! " + err, flush=True)
        return 1
    print("\n모든 요청 성공, 오류 0건.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
