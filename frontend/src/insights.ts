import { themeName, signed } from "./format";
import type { AnalysisResult } from "./types";

export type Insight = [title: string, body: string];

/** Plain-language takeaways derived from the raw analysis. */
export function buildInsights(result: AnalysisResult): Insight[] {
  const out: Insight[] = [];
  const { tone } = result;
  const { scores, label } = tone;
  const c = scores.compound;

  if (label === "positive" && scores.neg >= 0.05) {
    out.push(["Positive, with friction",
      `The overall read is positive (${signed(c)}), but ${(scores.neg * 100).toFixed(0)}% ` +
      "of the language is negative. There are complaints mixed in."]);
  } else if (label === "negative" && scores.pos >= 0.05) {
    out.push(["Negative, not hostile",
      `The overall read is negative (${signed(c)}), though ${(scores.pos * 100).toFixed(0)}% ` +
      "of the language is still positive."]);
  } else {
    out.push([`Reads ${label}`,
      `Compound sentiment is ${signed(c)} on a −1 to +1 scale; ` +
      `${(scores.neu * 100).toFixed(0)}% of the wording is neutral.`]);
  }

  const { themes } = result;
  if (themes.dominant.length) {
    const ranked = Object.entries(themes.scores).sort((a, b) => b[1] - a[1]);
    const lead = themes.dominant.map(themeName).join(" & ");
    let body = `${lead} leads with ${ranked[0][1]} trigger words`;
    if (ranked.length > themes.dominant.length) {
      const [runner, n] = ranked[themes.dominant.length];
      body += `, ahead of ${themeName(runner).toLowerCase()} (${n})`;
    }
    out.push([`Mostly about ${lead.toLowerCase()}`, body + "."]);
  } else {
    out.push(["No clear theme", "None of the tracked themes are mentioned in this text."]);
  }

  const kws = result.top_keywords;
  if (kws.length && kws[0].count > 1) {
    out.push([`“${kws[0].word}” keeps coming back`,
      `It's the most frequent content word, used ${kws[0].count} times.`]);
  } else if (kws.length) {
    out.push(["Varied vocabulary", "No content word repeats, so there's no single recurring subject."]);
  }

  const avg = result.sentence_count ? result.word_count / result.sentence_count : 0;
  const ind = tone.indicators;
  if (ind.uppercase_word_ratio >= 0.05 || ind.exclamation_count >= 3) {
    out.push(["Raised voice",
      `${ind.exclamation_count} exclamation marks and ` +
      `${(ind.uppercase_word_ratio * 100).toFixed(0)}% all-caps words suggest strong emotion.`]);
  } else if (ind.question_count) {
    out.push(["Open questions",
      `The writer asks ${ind.question_count} question${ind.question_count !== 1 ? "s" : ""}; ` +
      "they may expect a reply."]);
  } else {
    out.push(["Measured delivery",
      `About ${avg.toFixed(0)} words per sentence, with no questions and little emphasis.`]);
  }
  return out;
}
