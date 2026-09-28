-- Engagement metadata and emotion vectors live in separate tables: a reply is scraped once
-- but can be re-scored (another backend or checkpoint) without touching its metrics.
-- No FOREIGN KEY from reply_emotions: DuckDB refuses to upsert a referenced replies row,
-- and re-scraping a reply to refresh its counts is an upsert.

CREATE TABLE replies (
    comment_id       VARCHAR PRIMARY KEY,
    post_id          VARCHAR NOT NULL,      -- the post being replied to
    profile_username VARCHAR NOT NULL,      -- author of that post (the monitored profile)
    twitter_username VARCHAR NOT NULL,      -- author of the reply
    reply_content    VARCHAR NOT NULL,
    like_count       BIGINT NOT NULL DEFAULT 0,
    view_count       BIGINT NOT NULL DEFAULT 0,
    reply_count      BIGINT NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL,
    scraped_at       TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);

CREATE INDEX replies_profile_time ON replies (profile_username, created_at);

-- One column per emotion, P(yes) from Mood Lab's yes/no questions (server/presets.py).
CREATE TABLE reply_emotions (
    comment_id  VARCHAR PRIMARY KEY,        -- replies.comment_id
    joy         DOUBLE NOT NULL,
    sadness     DOUBLE NOT NULL,
    anger       DOUBLE NOT NULL,
    fear        DOUBLE NOT NULL,
    surprise    DOUBLE NOT NULL,
    disgust     DOUBLE NOT NULL,
    bluff       DOUBLE NOT NULL,
    backend     VARCHAR NOT NULL,           -- laya | jev
    model       VARCHAR NOT NULL,           -- e.g. "laya/multilingual on cuda"
    analyzed_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);
