-- Optional gap-fill trainer ("Вставьте слово"): the question points at the word inside
-- the lexeme's example sentence and lists the word forms of the answer and distractors
-- (aligned with [lexeme_id, ...distractors]), e.g. {ate, slept, drank}.
ALTER TABLE questions ADD COLUMN gap_span integer[];
ALTER TABLE questions ADD COLUMN gap_forms text[];
ALTER TABLE questions ADD CONSTRAINT gap_fill_shape CHECK (
  (trainer <> 'gap-fill' AND gap_span IS NULL AND gap_forms IS NULL)
  OR (trainer = 'gap-fill' AND lang = 'en' AND cardinality(gap_span) = 2 AND gap_span[1] >= 0 AND gap_span[2] > gap_span[1]
      AND cardinality(gap_forms) = cardinality(distractors) + 1)
);
