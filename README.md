# ☕🏠 사장님 &amp; 우리집 쿠팡 실시간 최저가

카페 사장님이 매주 사는 물품과 가정 생필품을 **쿠팡 파트너스 Open API**로 매시간 수집해
최저가·특가로 보여주는 정적 웹사이트입니다. GitHub Pages에서 무료로 호스팅되고,
GitHub Actions가 `data/deals.json`을 자동으로 갱신합니다.

- 라이브 사이트: `https://uphotopia.github.io/cafe-home-deals/`
- 저장소: `https://github.com/uphotopia/cafe-home-deals`

---

## 1. 무엇을 보여주나

| 섹션 | 수집 방법 | 소분류 |
| --- | --- | --- |
| ☕ 카페 사장님 필수템 | `GET /products/search` (키워드 13개) | 컵·뚜껑·홀더 / 빨대·냅킨·소모품 / 원두·우유·시럽 |
| 🏠 가정 생필품 | `GET /products/search` (키워드 10개) + `GET /products/bestcategories/{1014,1013,1012}` | 휴지·물티슈 / 세제·청소 / 생수·식료품 / 카테고리 베스트 |
| ⚡ 오늘의 골드박스 | `GET /products/goldbox` | 오늘의 특가 |
| 🔥 쿠팡 PL 특가 | `GET /products/coupangPL?limit=30` | 쿠팡 PL 브랜드 |

각 상품에는 `productId`, `productName`, `productPrice`, `productImage`, `productUrl`(파트너스
추적 URL 그대로), `isRocket`, `isFreeShipping`, `section`, `subCategory`, `keyword`, `rank`,
`unitHint`(상품명에서 읽은 용량·수량 표기)가 담깁니다.

## 2. 파일 구성

```
coupang-deals-site/
├── index.html                 # 사이트 마크업
├── styles.css                 # 반응형 스타일 (모바일 2열 ~ 데스크톱 5열)
├── app.js                     # 데이터 로딩 · 탭/칩/검색/정렬/필터 렌더링
├── data/deals.json            # 수집 결과 (자동 갱신, 커밋 대상)
├── scripts/fetch_deals.py     # 쿠팡 파트너스 API 수집기 (HMAC-SHA256 서명)
├── .github/workflow-template/update-deals.yml   # 매시간 자동 수집·커밋 워크플로(아래 5-B 참고)
├── .gitignore                 # .config/ 등 비밀 정보 제외
└── README.md
```

## 3. 로컬에서 실행

```bash
# 1) 인증 정보 (택 1)
export COUPANG_ACCESS_KEY="발급받은 액세스 키"
export COUPANG_SECRET_KEY="발급받은 시크릿 키"
#    또는 저장소 밖(상위 폴더)에 .config/coupang_partners.json 을 둔다
#    { "access_key": "...", "secret_key": "..." }

# 2) 데이터 수집
python3 scripts/fetch_deals.py

# 3) 미리보기 (file:// 로 열면 fetch 가 막히므로 로컬 서버 사용)
python3 -m http.server 8000
# 브라우저에서 http://localhost:8000 접속
```

수집기 동작 메모

- 요청 간 기본 0.45초 대기(`--delay`로 조절) — `/products/search` 분당 50회 제한 준수
- 429/5xx 응답은 지수 백오프로 최대 3회 재시도
- `productId` 기준 중복 제거, 파트너스 태그(`lptag=AF9362379`)가 없는 링크는 제외
- 수집 결과가 30건 미만이면 기존 `data/deals.json`을 덮어쓰지 않고 실패로 종료

## 4. GitHub Pages 배포

1. 저장소 **Settings → Pages → Build and deployment**
   - Source: `Deploy from a branch`
   - Branch: `main` / 폴더: `/ (root)`
2. 1~2분 뒤 `https://<계정>.github.io/<저장소>/` 로 접속되는지 확인
   - 이 저장소: <https://uphotopia.github.io/cafe-home-deals/>
