import type { BaseQuestion, TrainerPlugin } from "./trainer";
import { gapFill } from "./trainers/gapFill";
import { definitionToWord, wordToDefinition } from "./trainers/meaningChoice";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyTrainer = TrainerPlugin<any, any>;

export class TrainerRegistry {
  private plugins = new Map<string, AnyTrainer>();

  register<Q extends BaseQuestion, A>(plugin: TrainerPlugin<Q, A>): this {
    if (this.plugins.has(plugin.id)) throw new Error(`Trainer "${plugin.id}" is already registered`);
    this.plugins.set(plugin.id, plugin);
    return this;
  }

  get(id: string): AnyTrainer | undefined {
    return this.plugins.get(id);
  }

  list(): AnyTrainer[] {
    return [...this.plugins.values()];
  }

  ready(): AnyTrainer[] {
    return this.list().filter((p) => p.availability === "ready");
  }
}

/** Placeholder for roadmap trainers: shown in the UI, produces no questions. */
export function comingSoon(id: string, title: string, subtitle: string, icon: string, kind: string): TrainerPlugin {
  return {
    id, title, subtitle, icon, kind,
    availability: "soon",
    items: () => [],
    build: () => null,
    check: () => ({ correct: false, correctAnswerId: "" }),
  };
}

export function createDefaultRegistry(): TrainerRegistry {
  return new TrainerRegistry()
    .register(wordToDefinition)
    .register(definitionToWord)
    .register(gapFill)
    .register(comingSoon("listening", "Аудирование", "Услышьте слово — выберите значение.", "🎧", "audio-mcq"))
    .register(comingSoon("grammar", "Грамматика", "Формы слов и конструкции.", "🧩", "grammar"));
}
