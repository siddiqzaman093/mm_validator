// ---------------------------------------------------------------------------
// AI configuration shown under "Admin Activities → AI Configuration" (admin
// only) and applied for every user when "AI Warning Flags" is enabled.
//
// The API key is intentionally NOT here — it lives in a backend environment
// variable (OPENAI_API_KEY) so it is never shipped to browsers. The backend
// falls back to that env var whenever the client sends no key.
// ---------------------------------------------------------------------------
export const AI_PROVIDER       = 'openai'
export const AI_PROVIDER_LABEL = 'OpenAI (GPT)'
export const AI_MODEL          = 'gpt-5.4'
export const AI_MODEL_LABEL    = 'GPT-5.4'
