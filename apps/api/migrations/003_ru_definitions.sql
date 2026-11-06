-- Russian definitions are offline machine translations of the English definitions
-- (source 'machine'); the short word translation is kept separately and shown after
-- answering a Russian question.
ALTER TABLE definitions DROP CONSTRAINT definitions_source_check;
ALTER TABLE definitions ADD CONSTRAINT definitions_source_check
  CHECK (source IN ('wordnet', 'wiktionary', 'generated', 'machine'));
ALTER TABLE lexemes ADD COLUMN translation text;
