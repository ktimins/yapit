/**
 * Whether a block has anything a TTS model could voice. A block of symbols,
 * dashes or emoji is silence, not a failure — the worker skips it without
 * error, the same answer the server gives for blocks it cannot synthesize.
 */
export function isSpeakable(text: string): boolean {
  return /[\p{L}\p{N}]/u.test(text);
}
