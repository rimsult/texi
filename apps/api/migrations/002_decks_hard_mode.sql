-- Word sets (general CEFR vocabulary / technical vocabulary) and hard mode.
ALTER TABLE lexemes ADD COLUMN deck text NOT NULL DEFAULT 'general' CHECK (deck IN ('general', 'tech'));
ALTER TABLE lexemes ADD COLUMN domain text;      -- technical field (it, physics, …), tech deck only
ALTER TABLE lexemes ADD COLUMN hard_group text;  -- hard-mode group when it differs from semantic_group
ALTER TABLE lexemes ADD CONSTRAINT tech_ids_prefixed CHECK ((deck = 'tech') = (id LIKE 'tech:%'));
CREATE INDEX lexemes_deck_level_idx ON lexemes (deck, level);

-- Same-group distractors for hard mode, most similar first (empty = no hard question).
ALTER TABLE questions ADD COLUMN hard_distractors text[] NOT NULL DEFAULT '{}';
ALTER TABLE questions ADD CONSTRAINT hard_needs_two_distractors
  CHECK (cardinality(hard_distractors) = 0 OR cardinality(hard_distractors) >= 2);

ALTER TABLE attempt_events ADD COLUMN deck text NOT NULL DEFAULT 'general' CHECK (deck IN ('general', 'tech'));
ALTER TABLE attempt_events ADD COLUMN difficulty text NOT NULL DEFAULT 'normal' CHECK (difficulty IN ('normal', 'hard'));
