import type { ComponentType } from "react";
import type { BaseQuestion } from "@lexi/core";
import { McqCard } from "./McqCard";

export interface RendererProps<Q extends BaseQuestion = BaseQuestion> {
  question: Q;
  chosen: string | null;
  correctId: string | null;
  onAnswer: (answer: string) => void;
  /** Technical field id -> label, for the tech deck. */
  fields?: Record<string, string>;
}

/** UI renderer per question `kind`. A new trainer type only adds an entry here. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const RENDERERS: Record<string, ComponentType<RendererProps<any>>> = {
  mcq: McqCard,
};
