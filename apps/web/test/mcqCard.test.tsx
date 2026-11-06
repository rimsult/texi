import { definitionToWord, gapFill, Lexicon, createRng, type McqQuestion, wordToDefinition } from "@lexi/core";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { world } from "../../../packages/core/test/fixtures";
import { I18nProvider } from "../src/i18n";
import { Highlighted, McqCard } from "../src/ui/McqCard";

/** A1 world where "dog" has a learner definition with the headword masked as "___". */
function question(direction: "w2d" | "d2w", lang: "ru" | "en" = "en"): McqQuestion {
  const packs = world();
  const dog = packs[0]!.entries[0]!;
  dog.definitions = [
    { text: "an animal that people keep as a pet; ___ can bark", lang: "en", source: "simple", quality: 0.95 },
    { text: "животное, которое люди держат дома; собаки лают", lang: "ru", source: "machine", quality: 0.7 },
  ];
  Object.assign(dog, { example: "My dog likes to play.", exampleRu: "Моя собака любит играть.", synonyms: ["hound"] });
  const trainer = direction === "w2d" ? wordToDefinition : definitionToWord;
  return trainer.build("dog-n", { lexicon: new Lexicon(packs), level: "A1", preferredLang: lang, rng: createRng(4) })!;
}

const card = (q: McqQuestion, chosen: string | null, ui: "ru" | "en" = "ru") =>
  render(
    <I18nProvider lang={ui}>
      <McqCard question={q} chosen={chosen} correctId={q.correctOptionId} onAnswer={() => {}} />
    </I18nProvider>,
  );

describe("McqCard", () => {
  it("shows the masked word as a gap and fills it after answering", () => {
    const q = question("d2w");
    const { unmount } = card(q, null);
    expect(screen.getByTestId("prompt")).toHaveTextContent("an animal that people keep as a pet; ___ can bark");
    expect(screen.getByTestId("prompt").querySelector(".gap")).not.toBeNull();
    unmount();
    const wrong = q.options.find((o) => o.id !== q.correctOptionId)!;
    card(q, wrong.id);
    expect(screen.getByTestId("prompt")).toHaveTextContent("an animal that people keep as a pet; dog can bark");
    expect(screen.getByTestId("why")).toHaveTextContent(`Вы выбрали ${wrong.explain.lemma} — означает:`);
  });

  it("feedback lists translation, example with its translation, synonyms and the English original", () => {
    const q = question("w2d", "ru");
    const wrong = q.options.find((o) => o.id !== q.correctOptionId)!;
    card(q, wrong.id);
    const feedback = screen.getByTestId("feedback");
    const fact = (name: string) => within(feedback).getByText(name).nextElementSibling!;
    expect(fact("Перевод")).toHaveTextContent("собака");
    expect(fact("Пример")).toHaveTextContent("«My dog likes to play.»Моя собака любит играть.");
    expect(fact("Пример").querySelector("mark")).toHaveTextContent("dog");
    expect(fact("Синонимы")).toHaveTextContent("hound");
    expect(fact("Оригинал")).toHaveTextContent("an animal that people keep as a pet; dog can bark");
    expect(screen.getByTestId("why")).toHaveTextContent(`Вы выбрали определение слова ${wrong.explain.lemma}`);
  });

  it("speaks English when the interface is English", () => {
    const q = question("w2d", "en");
    card(q, q.correctOptionId, "en");
    expect(screen.getByTestId("feedback")).toHaveTextContent("Correct!");
    expect(within(screen.getByTestId("feedback")).getByText("Example")).toBeInTheDocument();
    expect(screen.queryByTestId("why")).toBeNull();
  });

  it("gap-fill: shows the sentence with a/an and a gap, then the word in place", () => {
    const packs = world();
    const [dog, apple, table] = packs[0]!.entries;
    Object.assign(apple!, { example: "I ate an apple for lunch.", exampleRu: "Я съел яблоко на обед." });
    packs[0]!.questions.push({
      trainer: "gap-fill", entryId: apple!.id, lang: "en", distractors: [dog!.id, table!.id],
      span: [9, 14], forms: ["apple", "dogs", "table"],
    });
    const q = gapFill.build(apple!.id, { lexicon: new Lexicon(packs), level: "A1", preferredLang: "ru", rng: createRng(2) })!;
    const { unmount } = card(q, null);
    expect(screen.getByTestId("prompt")).toHaveTextContent("I ate a/an ___ for lunch.");
    expect(screen.getByText("Вставьте пропущенное слово")).toBeInTheDocument();
    unmount();
    card(q, dog!.id);
    expect(screen.getByTestId("prompt")).toHaveTextContent("I ate an apple for lunch.");
    expect(screen.getByTestId("prompt").querySelector(".gap--filled")).toHaveTextContent("apple");
    // the wrong option tells its dictionary form and meaning
    const explain = screen.getAllByTestId("option-explain").map((x) => x.textContent);
    expect(explain).toContain("dog — собака; одомашненное хищное млекопитающее");
    expect(screen.getByTestId("why")).toHaveTextContent("Вы выбрали dog (собака) — означает:");
    const feedback = screen.getByTestId("feedback");
    expect(within(feedback).getByText("Перевод предложения").nextElementSibling).toHaveTextContent("Я съел яблоко на обед.");
    expect(within(feedback).queryByText("Пример")).toBeNull();
  });
});

describe("Highlighted", () => {
  const marks = (text: string, word: string) => {
    const { container, unmount } = render(<p><Highlighted text={text} word={word} /></p>);
    const found = [...container.querySelectorAll("mark")].map((m) => m.textContent);
    expect(container).toHaveTextContent(text);
    unmount();
    return found;
  };

  it.each([
    ["Dogs run. She is running and he ran.", "run", ["run", "running"]],
    ["They stopped and went on.", "stop", ["stopped"]],
    ["She studied; he studies.", "study", ["studied", "studies"]],
    ["He was making tea for the maker.", "make", ["making", "maker"]],
    ["I want to be a doctor because it has been my dream.", "be", ["be", "been"]],
    ["A cat and an apple.", "a", ["A"]],
    ["Write full stops at the end.", "full stop", ["full stops"]],
    ["Most children speak well.", "child", ["children"]],
    ["I borrow books and keep them in a bookcase.", "book", ["books"]],
  ])("%s → %s", (text, word, expected) => {
    expect(marks(text, word)).toEqual(expected);
  });
});
