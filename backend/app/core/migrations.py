"""DB 스키마 단계 목록 — 서버 시작 시 app.core.db.init_db 가 PRAGMA user_version 이후 단계만 차례로 실행한다.

스키마를 바꿀 때는 항상 목록 끝에 새 단계를 더한다 (이미 실행된 단계는 고치지 않는다).
v1 = 공용(설정 · 작업 실행 · LLM 사용량 · 호출 추적, Mallot Invest Agent 와 같은 모양) + Mallot 가계부 테이블의 마지막 모양
(거래 · 카테고리 · 내 계좌 · 정기지출 · 가맹점 규칙 · 캡쳐 판독 기록 · 가져오기 묶음). 그래서 Mallot 가계부 DB 의 같은 이름 테이블을
그대로 옮겨 올 수 있다 (scripts/import-mallot.py).
"""

MIGRATIONS: list[str] = [
    # v1: 공용 + 가계부
    """
    CREATE TABLE settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE runs (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        kind             TEXT    NOT NULL,              -- 작업 종류 (app.runs.runner 레지스트리 키)
        name             TEXT    NOT NULL,
        status           TEXT    NOT NULL DEFAULT 'queued'
                         CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
        params_json      TEXT    NOT NULL DEFAULT '{}',
        summary_json     TEXT,                          -- 끝난 뒤 결과 요약
        progress         REAL    NOT NULL DEFAULT 0,
        parent_id        INTEGER REFERENCES runs(id) ON DELETE SET NULL,   -- 이어 붙인 실행 (선택)
        artifact_path    TEXT,                          -- data 폴더 기준 상대 경로
        error            TEXT,
        cancel_requested INTEGER NOT NULL DEFAULT 0,
        created_at       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
        started_at       TEXT,
        finished_at      TEXT
    );
    CREATE TABLE run_metrics (
        run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        key    TEXT    NOT NULL,
        step   INTEGER NOT NULL,
        value  REAL    NOT NULL,
        PRIMARY KEY (run_id, key, step)
    );
    CREATE TABLE run_logs (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id  INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        ts      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime')),
        level   TEXT    NOT NULL DEFAULT 'info' CHECK (level IN ('debug', 'info', 'warn', 'error')),
        message TEXT    NOT NULL
    );
    CREATE TABLE llm_usage (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now', 'localtime')),
        feature            TEXT    NOT NULL,          -- capture_extract · spending_report · salary_analysis ...
        provider           TEXT    NOT NULL,          -- claude-agent-sdk (로컬 Claude Code 로그인 또는 API 키)
        model              TEXT    NOT NULL,
        input_tokens       INTEGER NOT NULL DEFAULT 0,
        output_tokens      INTEGER NOT NULL DEFAULT 0,
        cache_read_tokens  INTEGER NOT NULL DEFAULT 0,
        cache_write_tokens INTEGER NOT NULL DEFAULT 0,
        cost_usd           REAL,                      -- SDK 가 알려주는 API 요금 환산액 (구독 로그인이면 실제 청구 아님)
        duration_ms        INTEGER,
        api_duration_ms    INTEGER,
        turns              INTEGER,
        ok                 INTEGER NOT NULL DEFAULT 1,
        error              TEXT,
        run_id             INTEGER REFERENCES runs(id) ON DELETE SET NULL
    );
    CREATE TABLE trace_spans (
        id          TEXT    PRIMARY KEY,
        trace_id    TEXT    NOT NULL,                 -- 맨 위 span 의 id (실행 하나 · 비서 답 하나)
        parent_id   TEXT,
        run_id      INTEGER REFERENCES runs(id) ON DELETE CASCADE,
        kind        TEXT    NOT NULL CHECK (kind IN ('run', 'step', 'agent', 'llm', 'tool', 'event')),
        name        TEXT    NOT NULL,
        agent       TEXT,                             -- 이 span 을 일으킨 에이전트 키 (부모에게서 물려받음)
        status      TEXT    NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'ok', 'error', 'cancelled')),
        start_ms    REAL    NOT NULL,                 -- epoch 밀리초
        end_ms      REAL,
        duration_ms INTEGER,
        input_json  TEXT,
        output_json TEXT,
        attrs_json  TEXT    NOT NULL DEFAULT '{}',
        error       TEXT
    );
    CREATE TABLE accounts (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        name    TEXT NOT NULL,          -- 예: 국민 월급통장
        keyword TEXT NOT NULL DEFAULT '' -- 이체 상대가 이 문자열을 포함하면 내 계좌로 본다 (쉼표 구분)
    );
    CREATE TABLE categories (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL DEFAULT '',
        budget      INTEGER NOT NULL DEFAULT 0 CHECK (budget >= 0),
        sort_order  INTEGER NOT NULL DEFAULT 0,
        is_system   INTEGER NOT NULL DEFAULT 0  -- 삭제 불가 (기타)
    , icon TEXT NOT NULL DEFAULT '');
    CREATE TABLE extraction_logs (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
        image_sha256   TEXT    NOT NULL,
        image_path     TEXT,                 -- data 폴더 기준 상대 경로 (이미지 삭제 시 NULL)
        media_type     TEXT    NOT NULL,
        model          TEXT    NOT NULL,
        prompt_version TEXT    NOT NULL,
        duration_ms    INTEGER,
        status         TEXT    NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'confirmed', 'discarded', 'failed')),
        error          TEXT,
        raw_json       TEXT,                 -- LLM 원본 출력
        drafts_json    TEXT,                 -- 후처리(내 계좌·규칙·검증) 후 초안
        confirmed_json TEXT,                 -- 초안 순서대로 사용자가 저장한 값, 제외한 초안은 null
        confirmed_at   TEXT,
        ocr_text       TEXT,                 -- OCR(Unlimited-OCR-2)이 읽은 글 (OCR → LLM 판독일 때)
        note           TEXT                  -- 판독 경로 메모 (예: OCR 실패 → Vision)
    );
    CREATE TABLE import_batches (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        source      TEXT    NOT NULL CHECK (source IN ('banksalad')),
        file_name   TEXT    NOT NULL,
        file_sha256 TEXT    NOT NULL,
        period_from TEXT,
        period_to   TEXT,
        stats_json  TEXT    NOT NULL DEFAULT '{}',
        created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
    );
    CREATE TABLE merchant_rules (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        merchant_key TEXT    NOT NULL UNIQUE,
        category_id  INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
        source       TEXT    NOT NULL DEFAULT 'user' CHECK (source IN ('user', 'llm')),
        hits         INTEGER NOT NULL DEFAULT 1,
        updated_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
    );
    CREATE TABLE recurring_groups (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT    NOT NULL UNIQUE,
        kind       TEXT    NOT NULL DEFAULT 'expense' CHECK (kind IN ('saving', 'expense')),
        icon       TEXT    NOT NULL DEFAULT '',
        sort_order INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE recurring_items (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        name          TEXT    NOT NULL,
        group_id      INTEGER NOT NULL REFERENCES recurring_groups(id) ON DELETE RESTRICT,
        icon          TEXT    NOT NULL DEFAULT '',
        amount        INTEGER NOT NULL DEFAULT 0 CHECK (amount >= 0),
        day_of_month  INTEGER CHECK (day_of_month IS NULL OR day_of_month BETWEEN 1 AND 31),
        match_keyword TEXT    NOT NULL DEFAULT '',
        memo          TEXT    NOT NULL DEFAULT '',
        active        INTEGER NOT NULL DEFAULT 1,
        sort_order    INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE recurring_skips (
        item_id      INTEGER NOT NULL REFERENCES recurring_items(id) ON DELETE CASCADE,
        period_start TEXT    NOT NULL,            -- 수입일 기준 기간의 시작일 (YYYY-MM-DD)
        created_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
        PRIMARY KEY (item_id, period_start)
    );
    CREATE TABLE recurring_candidates (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        merchant_key TEXT    NOT NULL,
        cadence      TEXT    NOT NULL CHECK (cadence IN ('monthly', 'weekly')),
        merchant     TEXT    NOT NULL DEFAULT '',    -- 화면용 가맹점 이름 (가장 많이 쓴 표기)
        amount       INTEGER NOT NULL,               -- 최근 결제 금액 (자동 매칭은 금액이 같아야 해서 이 값을 제안)
        keyword      TEXT    NOT NULL DEFAULT '',    -- 제안 매칭 키워드
        anchor       INTEGER NOT NULL,               -- 매월 n일 / 요일 (0 = 월)
        occurrences  INTEGER NOT NULL DEFAULT 0,
        first_on     TEXT,
        last_on      TEXT,
        next_on      TEXT,                           -- 다음 예상 결제일
        confidence   REAL    NOT NULL DEFAULT 0,
        stats_json   TEXT    NOT NULL DEFAULT '{}',  -- 근거(거래 id·날짜·금액 범위·경고)와 등록 제안
        status       TEXT    NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected')),
        recurring_id INTEGER REFERENCES recurring_items(id) ON DELETE SET NULL,  -- 수락해서 만들거나 합친 정기지출
        created_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
        updated_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
        decided_at   TEXT
    );
    CREATE TABLE transactions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        occurred_on     TEXT    NOT NULL,
        occurred_time   TEXT,
        type            TEXT    NOT NULL CHECK (type IN ('expense', 'income', 'transfer', 'refund')),
        transfer_kind   TEXT    CHECK (transfer_kind IN ('internal', 'external')),
        amount          INTEGER NOT NULL CHECK (amount >= 0),
        merchant        TEXT    NOT NULL DEFAULT '',
        merchant_key    TEXT    NOT NULL DEFAULT '',
        category_id     INTEGER REFERENCES categories(id) ON DELETE SET NULL,
        category_source TEXT    CHECK (category_source IN ('user', 'llm', 'rule', 'import')),
        recurring_id    INTEGER REFERENCES recurring_items(id) ON DELETE SET NULL,
        payment_method  TEXT    NOT NULL DEFAULT '',
        memo            TEXT    NOT NULL DEFAULT '',
        needs_review    INTEGER NOT NULL DEFAULT 0,
        source          TEXT    NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'image', 'import')),
        extraction_id   INTEGER REFERENCES extraction_logs(id) ON DELETE SET NULL,
        import_batch_id INTEGER REFERENCES import_batches(id) ON DELETE CASCADE,
        external_id     TEXT    UNIQUE,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
        CHECK ((type = 'transfer') = (transfer_kind IS NOT NULL))
    );
    CREATE INDEX idx_extraction_logs_created ON extraction_logs (created_at);
    CREATE INDEX idx_transactions_occurred_on ON transactions (occurred_on);
    CREATE INDEX idx_transactions_merchant_key ON transactions (merchant_key);
    CREATE INDEX idx_transactions_import_batch ON transactions (import_batch_id);
    CREATE INDEX idx_recurring_candidates_key ON recurring_candidates (merchant_key, cadence);
    CREATE INDEX idx_runs_kind ON runs (kind, id);
    CREATE INDEX idx_llm_usage_created ON llm_usage (created_at);
    CREATE INDEX idx_llm_usage_feature ON llm_usage (feature, created_at);
    CREATE INDEX idx_trace_spans_trace ON trace_spans (trace_id, start_ms);
    CREATE INDEX idx_trace_spans_run ON trace_spans (run_id);
    CREATE INDEX idx_trace_spans_start ON trace_spans (start_ms);

    CREATE TABLE salary_slips (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        pay_month            TEXT    NOT NULL,                 -- 귀속 월 YYYY-MM (일한 달)
        paid_on              TEXT,                             -- 지급일 YYYY-MM-DD (가계부 입금과 맞춰 본다)
        kind                 TEXT    NOT NULL DEFAULT 'regular' CHECK (kind IN ('regular', 'bonus', 'retro', 'other')),
        employer             TEXT    NOT NULL DEFAULT '',
        taxable_pay          INTEGER NOT NULL DEFAULT 0 CHECK (taxable_pay >= 0),     -- 과세 지급액
        nontaxable_pay       INTEGER NOT NULL DEFAULT 0 CHECK (nontaxable_pay >= 0),  -- 비과세 (식대 등)
        national_pension     INTEGER NOT NULL DEFAULT 0,
        health_insurance     INTEGER NOT NULL DEFAULT 0,
        long_term_care       INTEGER NOT NULL DEFAULT 0,
        employment_insurance INTEGER NOT NULL DEFAULT 0,
        income_tax           INTEGER NOT NULL DEFAULT 0,
        local_income_tax     INTEGER NOT NULL DEFAULT 0,
        other_deductions     INTEGER NOT NULL DEFAULT 0,       -- 노조비 · 사우회 · 대출 상환 등
        net_pay              INTEGER,                          -- 명세서의 실지급액 (비우면 지급 − 공제)
        items_json           TEXT    NOT NULL DEFAULT '[]',    -- 명세서 줄 [{label, amount, kind}] (판독 · 직접)
        memo                 TEXT    NOT NULL DEFAULT '',
        source               TEXT    NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'image')),
        created_at           TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
    );
    CREATE INDEX idx_salary_slips_month ON salary_slips (pay_month);
    INSERT INTO settings (key, value) VALUES ('owner_name', '"나"'), ('monthly_income', '0'), ('payday', '25');
    INSERT INTO categories (name, description, budget, sort_order, is_system, icon) VALUES
        ('식비', '외식, 배달, 식료품', 0, 1, 0, '🍚'),
        ('커피', '카페, 커피·음료', 0, 2, 0, '☕'),
        ('생활비', '식료품을 제외한 필수 생활용품, 교통, 공과금 등', 0, 3, 0, '🧺'),
        ('여가·유흥', '술자리, 취미, 쇼핑 등 꼭 필요하지 않은 개인 소비', 0, 4, 0, '🎉'),
        ('기타', '추가 저금, 투자, 분류가 필요한 타 계좌 이체 등', 0, 5, 1, '📌');
    INSERT INTO recurring_groups (id, name, kind, icon, sort_order) VALUES
        (1, '저금', 'saving', '💰', 1), (2, '투자', 'saving', '📈', 2), (3, '보험', 'expense', '🛡️', 3),
        (4, '구독', 'expense', '📺', 4), (5, '교통', 'expense', '🚇', 5), (6, '통신', 'expense', '📱', 6),
        (7, '기타', 'expense', '📌', 7);
    INSERT INTO recurring_items (name, group_id, icon, match_keyword, sort_order) VALUES
        ('예·적금', 1, '🏦', '적금,예금', 1), ('주택청약', 1, '🏠', '청약', 2), ('ISA 자동이체', 2, '📈', 'ISA', 3),
        ('보험료', 3, '🛡️', '보험', 4), ('구독료', 4, '📺', '', 5), ('교통비', 5, '🚇', '티머니,교통', 6),
        ('통신비', 6, '📱', '통신', 7);
    """,
    # v2 (접속 기록): IP 마다 하루 묶음 · 로그인 사건 · 한국 밖 접속 경보 (app/auth/access_log.py)
    """
    CREATE TABLE access_ips (
        day        TEXT    NOT NULL,
        ip         TEXT    NOT NULL,                -- CF-Connecting-IP, 터널 밖이면 local
        country    TEXT,                            -- CF-IPCountry (KR · US · XX 알 수 없음 · T1 Tor)
        roles      TEXT    NOT NULL DEFAULT '',     -- 그날 그 IP 의 역할들 (admin · viewer · none)
        requests   INTEGER NOT NULL DEFAULT 0,
        denied     INTEGER NOT NULL DEFAULT 0,      -- 401 · 403 · 429
        first_at   TEXT    NOT NULL,
        last_at    TEXT    NOT NULL,
        last_path  TEXT    NOT NULL DEFAULT '',
        user_agent TEXT    NOT NULL DEFAULT '',
        PRIMARY KEY (day, ip)
    );
    CREATE TABLE access_events (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        day        TEXT    NOT NULL,
        at         TEXT    NOT NULL,
        ip         TEXT    NOT NULL,
        country    TEXT,
        kind       TEXT    NOT NULL,                -- login · share_enter · logout
        ok         INTEGER NOT NULL,
        note       TEXT    NOT NULL DEFAULT '',
        user_agent TEXT    NOT NULL DEFAULT ''
    );
    CREATE INDEX idx_access_events_day ON access_events (day);
    CREATE TABLE access_alerts (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        day        TEXT    NOT NULL,
        ip         TEXT    NOT NULL,
        country    TEXT,
        reason     TEXT    NOT NULL DEFAULT '',
        created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
        acked_at   TEXT,                            -- 관리자가 '확인' 누른 때
        UNIQUE (day, ip)
    );
    """,
    # v3 (급여): 연봉 기준으로 만든 명세서(source='estimate') — CHECK 를 바꾸려고 테이블을 다시 만든다 (app/salary/contract.py)
    """
    CREATE TABLE salary_slips_new (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        pay_month            TEXT    NOT NULL,
        paid_on              TEXT,
        kind                 TEXT    NOT NULL DEFAULT 'regular' CHECK (kind IN ('regular', 'bonus', 'retro', 'other')),
        employer             TEXT    NOT NULL DEFAULT '',
        taxable_pay          INTEGER NOT NULL DEFAULT 0 CHECK (taxable_pay >= 0),
        nontaxable_pay       INTEGER NOT NULL DEFAULT 0 CHECK (nontaxable_pay >= 0),
        national_pension     INTEGER NOT NULL DEFAULT 0,
        health_insurance     INTEGER NOT NULL DEFAULT 0,
        long_term_care       INTEGER NOT NULL DEFAULT 0,
        employment_insurance INTEGER NOT NULL DEFAULT 0,
        income_tax           INTEGER NOT NULL DEFAULT 0,
        local_income_tax     INTEGER NOT NULL DEFAULT 0,
        other_deductions     INTEGER NOT NULL DEFAULT 0,
        net_pay              INTEGER,
        items_json           TEXT    NOT NULL DEFAULT '[]',
        memo                 TEXT    NOT NULL DEFAULT '',
        source               TEXT    NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'image', 'estimate')),
        created_at           TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
    );
    INSERT INTO salary_slips_new SELECT * FROM salary_slips;
    DROP TABLE salary_slips;
    ALTER TABLE salary_slips_new RENAME TO salary_slips;
    CREATE INDEX idx_salary_slips_month ON salary_slips (pay_month);
    """,
]
