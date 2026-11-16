import { describe, expect, it } from "vitest";
import spec from "../../../openapi.json";
import { LABELS } from "./labels";

const schemas = spec.components.schemas as Record<string, { enum?: string[] }>;
const API_LABELS = schemas.Label?.enum ?? [];
const infos = Object.values(LABELS);

describe("LABELS", () => {
  it("has exactly the labels in openapi.json's Label enum", () => {
    expect(API_LABELS.length).toBeGreaterThan(0);
    expect(Object.keys(LABELS).sort()).toEqual([...API_LABELS].sort());
  });

  it("gives every label a distinct glyph, so none relies on colour alone", () => {
    expect(new Set(infos.map((info) => info.glyph)).size).toBe(infos.length);
  });

  it("gives every label a distinct name", () => {
    expect(new Set(infos.map((info) => info.name)).size).toBe(infos.length);
  });

  it.each(Object.entries(LABELS))("%s has a non-empty glyph, name and meaning", (_label, info) => {
    expect(info.glyph.trim()).not.toBe("");
    expect(info.name.trim()).not.toBe("");
    expect(info.meaning.trim()).not.toBe("");
  });
});
