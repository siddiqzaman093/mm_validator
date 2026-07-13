import {
  AI_PROVIDER, AI_PROVIDER_LABEL,
  AI_MODEL, AI_MODEL_LABEL,
} from '../aiConfig'

export default function AiConfigPage() {
  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* Page header */}
      <div>
        <h2 className="text-xl font-bold text-slate-800">AI Configuration</h2>
        <p className="text-sm text-slate-500 mt-0.5">
          Admin Activities — provider, key and model used for the AI-Enabled Validations.
        </p>
      </div>

      <div className="card p-6">
        <div className="flex items-center gap-2 mb-1">
          <svg className="w-5 h-5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          <h3 className="text-base font-bold text-slate-800">Admin Activities</h3>
        </div>
        <p className="text-xs text-slate-500 mb-4">
          AI configuration (applied for all users when <strong>AI-Enabled Validations</strong> is enabled).
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">AI Provider</label>
            <select className="input text-sm bg-slate-100 cursor-not-allowed" value={AI_PROVIDER} disabled>
              <option value={AI_PROVIDER}>{AI_PROVIDER_LABEL}</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">OpenAI API Key</label>
            <input
              type="text"
              className="input text-sm bg-slate-100 cursor-not-allowed text-slate-400"
              value="•••••••• configured on server"
              disabled
              readOnly
            />
            <p className="mt-1 text-xs text-slate-400">
              Stored as the <code className="bg-slate-100 px-1 rounded">OPENAI_API_KEY</code> environment
              variable on the backend — never sent to the browser.
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Model</label>
            <select className="input text-sm bg-slate-100 cursor-not-allowed" value={AI_MODEL} disabled>
              <option value={AI_MODEL}>{AI_MODEL_LABEL}</option>
            </select>
          </div>
        </div>
      </div>
    </div>
  )
}
