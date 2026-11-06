-- Content (derived from the pipeline; fully re-seedable)
CREATE TABLE lexemes (
  id             text PRIMARY KEY,
  lemma          text NOT NULL,
  pos            text NOT NULL CHECK (pos IN ('noun', 'verb', 'adjective', 'adverb')),
  level          text NOT NULL CHECK (level IN ('A1', 'A2', 'B1', 'B2', 'C1', 'C2')),
  semantic_group text,
  example        text
);
CREATE INDEX lexemes_level_idx ON lexemes (level);

CREATE TABLE definitions (
  id        bigserial PRIMARY KEY,
  lexeme_id text NOT NULL REFERENCES lexemes (id) ON DELETE CASCADE,
  text      text NOT NULL,
  lang      text NOT NULL CHECK (lang IN ('en', 'ru')),
  source    text NOT NULL CHECK (source IN ('wordnet', 'wiktionary', 'generated')),
  quality   real NOT NULL CHECK (quality > 0 AND quality <= 1),
  -- generated definitions must always rank below dictionary ones
  CONSTRAINT generated_quality_cap CHECK (source <> 'generated' OR quality <= 0.5)
);
CREATE INDEX definitions_lexeme_idx ON definitions (lexeme_id);

CREATE TABLE questions (
  id          text PRIMARY KEY,
  trainer     text NOT NULL,
  lexeme_id   text NOT NULL REFERENCES lexemes (id) ON DELETE CASCADE,
  lang        text NOT NULL CHECK (lang IN ('en', 'ru')),
  distractors text[] NOT NULL DEFAULT '{}',
  status      text NOT NULL CHECK (status IN ('ok', 'needs_review')),
  reasons     text[] NOT NULL DEFAULT '{}',
  CONSTRAINT ok_needs_two_distractors CHECK (status <> 'ok' OR cardinality(distractors) >= 2)
);
CREATE INDEX questions_lexeme_idx ON questions (lexeme_id);
CREATE INDEX questions_status_idx ON questions (status);

-- Language policy: Russian is allowed only for A1–A2 questions.
CREATE FUNCTION enforce_question_lang() RETURNS trigger AS $$
BEGIN
  IF NEW.lang = 'ru' AND (SELECT level FROM lexemes WHERE id = NEW.lexeme_id) NOT IN ('A1', 'A2') THEN
    RAISE EXCEPTION 'Russian definitions are only allowed for A1-A2 (question %)', NEW.id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER questions_lang_policy BEFORE INSERT OR UPDATE ON questions
  FOR EACH ROW EXECUTE FUNCTION enforce_question_lang();

-- Anonymous progress (no accounts: a random device id generated on the client)
CREATE TABLE devices (
  id            uuid PRIMARY KEY,
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE attempt_events (
  id          uuid PRIMARY KEY,
  device_id   uuid NOT NULL REFERENCES devices (id) ON DELETE CASCADE,
  trainer     text NOT NULL,
  entry_id    text NOT NULL,
  level       text NOT NULL CHECK (level IN ('A1', 'A2', 'B1', 'B2', 'C1', 'C2')),
  lang        text NOT NULL CHECK (lang IN ('en', 'ru')),
  correct     boolean NOT NULL,
  answer_id   text NOT NULL,
  answered_at timestamptz NOT NULL,
  duration_ms integer NOT NULL CHECK (duration_ms >= 0),
  received_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX attempt_events_device_idx ON attempt_events (device_id, answered_at);

-- Content metadata (manifest written by the seed)
CREATE TABLE content_meta (
  key   text PRIMARY KEY,
  value jsonb NOT NULL
);
