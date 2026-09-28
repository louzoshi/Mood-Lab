-- Custom yes/no questions (boar_emotion_radar/questions.py BOAR_QUESTIONS), one row per reply and question,
-- so questions can be added without a migration. Written with the reply's emotions.

CREATE TABLE reply_signals (
    comment_id  VARCHAR NOT NULL,           -- replies.comment_id
    question_id VARCHAR NOT NULL,           -- e.g. bug_report
    value       DOUBLE NOT NULL,            -- P(yes)
    PRIMARY KEY (comment_id, question_id)
);
