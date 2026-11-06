-- Level-adaptive definitions: learner definitions from Simple English Wiktionary
-- (source 'simple') for lower levels, plus richer feedback after answering: the
-- example's Russian translation (A1–A2) and common synonyms.
ALTER TABLE definitions DROP CONSTRAINT definitions_source_check;
ALTER TABLE definitions ADD CONSTRAINT definitions_source_check
  CHECK (source IN ('wordnet', 'wiktionary', 'simple', 'generated', 'machine'));
ALTER TABLE lexemes ADD COLUMN example_ru text;
ALTER TABLE lexemes ADD COLUMN synonyms text[] NOT NULL DEFAULT '{}';