3. `.nojekyll` 파일이 루트에 있으므로 Jekyll 처리 없이 정적 파일이 그대로 배포됩니다.
4. 데이터를 갱신한 뒤 Pages가 늦게 반영되면 **Actions → pages build and deployment → Re-run**

## 5. 자동 갱신

### 5-A. 현재 운영 방식 (설정 필요 없음)

지금은 사이트 주인의 어시스턴트 스케줄러가 **매시간** `scripts/fetch_deals.py`를 실행해
`data/deals.json`을 갱신하고 `main`에 커밋·푸시합니다. GitHub Actions 설정이 없어도
가격이 계속 최신으로 유지됩니다. (마지막 갱신 시각은 사이트 상단에 표시됩니다.)

### 5-B. GitHub Actions로 옮기려면 (선택)

워크플로 파일은 `.github/workflow-template/update-deals.yml`에 들어 있습니다.
GitHub의 저장소 설정 화면에서 ① Secrets 두 개를 등록하고 ② 템플릿 내용을
`.github/workflows/update-deals.yml`로 추가하면 Actions가 매시간 갱신을 맡습니다.
(Pickle의 GitHub 연결은 App 설치 토큰이라 워크플로 파일 푸시·Secrets 등록 권한이 없어
이 두 단계는 저장소 주인이 직접 해야 합니다.)

1. **Settings → Secrets and variables → Actions → New repository secret**

   | 이름 | 값 |
   | --- | --- |
   | `COUPANG_ACCESS_KEY` | 쿠팡 파트너스 액세스 키 |
   | `COUPANG_SECRET_KEY` | 쿠팡 파트너스 시크릿 키 |

   CLI로 등록할 때 (값이 셸 히스토리에 남지 않도록 파일에서 읽어 파이프):

   ```bash
   jq -r .access_key ~/.config/coupang_partners.json | gh secret set COUPANG_ACCESS_KEY
   jq -r .secret_key ~/.config/coupang_partners.json | gh secret set COUPANG_SECRET_KEY
   ```

2. **워크플로 추가** — `https://github.com/uphotopia/cafe-home-deals/new/main/.github/workflows`
   에서 파일 이름 `update-deals.yml`을 만들고 `.github/workflow-template/update-deals.yml`
   내용을 그대로 붙여 넣은 뒤 Commit.

3. **동작**
   - **스케줄**: `cron: "35 * * * *"` (UTC 기준 매시간 35분 = KST 매시간 35분)
     → 골드박스가 갱신되는 매일 07:30 KST 직후인 **07:35 KST**에 하루의 첫 갱신이 돕니다.
   - **수동 실행**: **Actions → Update deals data → Run workflow**
   - **흐름**: API 수집 → `data/deals.json` 검증(건수·파트너스 태그·키 미노출) → 변경 시에만 자동 커밋·푸시
   - GitHub의 스케줄은 혼잡하면 수 분~수십 분 늦게 시작될 수 있습니다.

## 6. 보안 수칙

- `access_key` / `secret_key`는 **저장소에 커밋하지 않습니다.** `.gitignore`에 `.config/`,
  `coupang_partners.json`, `.env`가 등록되어 있습니다.
- 프론트엔드(`index.html`, `app.js`, `styles.css`)와 `data/deals.json`에는 키가 들어가지
  않습니다. Actions 워크플로가 배포 전에 `data/deals.json` 안에 키 문자열이 없는지 검사합니다.
- 키가 노출되었다고 판단되면 쿠팡 파트너스에서 키를 재발급하고 Secrets를 교체하세요.

```bash
# 프론트엔드 파일에 키가 없는지 확인
grep -rEi "access_key|secret_key|COUPANG_" index.html app.js styles.css data/deals.json || echo "키 노출 없음"
```

## 7. 고지

> 이 사이트는 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.
> 표시된 가격은 마지막 API 갱신 시점 기준이며, 쿠팡 사이트의 실시간 변동에 따라 차이가 있을 수 있습니다.

가격·재고·배송 조건의 최종 확인은 쿠팡 상품 페이지에서 이루어집니다.
상품 이미지와 가격 정보의 저작권은 각 권리자(쿠팡 및 판매자)에게 있습니다.
